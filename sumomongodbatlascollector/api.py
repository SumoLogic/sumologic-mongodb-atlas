# -*- coding: future_fstrings -*-

import gzip
import json
from abc import abstractmethod
from io import BytesIO
import datetime
from requests.auth import HTTPDigestAuth
from sumoclient.factory import OutputHandlerFactory
from sumoclient.utils import get_current_timestamp, convert_epoch_to_utc_date, convert_utc_date_to_epoch, convert_date_to_epoch
from common.logger import get_logger
from sumoclient.httputils import ClientMixin


class BaseAPI(object):
    # pagination/auth/abstracts
    MOVING_WINDOW_DELTA = 0.001
    STOP_TIME_OFFSET_SECONDS = 10
    FUNCTION_TIMEOUT = 5*60
    isoformat = '%Y-%m-%dT%H:%M:%S.%fZ'
    date_format = '%Y-%m-%dT%H:%M:%SZ'

    def __init__(self, kvstore, config):
        self.kvstore = kvstore
        self.config = config
        self.start_time = datetime.datetime.utcnow()
        self.sumo_config = config['SumoLogic']
        self.collection_config = self.config['Collection']
        self.api_config = self.config['MongoDBAtlas']
        self.digestauth = HTTPDigestAuth(username=self.api_config['PUBLIC_KEY'], password=self.api_config['PRIVATE_KEY'])
        self.DEFAULT_START_TIME_EPOCH = get_current_timestamp() - self.collection_config['BACKFILL_DAYS']*24*60*60
        self.log = get_logger(__name__, force_create=True, **self.config['Logging'])

    def get_function_timeout(self):
        timeout_config = {
            "onprem": float("Inf"),
            "aws": 15*60,
            "gcp": 5*60,
            "azure": 5*60
        }
        return timeout_config[self.collection_config['ENVIRONMENT']]

    def is_time_remaining(self):
        now = datetime.datetime.utcnow()
        time_passed =  (now - self.start_time).total_seconds()
        self.log.info("checking time_passed: %s" % time_passed)
        has_time = time_passed + self.STOP_TIME_OFFSET_SECONDS < self.get_function_timeout()
        if not has_time:
            self.log.info("Shutting down not enough time")
        return has_time

    def __str__(self):
        return self._get_key()

    @abstractmethod
    def _get_key(self):
        pass

    @abstractmethod
    def save_state(self, last_time_epoch):
        pass

    @abstractmethod
    def get_state(self):
        pass

    @abstractmethod
    def build_fetch_params(self):
        pass

    @abstractmethod
    def build_send_params(self):
        pass

    @abstractmethod
    def transform_data(self, content):
        pass

    @abstractmethod
    def fetch(self):
        pass

class LogAPI(BaseAPI):
    # single API
    MOVING_WINDOW_DELTA = 1 # This api does not take ms
    pathname = "db_logs.json"

    def __init__(self, kvstore, hostname, filename, config):
        super(LogAPI, self).__init__(kvstore, config)
        self.hostname = hostname
        self.filename = filename

    def _get_key(self):
        key = f'''{self.api_config['PROJECT_ID']}-{self.hostname}-{self.filename}'''
        return key

    def save_state(self, last_time_epoch):
        key = self._get_key()
        obj = {"last_time_epoch": last_time_epoch}
        self.kvstore.set(key, obj)

    def get_state(self):
        key = self._get_key()
        if not self.kvstore.has_key(key):
            self.save_state(self.DEFAULT_START_TIME_EPOCH)
        obj = self.kvstore.get(key)
        return obj

    def build_fetch_params(self):
        start_time_epoch = self.get_state()['last_time_epoch']+self.MOVING_WINDOW_DELTA
        end_time_epoch = get_current_timestamp() - self.collection_config['END_TIME_EPOCH_OFFSET_SECONDS']
        return f'''{self.api_config['BASE_URL']}/groups/{self.api_config['PROJECT_ID']}/clusters/{self.hostname}/logs/{self.filename}''', {
                "auth": self.digestauth,
                "params": {"startDate": int(start_time_epoch), "endDate": int(end_time_epoch)}, # this api does not take ms
                "headers": {"Accept": "application/gzip"},
                "is_file": True
            }

    def build_send_params(self):
        return {
            "extra_headers": {'X-Sumo-Name': self.filename},
            "endpoint_key": "LOGS_SUMO_ENDPOINT"
        }

    def transform_data(self, content):
        # assuming file content is small so inmemory possible
        # https://stackoverflow.com/questions/11914472/stringio-in-python3
        # https://stackoverflow.com/questions/8858414/using-python-how-do-you-untar-purely-in-memory
        all_logs = []
        last_time_epoch = self.DEFAULT_START_TIME_EPOCH
        results = gzip.GzipFile(fileobj=BytesIO(content))
        for line in results.readlines():
            if "audit" in self.filename:
                msg = json.loads(line.decode('utf-8'))
                msg['project_id'] = self.api_config['PROJECT_ID']
                msg['hostname'] = self.hostname
                msg['cluster_name'] = self.hostname.split("-", 1)[0].strip()
                current_date = msg['ts']['$date']

            else:
                msg = {
                    'msg': line.decode('utf-8').strip(),
                    'project_id': self.api_config['PROJECT_ID'],
                    'hostname': self.hostname,
                    'cluster_name': self.hostname.split("-", 1)[0].strip()
                }
                current_date = msg['msg'].split(" ", 1)[0]

            try:
                current_timestamp = convert_date_to_epoch(current_date.strip())
                msg['created'] = current_date # taking out date
                last_time_epoch = max(current_timestamp, last_time_epoch)
                all_logs.append(msg)
            except ValueError:
                all_logs[-1]['msg'] += msg['msg']

        return all_logs, {"last_time_epoch": last_time_epoch}

    def fetch(self):
        self.log.info(f'''getting logfile: {self.filename} hostname: {self.hostname} project_id: {self.api_config[
            'PROJECT_ID']}''')
        output_handler = OutputHandlerFactory.get_handler(self.collection_config['OUTPUT_HANDLER'], path=self.pathname, config=self.config)
        url, kwargs = self.build_fetch_params()
        try:

            fetch_success, content = ClientMixin.make_request(url, method="get", TIMEOUT=60, **kwargs)
            if fetch_success and len(content) > 0:
                payload, state = self.transform_data(content)
                #Make this atomic if after sending -> Ctrl - C happens then it fails to save state
                send_success = output_handler.send(payload, **self.build_send_params())
                if send_success:
                    self.save_state(**state)
                    self.log.info(f'''Successfully sent logfile: {self.filename} hostname: {self.hostname} project_id: {self.api_config[
            'PROJECT_ID']} Data: {len(content)}''')
                else:
                    self.log.error(f'''Failed to sent logfile: {self.filename} hostname: {self.hostname} project_id: {self.api_config[
            'PROJECT_ID']}''')
            else:
                self.log.info(f'''No results status: {fetch_success} reason: {content}''')
        finally:
            output_handler.close()


class ProcessMetricsAPI(BaseAPI):

    pathname = "process_metrics.log"

    def __init__(self, kvstore, process_id, config):
        super(ProcessMetricsAPI, self).__init__(kvstore, config)
        self.process_id = process_id

    def _get_key(self):
        key = f'''{self.api_config['PROJECT_ID']}-{self.process_id}'''
        return key

    def save_state(self, last_time_epoch):
        key = self._get_key()
        obj = {"last_time_epoch": last_time_epoch}
        self.kvstore.set(key, obj)


    def get_state(self):
        key = self._get_key()
        if not self.kvstore.has_key(key):
            self.save_state(self.DEFAULT_START_TIME_EPOCH)
        obj = self.kvstore.get(key)
        return obj


    def build_fetch_params(self):
        start_time_epoch = self.get_state()['last_time_epoch']+self.MOVING_WINDOW_DELTA
        end_time_epoch = get_current_timestamp() - self.collection_config['END_TIME_EPOCH_OFFSET_SECONDS']
        start_time_date = convert_epoch_to_utc_date(start_time_epoch, date_format=self.isoformat)
        end_time_date = convert_epoch_to_utc_date(end_time_epoch, date_format=self.isoformat)
        return f'''{self.api_config['BASE_URL']}/groups/{self.api_config['PROJECT_ID']}/processes/{self.process_id}/measurements''', {
                "auth": self.digestauth,
                "params": { "itemsPerPage": self.api_config['PAGINATION_LIMIT'], "granularity": "PT1M",
                            "start": start_time_date, "end": end_time_date
                    # , "m": self.api_config["METRIC_TYPES"]["PROCESS_METRICS"]
                }
        }

    def build_send_params(self):
        return {
            "extra_headers": {'Content-Type': 'application/vnd.sumologic.carbon2'},
            "endpoint_key": "METRICS_SUMO_ENDPOINT",
            "jsondump": False
        }

    def transform_data(self, data):
        metrics = []
        last_time_epoch = self.DEFAULT_START_TIME_EPOCH
        for measurement in data['measurements']:
            for datapoints in measurement['dataPoints']:
                if datapoints['value'] is None:
                    continue
                current_timestamp = convert_utc_date_to_epoch(datapoints['timestamp'], date_format=self.date_format)
                cluster_name = data['hostId'].split("-", 1)[0].strip()
                metrics.append(f'''projectId={data['groupId']} hostId={data['hostId']} processId={data['processId']} metric={measurement['name']}  units={measurement['units']} cluster_name={cluster_name} {datapoints['value']} {current_timestamp}''')
                last_time_epoch = max(current_timestamp, last_time_epoch)
        return metrics, {"last_time_epoch": last_time_epoch}

    def fetch(self):
        self.log.info(f'''getting process_id: {self.process_id} project_id: {self.api_config['PROJECT_ID']}''')
        output_handler = OutputHandlerFactory.get_handler(self.collection_config['OUTPUT_HANDLER'], path=self.pathname, config=self.config)
        url, kwargs = self.build_fetch_params()
        try:
            fetch_success, content = ClientMixin.make_request(url, method="get", TIMEOUT=60, **kwargs)
            if fetch_success and len(content) > 0:
                payload, state = self.transform_data(content)
                send_success = output_handler.send(payload, **self.build_send_params())
                if send_success:
                    self.save_state(**state)
                    self.log.info(f'''Successfully sent process_id: {self.process_id} project_id: {self.api_config['PROJECT_ID']} Data: {len(content)}''')
                else:
                    self.log.error(f'''Failed to sent process_id: {self.process_id} project_id: {self.api_config['PROJECT_ID']}''')
            else:
                self.log.info(f'''No results status: {fetch_success} reason: {content}''')
        finally:
            output_handler.close()


class DiskMetricsAPI(BaseAPI):
    isoformat = '%Y-%m-%dT%H:%M:%S.%fZ'
    date_format = '%Y-%m-%dT%H:%M:%SZ'
    pathname = "disk_metrics.log"

    def __init__(self, kvstore, process_id, disk_name, config):
        super(DiskMetricsAPI, self).__init__(kvstore, config)
        self.process_id = process_id
        self.disk_name = disk_name

    def _get_key(self):
        key = f'''{self.api_config['PROJECT_ID']}-{self.process_id}-{self.disk_name}'''
        return key

    def save_state(self, last_time_epoch):
        key = self._get_key()
        obj = {"last_time_epoch": last_time_epoch}
        self.kvstore.set(key, obj)


    def get_state(self):
        key = self._get_key()
        if not self.kvstore.has_key(key):
            self.save_state(self.DEFAULT_START_TIME_EPOCH)
        obj = self.kvstore.get(key)
        return obj

    def build_fetch_params(self):
        start_time_epoch = self.get_state()['last_time_epoch']+self.MOVING_WINDOW_DELTA
        end_time_epoch = get_current_timestamp() - self.collection_config['END_TIME_EPOCH_OFFSET_SECONDS']
        start_time_date = convert_epoch_to_utc_date(start_time_epoch, date_format=self.isoformat)
        end_time_date = convert_epoch_to_utc_date(end_time_epoch, date_format=self.isoformat)
        return f'''{self.api_config['BASE_URL']}/groups/{self.api_config['PROJECT_ID']}/processes/{self.process_id}/disks/{self.disk_name}/measurements''', {
            "auth": self.digestauth,
            "params": {"itemsPerPage": self.api_config['PAGINATION_LIMIT'], "granularity": "PT1M",
                       "start": start_time_date, "end": end_time_date
                       # "m": self.api_config["METRIC_TYPES"]["DISK_METRICS"]
            }
        }

    def build_send_params(self):
        return {
            "extra_headers": {'Content-Type': 'application/vnd.sumologic.carbon2'},
            "endpoint_key": "METRICS_SUMO_ENDPOINT",
            "jsondump": False
        }

    def transform_data(self, data):
        metrics = []
        last_time_epoch = self.DEFAULT_START_TIME_EPOCH
        for measurement in data['measurements']:
            for datapoints in measurement['dataPoints']:
                if datapoints['value'] is None:
                    continue
                current_timestamp = convert_utc_date_to_epoch(datapoints['timestamp'], date_format=self.date_format)
                cluster_name = data['hostId'].split("-", 1)[0].strip()
                metrics.append(f'''projectId={data['groupId']} partitionName={data['partitionName']} hostId={data['hostId']} processId={data['processId']} metric={measurement['name']}  units={measurement['units']} cluster_name={cluster_name} {datapoints['value']} {current_timestamp}''')
                last_time_epoch = max(current_timestamp, last_time_epoch)
        return metrics, {"last_time_epoch": last_time_epoch}

    def fetch(self):
        self.log.info(f'''getting process_id: {self.process_id} disk_name: {self.disk_name} project_id: {self.api_config['PROJECT_ID']}''')
        output_handler = OutputHandlerFactory.get_handler(self.collection_config['OUTPUT_HANDLER'], path=self.pathname, config=self.config)
        url, kwargs = self.build_fetch_params()
        try:
            fetch_success, content = ClientMixin.make_request(url, method="get", TIMEOUT=60, **kwargs)
            if fetch_success and len(content) > 0:
                payload, state = self.transform_data(content)
                send_success = output_handler.send(payload, **self.build_send_params())
                if send_success:
                    self.save_state(**state)
                    self.log.info(f'''Successfully sent process_id: {self.process_id} disk_name: {self.disk_name} project_id: {self.api_config['PROJECT_ID']} Data: {len(content)}''')
                else:
                    self.log.error(f'''Failed to sent process_id: {self.process_id} disk_name: {self.disk_name} project_id: {self.api_config['PROJECT_ID']}''')
            else:
                self.log.info(f'''No results status: {fetch_success} reason: {content}''')
        finally:
            output_handler.close()


class DatabaseMetricsAPI(BaseAPI):
    isoformat = '%Y-%m-%dT%H:%M:%S.%fZ'
    date_format = '%Y-%m-%dT%H:%M:%SZ'
    pathname = "database_metrics.log"

    def __init__(self, kvstore, process_id, database_name, config):
        super(DatabaseMetricsAPI, self).__init__(kvstore, config)
        self.process_id = process_id
        self.database_name = database_name

    def _get_key(self):
        key = f'''{self.api_config['PROJECT_ID']}-{self.process_id}-{self.database_name}'''
        return key

    def save_state(self, last_time_epoch):
        key = self._get_key()
        obj = {"last_time_epoch": last_time_epoch}
        self.kvstore.set(key, obj)


    def get_state(self):
        key = self._get_key()
        if not self.kvstore.has_key(key):
            self.save_state(self.DEFAULT_START_TIME_EPOCH)
        obj = self.kvstore.get(key)
        return obj

    def build_fetch_params(self):
        start_time_epoch = self.get_state()['last_time_epoch']+self.MOVING_WINDOW_DELTA
        end_time_epoch = get_current_timestamp() - self.collection_config['END_TIME_EPOCH_OFFSET_SECONDS']
        start_time_date = convert_epoch_to_utc_date(start_time_epoch, date_format=self.isoformat)
        end_time_date = convert_epoch_to_utc_date(end_time_epoch, date_format=self.isoformat)
        return f'''{self.api_config['BASE_URL']}/groups/{self.api_config['PROJECT_ID']}/processes/{self.process_id}/databases/{self.database_name}/measurements''', {
            "auth": self.digestauth,
            "params": {"itemsPerPage": self.api_config['PAGINATION_LIMIT'], "granularity": "PT1M",
                       "start": start_time_date, "end": end_time_date
                        # ,  "m": self.api_config["METRIC_TYPES"]["DATABASE_METRICS"]
            }
        }

    def build_send_params(self):
        return {
            "extra_headers": {'Content-Type': 'application/vnd.sumologic.carbon2'},
            "endpoint_key": "METRICS_SUMO_ENDPOINT",
            "jsondump": False
        }

    def transform_data(self, data):
        metrics = []
        last_time_epoch = self.DEFAULT_START_TIME_EPOCH
        for measurement in data['measurements']:
            for datapoints in measurement['dataPoints']:
                if datapoints['value'] is None:
                    continue
                current_timestamp = convert_utc_date_to_epoch(datapoints['timestamp'], date_format=self.date_format)
                cluster_name = data['hostId'].split("-", 1)[0].strip()
                metrics.append(f'''projectId={data['groupId']} databaseName={data['databaseName']} hostId={data['hostId']} processId={data['processId']} metric={measurement['name']}  units={measurement['units']} cluster_name={cluster_name} {datapoints['value']} {current_timestamp}''')
                last_time_epoch = max(current_timestamp, last_time_epoch)
        return metrics, {"last_time_epoch": last_time_epoch}

    def fetch(self):
        self.log.info(f'''getting process_id: {self.process_id} database_name: {self.database_name} project_id: {self.api_config['PROJECT_ID']}''')
        output_handler = OutputHandlerFactory.get_handler(self.collection_config['OUTPUT_HANDLER'], path=self.pathname, config=self.config)
        url, kwargs = self.build_fetch_params()
        try:
            fetch_success, content = ClientMixin.make_request(url, method="get", TIMEOUT=60, **kwargs)
            if fetch_success and len(content) > 0:
                payload, state = self.transform_data(content)
                send_success = output_handler.send(payload, **self.build_send_params())
                if send_success:
                    self.save_state(**state)
                    self.log.info(f'''Successfully sent process_id: {self.process_id} database_name: {self.database_name} project_id: {self.api_config['PROJECT_ID']} Data: {len(content)}''')
                else:
                    self.log.error(f'''Failed to sent process_id: {self.process_id} database_name: {self.database_name} project_id: {self.api_config['PROJECT_ID']}''')
            else:
                self.log.info(f'''No results status: {fetch_success} reason: {content}''')
        finally:
            output_handler.close()


class ProjectEventsAPI(BaseAPI):

    pathname = "projectevents.json"

    def __init__(self, kvstore, config):
        super(ProjectEventsAPI, self).__init__(kvstore, config)

    def _get_key(self):
        key = f'''{self.api_config['PROJECT_ID']}-projectevents'''
        return key

    def save_state(self, state):
        key = self._get_key()
        self.kvstore.set(key, state)

    def get_state(self):
        key = self._get_key()
        if not self.kvstore.has_key(key):
            self.save_state({"last_time_epoch": self.DEFAULT_START_TIME_EPOCH, "page_num": 0})
        obj = self.kvstore.get(key)
        return obj

    def build_fetch_params(self):
        state = self.get_state()
        if state["page_num"] == 0:
            start_time_epoch = state['last_time_epoch'] + self.MOVING_WINDOW_DELTA
            end_time_epoch = get_current_timestamp() - self.collection_config['END_TIME_EPOCH_OFFSET_SECONDS']
            page_num = 1
        else:
            start_time_epoch = state['start_time_epoch']
            end_time_epoch = state['end_time_epoch']
            page_num = state['pageNum']

        start_time_date = convert_epoch_to_utc_date(start_time_epoch, date_format=self.isoformat)
        end_time_date = convert_epoch_to_utc_date(end_time_epoch, date_format=self.isoformat)
        return f'''{self.api_config['BASE_URL']}/groups/{self.api_config['PROJECT_ID']}/events''', {
            "auth": self.digestauth,
            "params": {"itemsPerPage": self.api_config['PAGINATION_LIMIT'], "minDate": start_time_date , "maxDate": end_time_date, "pageNum": page_num}
        }

    def build_send_params(self):
        return {
            "extra_headers": {'X-Sumo-Name': "events"},
            "endpoint_key": "LOGS_SUMO_ENDPOINT"
        }

    def transform_data(self, data):

        # assuming file content is small so inmemory possible
        # https://stackoverflow.com/questions/11914472/stringio-in-python3
        # https://stackoverflow.com/questions/8858414/using-python-how-do-you-untar-purely-in-memory
        last_time_epoch = self.DEFAULT_START_TIME_EPOCH
        event_logs = []
        for obj in data['results']:
            current_timestamp = convert_date_to_epoch(obj['created'])
            last_time_epoch = max(current_timestamp, last_time_epoch)
            event_logs.append(obj)

        return event_logs, {"last_time_epoch": last_time_epoch}

    def fetch(self):
        current_state = self.get_state()
        output_handler = OutputHandlerFactory.get_handler(self.collection_config['OUTPUT_HANDLER'], path=self.pathname, config=self.config)
        url, kwargs = self.build_fetch_params()
        next_request = True
        sess = ClientMixin.get_new_session()
        count = 0
        try:
            while next_request:
                send_success = has_next_page = False
                status, data = ClientMixin.make_request(url, method="get", session=sess, TIMEOUT=60, **kwargs)
                fetch_success = status and "results" in data
                if fetch_success:
                    has_next_page = len(data['results']) > 0
                    if has_next_page:
                        payload, updated_state = self.transform_data(data)
                        send_success = output_handler.send(payload, **self.build_send_params())
                        if send_success:
                            count += 1
                            self.log.info(f'''Fetching Project: {self.api_config['PROJECT_ID']} Events Page: {kwargs['params']['pageNum']}  Datalen: {len(payload)} starttime: {kwargs['params']['minDate']} endtime: {kwargs['params']['maxDate']}''')
                            kwargs['params']['pageNum'] += 1
                            # save and update last_time_epoch required for next invocation
                            current_state.update(updated_state)
                            # time not available save current state new page num else continue
                            if not self.is_time_remaining():
                                self.save_state({
                                    "start_time_epoch": convert_utc_date_to_epoch(kwargs['params']['minDate']),
                                    "end_time_epoch": convert_utc_date_to_epoch(kwargs['params']['maxDate']),
                                    "page_num": kwargs['params']["pageNum"],
                                    "last_time_epoch": current_state['last_time_epoch']
                                })
                        else:
                            # show err unable to send save current state
                            self.log.error(f'''Unable to send Project: {self.api_config['PROJECT_ID']} Events Page: {kwargs['params']['pageNum']} starttime: {kwargs['params']['minDate']} endtime: {kwargs['params']['maxDate']}''')
                            self.save_state({
                                "start_time_epoch": convert_utc_date_to_epoch(kwargs['params']['minDate']),
                                "end_time_epoch": convert_utc_date_to_epoch(kwargs['params']['maxDate']),
                                "page_num": kwargs['params']["pageNum"],
                                "last_time_epoch": current_state['last_time_epoch']
                            })
                    else:
                        self.log.info(f'''Moving starttime window Project: {self.api_config['PROJECT_ID']} Events Page: {kwargs['params']['pageNum']} starttime: {kwargs['params']['minDate']} endtime: {kwargs['params']['maxDate']}''')
                        # here send success is false
                        # genuine no result window no change
                        # page_num has finished increase window calc last_time_epoch  and add 1
                        if kwargs['params']['pageNum'] > 1:
                            self.save_state({
                                "page_num": 0,
                                "last_time_epoch": current_state['last_time_epoch'] + self.MOVING_WINDOW_DELTA
                            })
                else:
                    self.log.error(f'''Unable to fetch Project: {self.api_config['PROJECT_ID']} Events Page: {kwargs['params']['pageNum']} Reason: {data} starttime: {kwargs['params']['minDate']} endtime: {kwargs['params']['maxDate']}''')
                next_request = fetch_success and send_success and has_next_page and self.is_time_remaining()
        finally:
            # should include save here for ctrl-C case when has_next_page=True
            sess.close()
            self.log.info(f'''Completed Project: {self.api_config['PROJECT_ID']} Count: {count} Events Page: {kwargs['params']['pageNum']} starttime: {kwargs['params']['minDate']} endtime: {kwargs['params']['maxDate']}''')


class OrgEventsAPI(BaseAPI):
    pathname = "orgevents.json"

    def __init__(self, kvstore, config):
        super(OrgEventsAPI, self).__init__(kvstore, config)


    def _get_key(self):
        key = f'''{self.api_config['ORGANIZATION_ID']}-orgevents'''
        return key


    def save_state(self, state):
        key = self._get_key()
        self.kvstore.set(key, state)


    def get_state(self):
        key = self._get_key()
        if not self.kvstore.has_key(key):
            self.save_state({"last_time_epoch": self.DEFAULT_START_TIME_EPOCH, "page_num": 0})
        obj = self.kvstore.get(key)
        return obj


    def build_fetch_params(self):
        state = self.get_state()
        if state["page_num"] == 0:
            start_time_epoch = state['last_time_epoch'] + self.MOVING_WINDOW_DELTA
            end_time_epoch = get_current_timestamp() - self.collection_config['END_TIME_EPOCH_OFFSET_SECONDS']
            page_num = 1
        else:
            start_time_epoch = state['start_time_epoch']
            end_time_epoch = state['end_time_epoch']
            page_num = state['pageNum']

        start_time_date = convert_epoch_to_utc_date(start_time_epoch, date_format=self.isoformat)
        end_time_date = convert_epoch_to_utc_date(end_time_epoch, date_format=self.isoformat)
        return f'''{self.api_config['BASE_URL']}/orgs/{self.api_config['ORGANIZATION_ID']}/events''', {
            "auth": self.digestauth,
            "params": {"itemsPerPage": self.api_config['PAGINATION_LIMIT'], "minDate": start_time_date , "maxDate": end_time_date, "pageNum": page_num}
        }

    def build_send_params(self):
        return {
            "extra_headers": {'X-Sumo-Name': "orgevents"},
            "endpoint_key": "LOGS_SUMO_ENDPOINT"
        }

    def transform_data(self, data):

        # assuming file content is small so inmemory possible
        # https://stackoverflow.com/questions/11914472/stringio-in-python3
        # https://stackoverflow.com/questions/8858414/using-python-how-do-you-untar-purely-in-memory
        last_time_epoch = self.DEFAULT_START_TIME_EPOCH
        event_logs = []
        for obj in data['results']:
            current_timestamp = convert_date_to_epoch(obj['created'])
            last_time_epoch = max(current_timestamp, last_time_epoch)
            event_logs.append(obj)

        return event_logs, {"last_time_epoch": last_time_epoch}

    def fetch(self):
        current_state = self.get_state()
        output_handler = OutputHandlerFactory.get_handler(self.collection_config['OUTPUT_HANDLER'], path=self.pathname, config=self.config)
        url, kwargs = self.build_fetch_params()
        next_request = True
        count = 0
        sess = ClientMixin.get_new_session()
        try:
            while next_request:
                send_success = has_next_page = False
                status, data = ClientMixin.make_request(url, method="get", session=sess, TIMEOUT=60, **kwargs)
                fetch_success = status and "results" in data
                if fetch_success:
                    has_next_page = len(data['results']) > 0
                    if has_next_page:
                        payload, updated_state = self.transform_data(data)
                        send_success = output_handler.send(payload, **self.build_send_params())
                        if send_success:
                            count +=1
                            self.log.info(f'''Fetching OrgId: {self.api_config['ORGANIZATION_ID']} OrgEvents Page: {kwargs['params']['pageNum']}  Datalen: {len(payload)} starttime: {kwargs['params']['minDate']} endtime: {kwargs['params']['maxDate']}''')
                            kwargs['params']['pageNum'] += 1
                            # save and update last_time_epoch required for next invocation
                            current_state.update(updated_state)
                            # time not available save current state new page num else continue
                            if not self.is_time_remaining():
                                self.save_state({
                                    "start_time_epoch": convert_utc_date_to_epoch(kwargs['params']['minDate']),
                                    "end_time_epoch": convert_utc_date_to_epoch(kwargs['params']['maxDate']),
                                    "page_num": kwargs['params']["pageNum"],
                                    "last_time_epoch": current_state['last_time_epoch']
                                })
                        else:
                            # show err unable to send save current state
                            self.log.error(f'''Unable to send OrgId: {self.api_config['ORGANIZATION_ID']} OrgEvents Page: {kwargs['params']['pageNum']} starttime: {kwargs['params']['minDate']} endtime: {kwargs['params']['maxDate']}''')
                            self.save_state({
                                "start_time_epoch": convert_utc_date_to_epoch(kwargs['params']['minDate']),
                                "end_time_epoch": convert_utc_date_to_epoch(kwargs['params']['maxDate']),
                                "page_num": kwargs['params']["pageNum"],
                                "last_time_epoch": current_state['last_time_epoch']
                            })
                    else:
                        self.log.info(f'''Moving starttime window OrgId: {self.api_config['ORGANIZATION_ID']} OrgEvents Page: {kwargs['params']['pageNum']} starttime: {kwargs['params']['minDate']} endtime: {kwargs['params']['maxDate']}''')
                        # here send success is false
                        # genuine no result window no change
                        # page_num has finished increase window calc last_time_epoch  and add 1
                        if kwargs['params']['pageNum'] > 1:
                            self.save_state({
                                "page_num": 0,
                                "last_time_epoch": current_state['last_time_epoch'] + self.MOVING_WINDOW_DELTA
                            })
                else:
                    self.log.error(f'''Unable to fetch OrgId: {self.api_config['ORGANIZATION_ID']} OrgEvents Page: {kwargs['params']['pageNum']} Reason: {data} starttime: {kwargs['params']['minDate']} endtime: {kwargs['params']['maxDate']}''')
                next_request = fetch_success and send_success and has_next_page and self.is_time_remaining()
        finally:
            sess.close()
            self.log.info(f'''Completed OrgId: {self.api_config['ORGANIZATION_ID']} Count: {count} Events Page: {kwargs['params']['pageNum']} starttime: {kwargs['params']['minDate']} endtime: {kwargs['params']['maxDate']}''')


class AlertsAPI(BaseAPI):
    # In Alerts API assumption is that no new new alerts will be inserted in previous pages

    pathname = "alerts.json"

    def __init__(self, kvstore, config):
        super(AlertsAPI, self).__init__(kvstore, config)


    def _get_key(self):
        key = f'''{self.api_config['PROJECT_ID']}-alerts'''
        return key

    def save_state(self, state):
        key = self._get_key()
        self.kvstore.set(key, state)


    def get_state(self):
        key = self._get_key()
        if not self.kvstore.has_key(key):
            self.save_state({"page_num": 0, "last_page_offset": 0})
        obj = self.kvstore.get(key)
        return obj

    def build_fetch_params(self):
        state = self.get_state()
        if state["page_num"] == 0:
            page_num = 1
        else:
            page_num = state['page_num']

        return f'''{self.api_config['BASE_URL']}/groups/{self.api_config['PROJECT_ID']}/alerts''', {
            "auth": self.digestauth,
            "params": {"itemsPerPage": self.api_config['PAGINATION_LIMIT'], "pageNum": page_num}
        }

    def build_send_params(self):
        return {
            "extra_headers": {'X-Sumo-Name': "alerts"},
            "endpoint_key": "LOGS_SUMO_ENDPOINT"
        }

    def transform_data(self, data):

        # assuming file content is small so inmemory possible
        # https://stackoverflow.com/questions/11914472/stringio-in-python3
        # https://stackoverflow.com/questions/8858414/using-python-how-do-you-untar-purely-in-memory

        event_logs = []
        for obj in data['results']:
            event_logs.append(obj)

        return event_logs, {"last_page_offset": len(data["results"]) % self.api_config['PAGINATION_LIMIT']}

    def fetch(self):
        current_state = self.get_state()
        output_handler = OutputHandlerFactory.get_handler(self.collection_config['OUTPUT_HANDLER'], path=self.pathname, config=self.config)
        url, kwargs = self.build_fetch_params()
        next_request = True
        sess = ClientMixin.get_new_session()
        count = 0
        try:
            while next_request:
                send_success = has_next_page = False
                status, data = ClientMixin.make_request(url, method="get", session=sess, TIMEOUT=60, **kwargs)
                fetch_success = status and "results" in data
                if fetch_success:
                    has_next_page = len(data['results']) > 0
                    if has_next_page:
                        payload, updated_state = self.transform_data(data)
                        send_success = output_handler.send(payload, **self.build_send_params())
                        if send_success:
                            count += 1
                            self.log.info(f'''Fetching Project: {self.api_config['PROJECT_ID']} Alerts Page: {kwargs['params']['pageNum']}  Datalen: {len(payload)} ''')
                            current_state.update(updated_state)
                            if current_state['last_page_offset'] == 0:
                                # do not increase if num alerts < page limit
                                kwargs['params']['pageNum'] += 1
                            else:
                                has_next_page = False
                            # time not available save current state new page num else continue
                            if (not self.is_time_remaining()) or (not has_next_page):
                                self.save_state({
                                    "page_num": kwargs['params']["pageNum"],
                                    "last_page_offset": current_state['last_page_offset']
                                })
                        else:
                            # show err unable to send save current state
                            self.log.error(f'''Unable to send Project: {self.api_config['PROJECT_ID']} Alerts Page: {kwargs['params']['pageNum']} ''')
                            self.save_state({
                                "page_num": kwargs['params']["pageNum"],
                                "last_page_offset": current_state['last_page_offset']
                            })
                    else:
                        self.log.info(f'''Moving starttime window Project: {self.api_config['PROJECT_ID']} Alerts Page: {kwargs['params']['pageNum']} ''')
                        # here send success is false
                        # genuine no result window no change
                        # page_num has finished increase window calc last_time_epoch  and add 1
                        self.save_state({
                            "page_num": kwargs['params']["pageNum"],
                            "last_page_offset": current_state['last_page_offset']
                        })
                else:
                    self.log.error(f'''Unable to fetch Project: {self.api_config['PROJECT_ID']} Alerts Page: {kwargs['params']['pageNum']} Reason: {data} ''')
                next_request = fetch_success and send_success and has_next_page and self.is_time_remaining()
        finally:
            sess.close()
            self.log.info(f'''Completed Project: {self.api_config['PROJECT_ID']} Count: {count} Events Page: {kwargs['params']['pageNum']}''')

