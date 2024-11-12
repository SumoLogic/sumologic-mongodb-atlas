import traceback
import os
from requests.auth import HTTPDigestAuth
from time_and_memory_tracker import TimeAndMemoryTracker

from sumoappclient.sumoclient.base import BaseCollector
from sumoappclient.sumoclient.httputils import ClientMixin
from sumoappclient.common.utils import get_current_timestamp
from api import (
    ProcessMetricsAPI,
    ProjectEventsAPI,
    OrgEventsAPI,
    DiskMetricsAPI,
    LogAPI,
    AlertsAPI,
    DatabaseMetricsAPI,
)


class MongoDBAtlasCollector(BaseCollector):
    """
    Design Doc: https://docs.google.com/document/d/15TgilyyuGTMjRIZUXVJa1UhpTu3wS-gMl-dDsXAV2gw/edit?usp=sharing
    """

    COLLECTOR_PROCESS_NAME = "sumomongodbatlascollector"
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
        # removing redundant handlers since AWS Lambda also sets up a handler, on the root logger
        if self.collection_config["ENVIRONMENT"] == "aws":
            for hdlr in self.log.handlers:
                self.log.removeHandler(hdlr)

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
                self.log.error(f"Error in making GET request to url: {url} status: {status} message: {data}")
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

    def _get_user_provided_cluster_name(self):
        if self.collection_config and self.collection_config.get("Clusters"):
            return self.collection_config.get("Clusters")
        return []

    def _get_all_processes_from_project(self):
        url = f"{self.api_config['BASE_URL']}/groups/{self.api_config['PROJECT_ID']}/processes"
        kwargs = {
            "auth": self.digestauth,
            "params": {"itemsPerPage": self.api_config["PAGINATION_LIMIT"]},
        }
        all_data = self.getpaginateddata(url, **kwargs)
        all_cluster_aliases = list({self._get_cluster_name(obj["userAlias"]) for data in all_data for obj in data["results"]})
        user_provided_clusters = self._get_user_provided_cluster_name()

        if len(all_cluster_aliases) > 0 and len(user_provided_clusters) > 0:
            cluster_mapping = {}
            process_ids = set()
            hostnames = set()
            for obj in all_data:
                for obj in obj["results"]:
                    cluster_alias = self._get_cluster_name(obj["userAlias"])
                    if cluster_alias in user_provided_clusters:
                        cluster_mapping[self._get_cluster_name(obj["hostname"])] = cluster_alias
                        process_ids.add(obj['id'])
                        hostnames.add(obj['hostname'])

            if not cluster_mapping:
                raise Exception(f"None of the user provided cluster matched the following cluster aliases: {','.join(all_cluster_aliases)}")
            process_ids = list(process_ids)
            hostnames = list(hostnames)
        else:
            process_ids = list({obj["id"] for data in all_data for obj in data["results"]})
            hostnames = list({obj["hostname"] for data in all_data for obj in data["results"]})
            cluster_mapping = {
                self._get_cluster_name(obj["hostname"]): self._get_cluster_name(
                    obj["userAlias"]
                )
                for data in all_data
                for obj in data["results"]
            }

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
        process_ids, hostnames, cluster_mapping = self._get_all_processes_from_project()
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
        if not self.kvstore.has_key("database_names"):
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
        if not self.kvstore.has_key("disk_names"):
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
        if not self.kvstore.has_key("processes"):
            self._set_processes()

        current_timestamp = get_current_timestamp(milliseconds=True)
        processes = self.kvstore.get("processes")
        if current_timestamp - processes["last_set_date"] > self.DATA_REFRESH_TIME or (
            len(processes["process_ids"]) == 0
        ):
            self._set_processes()

        processes = self.kvstore.get("processes")
        process_ids, hostnames = processes["process_ids"], processes["hostnames"]
        return process_ids, hostnames

    def build_task_params(self):
        with TimeAndMemoryTracker(activate=self.collection_config.get("ACTIVATE_TIME_AND_MEMORY_TRACKING", False)) as tracker:
            start_message = tracker.start("self.build_task_params")
        audit_files = ["mongodb-audit-log.gz", "mongos-audit-log.gz"]
        dblog_files = ["mongodb.gz", "mongos.gz"]
        filenames = []
        tasks = []
        process_ids, hostnames = self._get_process_names()
        cluster_mapping = self.kvstore.get("cluster_mapping", {}).get("values", {})

        if "LOG_TYPES" in self.api_config:
            if "DATABASE" in self.api_config["LOG_TYPES"]:
                filenames.extend(dblog_files)
            if "AUDIT" in self.api_config["LOG_TYPES"]:
                filenames.extend(audit_files)

            for filename in filenames:
                for hostname in hostnames:
                    tasks.append(
                        LogAPI(
                            self.kvstore,
                            hostname,
                            filename,
                            self.config,
                            cluster_mapping,
                        )
                    )

            if "EVENTS_PROJECT" in self.api_config["LOG_TYPES"]:
                tasks.append(ProjectEventsAPI(self.kvstore, self.config))

            if "EVENTS_ORG" in self.api_config["LOG_TYPES"]:
                tasks.append(OrgEventsAPI(self.kvstore, self.config))

            if "ALERTS" in self.api_config["LOG_TYPES"]:
                tasks.append(AlertsAPI(self.kvstore, self.config))

        if "METRIC_TYPES" in self.api_config:
            if self.api_config["METRIC_TYPES"].get("PROCESS_METRICS", []):
                for process_id in process_ids:
                    tasks.append(
                        ProcessMetricsAPI(
                            self.kvstore, process_id, self.config, cluster_mapping
                        )
                    )

            if self.api_config["METRIC_TYPES"].get("DISK_METRICS", []):
                disk_names = self._get_disk_names()
                for process_id in process_ids:
                    for disk_name in disk_names:
                        tasks.append(
                            DiskMetricsAPI(
                                self.kvstore,
                                process_id,
                                disk_name,
                                self.config,
                                cluster_mapping,
                            )
                        )

            if self.api_config["METRIC_TYPES"].get("DATABASE_METRICS", []):
                database_names = self._get_database_names()
                for process_id in process_ids:
                    for database_name in database_names:
                        tasks.append(
                            DatabaseMetricsAPI(
                                self.kvstore,
                                process_id,
                                database_name,
                                self.config,
                                cluster_mapping,
                            )
                        )

        end_message = tracker.end("self.build_task_params")
        self.log.info(f'''{len(tasks)} Tasks Generated {start_message} {end_message}''')
        if len(tasks) == 0:
            raise Exception("No tasks Generated")
        return tasks


def main(*args, **kwargs):
    try:
        ns = MongoDBAtlasCollector()
        ns.run()
        # ns.test()
    except BaseException as e:
        traceback.print_exc()


if __name__ == "__main__":
    main()
