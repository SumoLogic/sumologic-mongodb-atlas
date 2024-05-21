# -*- coding: utf-8 -*-

import os
import traceback
from concurrent import futures
from random import shuffle

from requests.auth import HTTPDigestAuth
from sumoappclient.common.utils import get_current_timestamp
from sumoappclient.sumoclient.base import BaseCollector
from sumoappclient.sumoclient.httputils import ClientMixin

from api import (AlertsAPI, DatabaseMetricsAPI, DiskMetricsAPI, LogAPI,
                 OrgEventsAPI, ProcessMetricsAPI, ProjectEventsAPI)


class MongoDBAtlasCollector(BaseCollector):
    """
    Design Doc: https://docs.google.com/document/d/15TgilyyuGTMjRIZUXVJa1UhpTu3wS-gMl-dDsXAV2gw/edit?usp=sharing
    """

    SINGLE_PROCESS_LOCK_KEY = "is_mongodbatlascollector_running"
    CONFIG_FILENAME = "mongodbatlas.yaml"
    DATA_REFRESH_TIME = 60 * 60 * 1000

    def __init__(self):
        self.project_dir = self.get_current_dir()
        super(MongoDBAtlasCollector, self).__init__(self.project_dir)
        self.api_config = self.config["MongoDBAtlas"]
        self.digestauth = HTTPDigestAuth(
            username=self.api_config["PUBLIC_API_KEY"],
            password=self.api_config["PRIVATE_API_KEY"],
        )
        self.mongosess = ClientMixin.get_new_session(
            MAX_RETRY=self.collection_config["MAX_RETRY"],
            BACKOFF_FACTOR=self.collection_config["BACKOFF_FACTOR"],
        )

    def get_current_dir(self):
        cur_dir = os.path.dirname(__file__)
        return cur_dir

    def getpaginateddata(self, url, **kwargs):
        page_num = 0
        all_data = []

        while True:
            page_num += 1
            status, data = ClientMixin.make_request(
                url,
                method="get",
                session=self.mongosess,
                logger=self.log,
                TIMEOUT=self.collection_config["TIMEOUT"],
                MAX_RETRY=self.collection_config["MAX_RETRY"],
                BACKOFF_FACTOR=self.collection_config["BACKOFF_FACTOR"],
                **kwargs,
            )
            if status and "results" in data and len(data["results"]) > 0:
                all_data.append(data)
                kwargs["params"]["pageNum"] = page_num + 1
            else:
                break

        return all_data

    def _get_all_databases(self, process_ids):
        database_names = []
        for process_id in process_ids:
            url = f"{self.api_config['BASE_URL']}/groups/{self.api_config['PROJECT_ID']}/processes/{process_id}/databases"
            kwargs = {
                "auth": self.digestauth,
                "params": {"itemsPerPage": self.api_config["PAGINATION_LIMIT"]},
            }
            all_data = self.getpaginateddata(url, **kwargs)
            database_names.extend(
                [obj["databaseName"] for data in all_data for obj in data["results"]]
            )
        return list(set(database_names))

    def _get_cluster_name(self, fullname):
        return fullname.split("-shard")[0]

    def _get_all_processes_from_project(self):
        url = f"{self.api_config['BASE_URL']}/groups/{self.api_config['PROJECT_ID']}/processes"
        kwargs = {
            "auth": self.digestauth,
            "params": {"itemsPerPage": self.api_config["PAGINATION_LIMIT"]},
        }
        all_data = self.getpaginateddata(url, **kwargs)
        process_ids = [obj["id"] for data in all_data for obj in data["results"]]
        hostnames = [obj["hostname"] for data in all_data for obj in data["results"]]
        # 'port': 27017, 'replicaSetName': 'M10AWSTestCluster-config-0', 'typeName': 'SHARD_CONFIG_PRIMARY'
        cluster_mapping = {
            self._get_cluster_name(obj["hostname"]): self._get_cluster_name(
                obj["userAlias"]
            )
            for data in all_data
            for obj in data["results"]
        }
        hostnames = list(set(hostnames))
        return process_ids, hostnames, cluster_mapping

    def _get_all_disks_from_host(self, process_ids):
        disks = []
        for process_id in process_ids:
            url = f"{self.api_config['BASE_URL']}/groups/{self.api_config['PROJECT_ID']}/processes/{process_id}/disks"
            kwargs = {
                "auth": self.digestauth,
                "params": {"itemsPerPage": self.api_config["PAGINATION_LIMIT"]},
            }
            all_data = self.getpaginateddata(url, **kwargs)
            disks.extend(
                [obj["partitionName"] for data in all_data for obj in data["results"]]
            )
        return list(set(disks))

    def _set_database_names(self, process_ids):
        database_names = self._get_all_databases(process_ids)
        self.kvstore.set(
            "database_names",
            {
                "last_set_date": get_current_timestamp(milliseconds=True),
                "values": database_names,
            },
        )

    def _set_processes(self):
        (
            process_ids,
            hostnames,
            cluster_mapping,
        ) = self._get_all_processes_from_project()
        self.kvstore.set(
            "processes",
            {
                "last_set_date": get_current_timestamp(milliseconds=True),
                "process_ids": process_ids,
                "hostnames": hostnames,
            },
        )
        self.kvstore.set(
            "cluster_mapping",
            {
                "last_set_date": get_current_timestamp(milliseconds=True),
                "values": cluster_mapping,
            },
        )

    def _set_disk_names(self, process_ids):
        disks = self._get_all_disks_from_host(process_ids)
        self.kvstore.set(
            "disk_names",
            {
                "last_set_date": get_current_timestamp(milliseconds=True),
                "values": disks,
            },
        )

    def _get_database_names(self):
        if "database_names" not in self.kvstore:
            process_ids, _ = self._get_process_names()
            self._set_database_names(process_ids)

        current_timestamp = get_current_timestamp(milliseconds=True)
        databases = self.kvstore.get("database_names")
        if current_timestamp - databases["last_set_date"] > self.DATA_REFRESH_TIME or (
            len(databases["values"]) == 0
        ):
            process_ids, _ = self._get_process_names()
            self._set_database_names(process_ids)

        database_names = self.kvstore.get("database_names")["values"]
        return database_names

    def _get_disk_names(self):
        if "disk_names" not in self.kvstore:
            process_ids, _ = self._get_process_names()
            self._set_disk_names(process_ids)

        current_timestamp = get_current_timestamp(milliseconds=True)
        disks = self.kvstore.get("disk_names")
        if current_timestamp - disks["last_set_date"] > self.DATA_REFRESH_TIME or (
            len(disks["values"]) == 0
        ):
            process_ids, _ = self._get_process_names()
            self._set_disk_names(process_ids)

        disk_names = self.kvstore.get("disk_names")["values"]
        return disk_names

    def _get_process_names(self):
        if "processes" not in self.kvstore:
            self._set_processes()

        current_timestamp = get_current_timestamp(milliseconds=True)
        processes = self.kvstore.get("processes")
        if current_timestamp - processes["last_set_date"] > self.DATA_REFRESH_TIME or (
            len(processes["process_ids"]) == 0
        ):
            self._set_processes()

        processes = self.kvstore.get("processes")
        process_ids, hostnames = (
            processes["process_ids"],
            processes["hostnames"],
        )
        process_ids_copy = process_ids.copy()
        hostnames_copy = hostnames.copy()

        del process_ids
        del hostnames
        return process_ids_copy, hostnames_copy

    def is_running(self):
        self.log.debug("Acquiring single instance lock")
        return self.kvstore.acquire_lock(self.SINGLE_PROCESS_LOCK_KEY)

    def stop_running(self):
        self.log.debug("Releasing single instance lock")
        return self.kvstore.release_lock(self.SINGLE_PROCESS_LOCK_KEY)

    def build_task_params(self):
        audit_files = ["mongodb-audit-log.gz", "mongos-audit-log.gz"]
        dblog_files = ["mongodb.gz", "mongos.gz"]
        process_ids, hostnames = self._get_process_names()
        cluster_mapping = self.kvstore.get("cluster_mapping", {}).get("values", {})

        try:
            if "LOG_TYPES" in self.api_config:
                if "DATABASE" in self.api_config["LOG_TYPES"]:
                    for filename in dblog_files:
                        for hostname in hostnames:
                            yield LogAPI(
                                self.kvstore,
                                hostname,
                                filename,
                                self.config,
                                cluster_mapping,
                            )
                            del filename, hostname

                if "AUDIT" in self.api_config["LOG_TYPES"]:
                    for filename in audit_files:
                        for hostname in hostnames:
                            yield LogAPI(
                                self.kvstore,
                                hostname,
                                filename,
                                self.config,
                                cluster_mapping,
                            )
                            del filename, hostname

                if "EVENTS_PROJECT" in self.api_config["LOG_TYPES"]:
                    yield ProjectEventsAPI(self.kvstore, self.config)

                if "EVENTS_ORG" in self.api_config["LOG_TYPES"]:
                    yield OrgEventsAPI(self.kvstore, self.config)

                if "ALERTS" in self.api_config["LOG_TYPES"]:
                    yield AlertsAPI(self.kvstore, self.config)

            if "METRIC_TYPES" in self.api_config:
                if self.api_config["METRIC_TYPES"].get("PROCESS_METRICS", []):
                    for process_id in process_ids:
                        yield ProcessMetricsAPI(
                            self.kvstore,
                            process_id,
                            self.config,
                            cluster_mapping,
                        )
                        del process_id

                if self.api_config["METRIC_TYPES"].get("DISK_METRICS", []):
                    disk_names = self._get_disk_names()
                    for process_id in process_ids:
                        for disk_name in disk_names:
                            yield DiskMetricsAPI(
                                self.kvstore,
                                process_id,
                                disk_name,
                                self.config,
                                cluster_mapping,
                            )
                            del process_id, disk_name

                if self.api_config["METRIC_TYPES"].get("DATABASE_METRICS", []):
                    database_names = self._get_database_names()
                    for process_id in process_ids:
                        for database_name in database_names:
                            yield DatabaseMetricsAPI(
                                self.kvstore,
                                process_id,
                                database_name,
                                self.config,
                                cluster_mapping,
                            )
                            del process_id, database_name

        except Exception as e:
            self.log.error(
                f"An error occurred while building task parameters: {e}",
                exc_info=True,
            )
        finally:
            del (
                audit_files,
                dblog_files,
                process_ids,
                hostnames,
                cluster_mapping,
            )

        self.log.info("Generated task parameters")

    def run(self):
        if self.is_running():
            try:
                self.log.info("Starting MongoDB Atlas Forwarder...")
                task_params = self.build_task_params()
                task_params = list(task_params)
                shuffle(task_params)

                all_futures = {}
                num_workers = self.config["Collection"]["NUM_WORKERS"]
                self.log.debug(f"Spawning {num_workers} workers")

                with futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
                    results = {
                        executor.submit(apiobj.fetch): apiobj for apiobj in task_params
                    }
                    all_futures.update(results)

                for future in futures.as_completed(all_futures):
                    param = all_futures[future]
                    api_type = str(param)
                    try:
                        result = future.result()
                        del result
                    except Exception as exc:
                        self.log.error(
                            f"API Type: {api_type} thread generated an exception: {exc}",
                            exc_info=True,
                        )
                    else:
                        self.log.info(f"API Type: {api_type} thread completed")

                    del future
                    del param

                all_futures.clear()
                del task_params

            except Exception as e:
                self.log.error(f"An error occurred: {e}", exc_info=True)

            finally:
                self.stop_running()
                self.mongosess.close()
                del self.mongosess

        else:
            if not self.is_process_running(["sumomongodbatlascollector"]):
                self.kvstore.release_lock_on_expired_key(
                    self.SINGLE_PROCESS_LOCK_KEY, expiry_min=10
                )

    def test(self):
        if self.is_running():
            task_params = self.build_task_params()
            shuffle(task_params)
            # print(task_params)
            try:
                for apiobj in task_params:
                    apiobj.fetch()
                    # print(apiobj.__class__.__name__)
            finally:
                self.stop_running()


def main(*args, **kwargs):
    try:
        ns = MongoDBAtlasCollector()
        ns.run()
    except BaseException:
        traceback.print_exc()


if __name__ == "__main__":
    main()
