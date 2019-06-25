# -*- coding: future_fstrings -*-

import traceback
import sys
import time
import os
from concurrent import futures
import datetime
from random import shuffle

from requests.auth import HTTPDigestAuth
from common.logger import get_logger
from sumoclient.httputils import ClientMixin
from omnistorage.factory import ProviderFactory
from sumoclient.utils import get_current_timestamp
from common.config import Config
from api import ProcessMetricsAPI, ProjectEventsAPI, OrgEventsAPI, DiskMetricsAPI, LogAPI, AlertsAPI, DatabaseMetricsAPI


class MongoDBAtlasCollector(object):

    CONFIG_FILENAME = "mongodbatlas.yaml"
    DATA_REFRESH_TIME = 60*60*1000

    def __init__(self):
        self.start_time = datetime.datetime.utcnow()
        cfgpath = sys.argv[1] if len(sys.argv) > 1 else ''
        self.root_dir = self.get_current_dir()
        self.config = Config().get_config(self.CONFIG_FILENAME, self.root_dir, cfgpath)
        self.log = get_logger(__name__, force_create=True, **self.config['Logging'])
        self.collection_config = self.config['Collection']
        self.api_config = self.config['MongoDBAtlas']
        op_cli = ProviderFactory.get_provider(self.collection_config['ENVIRONMENT'])
        self.kvstore = op_cli.get_storage("keyvalue", name=self.config['Collection']['DBNAME'])
        self.digestauth = HTTPDigestAuth(username=self.api_config['PUBLIC_KEY'], password=self.api_config['PRIVATE_KEY'])

    def get_current_dir(self):
        cur_dir = os.path.dirname(__file__)
        return cur_dir

    def getpaginateddata(self, url, **kwargs):
        page_num = 0
        all_data = []
        sess = ClientMixin.get_new_session()
        try:
            while True:
                page_num += 1
                status, data = ClientMixin.make_request(url, method="get", session=sess, TIMEOUT=60, **kwargs)
                if status and "results" in data and len(data['results']) > 0:
                    all_data.append(data)
                    kwargs['params']['pageNum'] = page_num + 1
                else:
                    break
        finally:
            sess.close()
        return all_data

    def _get_all_databases(self, process_ids):
        database_names = []
        for process_id in process_ids:
            url = f'''{self.api_config['BASE_URL']}/groups/{self.api_config['PROJECT_ID']}/processes/{process_id}/databases'''
            kwargs = {'auth': self.digestauth, "params": {"itemsPerPage": self.api_config['PAGINATION_LIMIT']}}
            all_data = self.getpaginateddata(url, **kwargs)
            database_names.extend([obj['databaseName'] for data in all_data for obj in data['results']])
        return list(set(database_names))

    def _get_all_processes_from_project(self):
        url = f'''{self.api_config['BASE_URL']}/groups/{self.api_config['PROJECT_ID']}/processes'''
        kwargs = {'auth': self.digestauth, "params": {"itemsPerPage": self.api_config['PAGINATION_LIMIT']}}
        all_data = self.getpaginateddata(url, **kwargs)
        process_ids = [obj['id'] for data in all_data for obj in data['results']]
        hostnames = [obj['hostname'] for data in all_data for obj in data['results']]
        # 'port': 27017, 'replicaSetName': 'M10AWSTestCluster-config-0', 'typeName': 'SHARD_CONFIG_PRIMARY'

        hostnames = list(set(hostnames))
        return process_ids, hostnames

    def _get_all_disks_from_host(self, process_ids):
        disks = []
        for process_id in process_ids:
            url = f'''{self.api_config['BASE_URL']}/groups/{self.api_config['PROJECT_ID']}/processes/{process_id}/disks'''
            kwargs = {'auth': self.digestauth, "params": {"itemsPerPage": self.api_config['PAGINATION_LIMIT']}}
            all_data = self.getpaginateddata(url, **kwargs)
            disks.extend([obj['partitionName'] for data in all_data for obj in data['results']])
        return list(set(disks))

    def _set_database_names(self, process_ids):
        database_names = self._get_all_databases(process_ids)
        self.kvstore.set("database_names", {"last_set_date": get_current_timestamp(milliseconds=True), "values": database_names})

    def _set_processes(self):
        process_ids, hostnames = self._get_all_processes_from_project()
        self.kvstore.set("processes", {"last_set_date": get_current_timestamp(milliseconds=True), "process_ids": process_ids, "hostnames": hostnames})

    def _set_disk_names(self, process_ids):
        disks = self._get_all_disks_from_host(process_ids)
        self.kvstore.set("disk_names", {"last_set_date": get_current_timestamp(milliseconds=True), "values": disks})

    def _get_database_names(self):
        if not self.kvstore.has_key('database_names'):
            process_ids, _ = self._get_process_names()
            self._set_database_names(process_ids)

        current_timestamp = get_current_timestamp(milliseconds=True)
        if current_timestamp - self.kvstore.get('database_names')['last_set_date'] > self.DATA_REFRESH_TIME:
            process_ids, _ = self._get_process_names()
            self._set_database_names(process_ids)

        database_names = self.kvstore.get('database_names')['values']
        return database_names

    def _get_disk_names(self):
        if not self.kvstore.has_key('disk_names'):
            process_ids, _ = self._get_process_names()
            self._set_disk_names(process_ids)

        current_timestamp = get_current_timestamp(milliseconds=True)
        if current_timestamp - self.kvstore.get('disk_names')['last_set_date'] > self.DATA_REFRESH_TIME:
            process_ids, _ = self._get_process_names()
            self._set_disk_names(process_ids)

        disk_names = self.kvstore.get('disk_names')["values"]
        return disk_names

    def _get_process_names(self):
        if not self.kvstore.has_key('processes'):
            self._set_processes()

        current_timestamp = get_current_timestamp()
        if current_timestamp - self.kvstore.get('processes')['last_set_date'] > self.DATA_REFRESH_TIME:
            self._set_processes()

        processes = self.kvstore.get('processes')
        process_ids, hostnames = processes['process_ids'], processes['hostnames']
        return process_ids, hostnames

    def is_running(self):
        self.log.info("Acquiring single instance lock")
        return self.kvstore.acquire_lock('is_running')

    def stop_running(self):
        self.log.info("Releasing single instance lock")
        return self.kvstore.release_lock('is_running')

    def build_task_params(self):

        audit_files = ["mongodb-audit-log.gz", "mongos-audit-log.gz"]
        dblog_files = ["mongodb.gz", "mongos.gz"]
        filenames = []
        tasks = []
        process_ids, hostnames = self._get_process_names()

        if 'LOG_TYPES' in self.api_config:
            if "DATABASE" in self.api_config['LOG_TYPES']:
                filenames.extend(dblog_files)
            if "AUDIT" in self.api_config['LOG_TYPES']:
                filenames.extend(audit_files)

            for filename in filenames:
                for hostname in hostnames:
                    tasks.append(LogAPI(self.kvstore, hostname, filename, self.config))

            if "EVENTS_PROJECT" in self.api_config['LOG_TYPES']:
                tasks.append(ProjectEventsAPI(self.kvstore, self.config))

            if "EVENTS_ORG" in self.api_config['LOG_TYPES']:
                tasks.append(OrgEventsAPI(self.kvstore, self.config))

            if "ALERTS" in self.api_config['LOG_TYPES']:
                tasks.append(AlertsAPI(self.kvstore, self.config))

        if 'METRIC_TYPES' in self.api_config:
            if "PROCESS_METRICS" in self.api_config['METRIC_TYPES']:
                for process_id in process_ids:
                    tasks.append(ProcessMetricsAPI(self.kvstore, process_id, self.config))

            if "DISK_METRICS" in self.api_config['METRIC_TYPES']:
                disk_names = self._get_disk_names()
                for process_id in process_ids:
                    for disk_name in disk_names:
                        tasks.append(DiskMetricsAPI(self.kvstore, process_id, disk_name, self.config))

            if "DATABASE_METRICS" in self.api_config['METRIC_TYPES']:
                database_names = self._get_database_names()
                for process_id in process_ids:
                    for database_name in database_names:
                        tasks.append(DatabaseMetricsAPI(self.kvstore, process_id, database_name, self.config))

        return tasks

    def run(self):
        if self.is_running():
            try:
                self.log.info('Starting MongoDB Atlas Forwarder...')
                task_params = self.build_task_params()
                shuffle(task_params)
                all_futures = {}
                self.log.info("spawning %d workers" % self.config['Collection']['NUM_WORKERS'])
                with futures.ThreadPoolExecutor(max_workers=self.config['Collection']['NUM_WORKERS']) as executor:
                    results = {executor.submit(apiobj.fetch): apiobj for apiobj in task_params}
                    all_futures.update(results)
                for future in futures.as_completed(all_futures):
                    param = all_futures[future]
                    api_type = str(param)
                    try:
                        future.result()
                        obj = self.kvstore.get(api_type)
                    except Exception as exc:
                        self.log.error(f'''API Type: {api_type} thread generated an exception: {exc}''', exc_info=True)
                    else:
                        self.log.info(f'''API Type: {api_type} thread completed {obj}''')
            finally:
                self.stop_running()

    def test(self):
        if self.is_running():
            task_params = self.build_task_params()
            shuffle(task_params)
            try:
                for apiobj in task_params:
                    apiobj.fetch()
                    # print(apiobj.__class__.__name__)
            finally:
                self.stop_running()


def main(context=None):

    try:
        ns = MongoDBAtlasCollector()
        ns.run()
        # ns.test()
    except BaseException as e:
        traceback.print_exc()


if __name__ == '__main__':
    main()
