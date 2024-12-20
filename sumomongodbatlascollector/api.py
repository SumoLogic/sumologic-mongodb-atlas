import gzip
import json
import os
from io import BytesIO
import time
from requests.auth import HTTPDigestAuth
from sumoappclient.sumoclient.base import BaseAPI
from sumoappclient.sumoclient.factory import OutputHandlerFactory
from sumoappclient.common.utils import (
    get_current_timestamp,
    convert_epoch_to_utc_date,
    convert_utc_date_to_epoch,
    convert_date_to_epoch,
)
from sumoappclient.sumoclient.httputils import ClientMixin
from time_and_memory_tracker import TimeAndMemoryTracker


class MongoDBAPI(BaseAPI):
    MOVING_WINDOW_DELTA = 0.001
    isoformat = "%Y-%m-%dT%H:%M:%S.%fZ"
    date_format = "%Y-%m-%dT%H:%M:%SZ"

    def __init__(self, kvstore, config):
        super(MongoDBAPI, self).__init__(kvstore, config)
        self.api_config = self.config["MongoDBAtlas"]
        self.MAX_REQUEST_WINDOW_LENGTH = self.api_config.get("Collection", {}).get(
            "MAX_REQUEST_WINDOW_LENGTH", 3600
        )
        self.MIN_REQUEST_WINDOW_LENGTH = self.api_config.get("Collection", {}).get(
            "MIN_REQUEST_WINDOW_LENGTH", 60
        )
        self.digestauth = HTTPDigestAuth(
            username=self.api_config["PUBLIC_API_KEY"],
            password=self.api_config["PRIVATE_API_KEY"],
        )
        activate_time_and_memory_tracker = self.collection_config.get(
            "ACTIVATE_TIME_AND_MEMORY_TRACKER", False
        ) or os.environ.get("ACTIVATE_TIME_AND_MEMORY_TRACKER", False)

    def get_window(self, last_time_epoch):
        start_time_epoch = last_time_epoch + self.MOVING_WINDOW_DELTA
        end_time_epoch = (get_current_timestamp() - self.collection_config["END_TIME_EPOCH_OFFSET_SECONDS"])

        while not (end_time_epoch - start_time_epoch > self.MIN_REQUEST_WINDOW_LENGTH):
            # initially last_time_epoch is same as current_time_stamp so endtime becomes lesser than starttime
            time.sleep(self.MIN_REQUEST_WINDOW_LENGTH)
            end_time_epoch = (get_current_timestamp() - self.collection_config["END_TIME_EPOCH_OFFSET_SECONDS"])

        if (end_time_epoch - start_time_epoch) > self.MAX_REQUEST_WINDOW_LENGTH:
            end_time_epoch = start_time_epoch + self.MAX_REQUEST_WINDOW_LENGTH

        return start_time_epoch, end_time_epoch

    def _get_cluster_name(self, full_name_with_cluster):
        return full_name_with_cluster.split("-shard")[0]

    def _replace_cluster_name(self, full_name_with_cluster, cluster_mapping):
        cluster_name = self._get_cluster_name(full_name_with_cluster)
        cluster_alias = cluster_mapping.get(cluster_name, cluster_name)
        return full_name_with_cluster.replace(cluster_name, cluster_alias)


class FetchMixin(MongoDBAPI):
    def fetch(self):
        log_type = self.get_key()
        with TimeAndMemoryTracker(activate=self.collection_config.get("ACTIVATE_TIME_AND_MEMORY_TRACKING", False)) as tracker:
            output_handler = OutputHandlerFactory.get_handler(
                self.collection_config["OUTPUT_HANDLER"],
                path=self.pathname,
                config=self.config,
            )
            start_message = tracker.start("self.build_fetch_params")
            url, kwargs = self.build_fetch_params()
            end_message = tracker.end("self.build_fetch_params")
            self.log.info(f'''Fetching LogType: {log_type} kwargs: {kwargs} url: {url} {start_message} {end_message}''')
            state = None
            payload = []
            try:
                start_message = tracker.start("ClientMixin.make_request")
                fetch_success, content = ClientMixin.make_request(
                    url,
                    method="get",
                    logger=self.log,
                    TIMEOUT=self.collection_config["TIMEOUT"],
                    MAX_RETRY=self.collection_config["MAX_RETRY"],
                    BACKOFF_FACTOR=self.collection_config["BACKOFF_FACTOR"],
                    **kwargs,
                )
                end_message = tracker.end("ClientMixin.make_request")
                self.log.debug(f'''Fetched LogType: {log_type} kwargs: {kwargs} url: {url} {start_message} {end_message}''')
                if fetch_success and len(content) > 0:
                    payload, state = self.transform_data(content)
                    # Todo Make this atomic if after sending -> Ctrl - C happens then it fails to save state
                    params = self.build_send_params()
                    start_message = tracker.start("OutputHandler.send")
                    send_success = output_handler.send(payload, **params)
                    end_message = tracker.end("OutputHandler.send")
                    if send_success:
                        self.save_state(**state)
                        self.log.info(f"""Successfully sent LogType: {self.get_key()} Data: {len(content)} kwargs: {kwargs} url: {url} {start_message} {end_message}""")
                    else:
                        self.log.error(f"""Failed to send LogType: {self.get_key()} Data: {len(content)} kwargs: {kwargs} url: {url} {start_message} {end_message}""")
                elif fetch_success and len(content) == 0:
                    self.log.info(
                        f"""No results window LogType: {log_type} status: {fetch_success} kwargs: {kwargs} url: {url}"""
                    )
                    is_move_fetch_window, new_state = self.check_move_fetch_window(kwargs)
                    if is_move_fetch_window:
                        self.save_state(**new_state)
                        self.log.debug(f"""Moving fetched window newstate: {new_state}""")
                else:
                    self.log.error(
                        f"""Error LogType: {log_type} status: {fetch_success} reason: {content} kwargs: {kwargs} url: {url}"""
                    )
            finally:
                output_handler.close()
                self.log.info(
                    f"""Completed LogType: {log_type} curstate: {state} datasent: {len(payload)}"""
                )


class PaginatedFetchMixin(MongoDBAPI):
    def fetch(self):
        current_state = self.get_state()
        with TimeAndMemoryTracker(activate=self.collection_config.get("ACTIVATE_TIME_AND_MEMORY_TRACKING", False)) as tracker:
            output_handler = OutputHandlerFactory.get_handler(self.collection_config["OUTPUT_HANDLER"], path=self.pathname, config=self.config)
            start_message = tracker.start("self.build_fetch_params")
            url, kwargs = self.build_fetch_params()
            end_message = tracker.end("self.build_fetch_params")
            log_type = self.get_key()
            self.log.info(f'''Fetching LogType: {log_type} kwargs: {kwargs} url: {url} {start_message} {end_message} ''')
            next_request = True
            count = 0
            sess = ClientMixin.get_new_session()
            try:
                while next_request:
                    send_success = has_next_page = False
                    start_message = tracker.start("ClientMixin.make_request")
                    status, data = ClientMixin.make_request(
                        url,
                        method="get",
                        session=sess,
                        logger=self.log,
                        TIMEOUT=self.collection_config["TIMEOUT"],
                        MAX_RETRY=self.collection_config["MAX_RETRY"],
                        BACKOFF_FACTOR=self.collection_config["BACKOFF_FACTOR"],
                        **kwargs,
                    )
                    end_message = tracker.end("ClientMixin.make_request")
                    fetch_success = status and "results" in data
                    if (count < 4) or (count % 5 == 0):
                        self.log.info(f'''Fetched LogType: {log_type} kwargs: {kwargs} url: {url} {start_message} {end_message}''')
                    if fetch_success:
                        has_next_page = len(data["results"]) > 0
                        if has_next_page:
                            payload, updated_state = self.transform_data(data)
                            params = self.build_send_params()
                            start_message = tracker.start("OutputHandler.send")
                            send_success = output_handler.send(payload, **params)
                            end_message = tracker.end("OutputHandler.send")
                            if send_success:
                                count += 1
                                if (count < 4) or (count % 5 == 0):
                                    self.log.info(
                                        f"""Successfully sent LogType: {log_type} Page: {kwargs['params']['pageNum']}  Datalen: {len(payload)} starttime: {kwargs['params']['minDate']} endtime: {kwargs['params']['maxDate']} {start_message} {end_message}"""
                                    )
                                kwargs["params"]["pageNum"] += 1
                                # save and update last_time_epoch required for next invocation
                                current_state.update(updated_state)
                                # time not available save current state new page num else continue
                                if not self.is_time_remaining():
                                    self.save_state(
                                        {
                                            "start_time_epoch": convert_utc_date_to_epoch(
                                                kwargs["params"]["minDate"]
                                            ),
                                            "end_time_epoch": convert_utc_date_to_epoch(
                                                kwargs["params"]["maxDate"]
                                            ),
                                            "page_num": kwargs["params"]["pageNum"],
                                            "last_time_epoch": current_state[
                                                "last_time_epoch"
                                            ],
                                        }
                                    )
                            else:
                                # show err unable to send save current state
                                self.log.error(
                                    f"""Failed to send LogType: {log_type} Page: {kwargs['params']['pageNum']} starttime: {kwargs['params']['minDate']} endtime: {kwargs['params']['maxDate']} {start_message} {end_message}"""
                                )
                                self.save_state(
                                    {
                                        "start_time_epoch": convert_utc_date_to_epoch(
                                            kwargs["params"]["minDate"]
                                        ),
                                        "end_time_epoch": convert_utc_date_to_epoch(
                                            kwargs["params"]["maxDate"]
                                        ),
                                        "page_num": kwargs["params"]["pageNum"],
                                        "last_time_epoch": current_state["last_time_epoch"],
                                    }
                                )
                        else:
                            # here fetch success is true and assuming pageNum starts from 1
                            # page_num has finished increase window calc last_time_epoch
                            if kwargs["params"]["pageNum"] > 1:
                                self.log.debug(
                                    f"""Moving starttime window LogType: {log_type} Page: {kwargs['params']['pageNum']} starttime: {kwargs['params']['minDate']} endtime: {kwargs['params']['maxDate']} to last_time_epoch": {convert_epoch_to_utc_date(current_state['last_time_epoch'], date_format=self.isoformat)}"""
                                )
                                self.save_state(
                                    {
                                        "page_num": 0,
                                        "last_time_epoch": current_state["last_time_epoch"],
                                    }
                                )
                            else:
                                # genuine no result window no change
                                self.log.info(
                                    f"""No results window LogType: {log_type} Page: {kwargs['params']['pageNum']} starttime: {kwargs['params']['minDate']} endtime: {kwargs['params']['maxDate']} status: {fetch_success}"""
                                )
                                is_move_fetch_window, updated_state = (
                                    self.check_move_fetch_window(kwargs)
                                )
                                if is_move_fetch_window:
                                    current_state.update(updated_state)
                                    self.log.debug(
                                        f"""Moving starttime window LogType: {log_type} Page: {kwargs['params']['pageNum']} starttime: {kwargs['params']['minDate']} endtime: {kwargs['params']['maxDate']} to last_time_epoch": {convert_epoch_to_utc_date(current_state['last_time_epoch'], date_format=self.isoformat)}"""
                                    )
                                    self.save_state(
                                        {
                                            "page_num": 0,
                                            "last_time_epoch": current_state[
                                                "last_time_epoch"
                                            ],
                                        }
                                    )

                    else:
                        self.save_state(
                            {
                                "start_time_epoch": convert_utc_date_to_epoch(
                                    kwargs["params"]["minDate"]
                                ),
                                "end_time_epoch": convert_utc_date_to_epoch(
                                    kwargs["params"]["maxDate"]
                                ),
                                "page_num": kwargs["params"]["pageNum"],
                                "last_time_epoch": current_state["last_time_epoch"],
                            }
                        )
                        self.log.error(
                            f"""Failed to fetch LogType: {log_type} Page: {kwargs['params']['pageNum']} Reason: {data} starttime: {kwargs['params']['minDate']} endtime: {kwargs['params']['maxDate']}"""
                        )
                    next_request = (fetch_success and send_success and has_next_page and self.is_time_remaining())
            finally:
                sess.close()
                self.log.info(
                    f"""Completed LogType: {log_type} Count: {count} Page: {kwargs['params']['pageNum']} starttime: {kwargs['params']['minDate']} endtime: {kwargs['params']['maxDate']}"""
                )


class LogAPI(FetchMixin):
    # single API
    MOVING_WINDOW_DELTA = 1  # This api does not take ms

    def __init__(self, kvstore, hostname, filename, config, cluster_mapping):
        super(LogAPI, self).__init__(kvstore, config)
        self.hostname = hostname
        self.filename = filename
        self.pathname = (
            "db_logs.json" if "audit" not in self.filename else "db_auditlogs.json"
        )
        self.cluster_mapping = cluster_mapping

    def get_key(self):
        key = f"""{self.api_config['PROJECT_ID']}-{self.hostname}-{self.filename}"""
        return key

    def save_state(self, last_time_epoch):
        key = self.get_key()
        obj = {"last_time_epoch": last_time_epoch}
        self.kvstore.set(key, obj)

    def get_state(self):
        key = self.get_key()
        if not self.kvstore.has_key(key):
            self.save_state(self.DEFAULT_START_TIME_EPOCH)
        obj = self.kvstore.get(key)
        return obj

    # API Ref: https://www.mongodb.com/docs/atlas/reference/api-resources-spec/v1/#tag/Monitoring-and-Logs/operation/downloadHostLogs
    def build_fetch_params(self):
        start_time_epoch, end_time_epoch = self.get_window(
            self.get_state()["last_time_epoch"]
        )

        return (
            f"""{self.api_config['BASE_URL']}/groups/{self.api_config['PROJECT_ID']}/clusters/{self.hostname}/logs/{self.filename}""",
            {
                "auth": self.digestauth,
                "params": {
                    "startDate": int(start_time_epoch),
                    "endDate": int(end_time_epoch),
                },  # this api does not take ms
                "headers": {"Accept": "application/gzip"},
                "is_file": True,
            },
        )

    def build_send_params(self):
        return {
            "extra_headers": {"X-Sumo-Name": self.filename},
            "endpoint_key": "HTTP_LOGS_ENDPOINT",
        }

    def check_move_fetch_window(self, kwargs):
        # https://www.mongodb.com/docs/atlas/reference/api/logs/
        # Process and audit logs are updated from the cluster backend infrastructure every five minutes and contain log data from the previous five minutes.
        data_availablity_max_endDate = int(get_current_timestamp() - 5 * 60)
        api_endDate = kwargs["params"]["endDate"]
        if api_endDate < data_availablity_max_endDate:
            return True, {"last_time_epoch": api_endDate}
        else:
            return False, {}

    def transform_data(self, content):
        # assuming file content is small so inmemory possible
        # https://stackoverflow.com/questions/11914472/stringio-in-python3
        # https://stackoverflow.com/questions/8858414/using-python-how-do-you-untar-purely-in-memory
        all_logs = []
        last_time_epoch = self.DEFAULT_START_TIME_EPOCH
        results = gzip.GzipFile(fileobj=BytesIO(content))
        last_line = ""
        for line_no, line in enumerate(results.readlines()):
            if not line.strip():
                # for JSONDecoderror in case of empty lines
                continue
            line = line.decode("utf-8")
            hostname_alias = self._replace_cluster_name(
                self.hostname, self.cluster_mapping
            )
            cluster_name = self._get_cluster_name(hostname_alias)

            if "audit" in self.filename:
                if last_line:
                    line = last_line + line
                try:
                    msg = json.loads(line)
                    last_line = ""
                except ValueError as e:
                    # checking for multiline messages
                    last_line = line
                    self.log.warn(
                        "Multiline Message in line no: %d last_log: %s current_log: %s"
                        % (line_no, all_logs[-1:], line)
                    )
                    continue
                msg["project_id"] = self.api_config["PROJECT_ID"]
                msg["hostname"] = hostname_alias
                msg["cluster_name"] = cluster_name
                current_date = msg["ts"]["$date"]
            else:
                if last_line:
                    line = last_line + line
                try:
                    msg = json.loads(line)
                    last_line = ""
                except ValueError as e:
                    # checking for multiline messages
                    last_line = line
                    self.log.warn(
                        "Multiline Message in line no: %d last_log: %s current_log: %s"
                        % (line_no, all_logs[-1:], line)
                    )
                    continue
                msg["project_id"] = self.api_config["PROJECT_ID"]
                msg["hostname"] = hostname_alias
                msg["cluster_name"] = cluster_name
                current_date = msg["t"]["$date"]

            current_date_timestamp = convert_date_to_epoch(current_date.strip())
            msg["created"] = current_date  # taking out date
            last_time_epoch = max(current_date_timestamp, last_time_epoch)
            all_logs.append(msg)

        return all_logs, {"last_time_epoch": last_time_epoch}


class ProcessMetricsAPI(FetchMixin):
    pathname = "process_metrics.log"

    def __init__(self, kvstore, process_id, config, cluster_mapping):
        super(ProcessMetricsAPI, self).__init__(kvstore, config)
        self.process_id = process_id
        self.cluster_mapping = cluster_mapping

    def get_key(self):
        key = f"""{self.api_config['PROJECT_ID']}-{self.process_id}-processmetrics"""
        return key

    def save_state(self, last_time_epoch):
        key = self.get_key()
        obj = {"last_time_epoch": last_time_epoch}
        self.kvstore.set(key, obj)

    def get_state(self):
        key = self.get_key()
        if not self.kvstore.has_key(key):
            self.save_state(self.DEFAULT_START_TIME_EPOCH)
        obj = self.kvstore.get(key)
        return obj

    # API Ref: https://www.mongodb.com/docs/atlas/reference/api-resources-spec/v1/#tag/Monitoring-and-Logs/operation/getHostMeasurements
    def build_fetch_params(self):
        start_time_epoch, end_time_epoch = self.get_window(
            self.get_state()["last_time_epoch"]
        )
        start_time_date = convert_epoch_to_utc_date(
            start_time_epoch, date_format=self.isoformat
        )
        end_time_date = convert_epoch_to_utc_date(
            end_time_epoch, date_format=self.isoformat
        )
        return (
            f"""{self.api_config['BASE_URL']}/groups/{self.api_config['PROJECT_ID']}/processes/{self.process_id}/measurements""",
            {
                "auth": self.digestauth,
                "params": {
                    "itemsPerPage": self.api_config["PAGINATION_LIMIT"],
                    "granularity": "PT1M",
                    "start": start_time_date,
                    "end": end_time_date,
                    "m": self.api_config["METRIC_TYPES"]["PROCESS_METRICS"],
                },
            },
        )

    def build_send_params(self):
        return {
            "extra_headers": {"Content-Type": "application/vnd.sumologic.carbon2"},
            "endpoint_key": "HTTP_METRICS_ENDPOINT",
            "jsondump": False,
        }

    def check_move_fetch_window(self, kwargs):
        # https://www.mongodb.com/docs/atlas/reference/api/process-measurements/
        # Atlas retrieves database metrics every 20 minutes by default. Results include data points with 20 minute intervals.
        data_availablity_max_endDate = get_current_timestamp() - 20 * 60
        api_endDate = convert_utc_date_to_epoch(
            kwargs["params"]["end"], date_format=self.isoformat
        )
        if api_endDate < data_availablity_max_endDate:
            return True, {"last_time_epoch": api_endDate}
        else:
            return False, {}

    def transform_data(self, data):
        metrics = []
        last_time_epoch = self.DEFAULT_START_TIME_EPOCH
        for measurement in data["measurements"]:
            for datapoints in measurement["dataPoints"]:
                if datapoints["value"] is None:
                    continue
                current_timestamp = convert_utc_date_to_epoch(
                    datapoints["timestamp"], date_format=self.date_format
                )
                host_id = self._replace_cluster_name(
                    data["hostId"], self.cluster_mapping
                )
                process_id = self._replace_cluster_name(
                    data["processId"], self.cluster_mapping
                )
                cluster_name = self._get_cluster_name(host_id)
                metrics.append(
                    f"""projectId={data['groupId']} hostId={host_id} processId={process_id} metric={measurement['name']}  units={measurement['units']} cluster_name={cluster_name} {datapoints['value']} {current_timestamp}"""
                )
                last_time_epoch = max(current_timestamp, last_time_epoch)
        return metrics, {"last_time_epoch": last_time_epoch}


class DiskMetricsAPI(FetchMixin):
    isoformat = "%Y-%m-%dT%H:%M:%S.%fZ"
    date_format = "%Y-%m-%dT%H:%M:%SZ"
    pathname = "disk_metrics.log"

    def __init__(self, kvstore, process_id, disk_name, config, cluster_mapping):
        super(DiskMetricsAPI, self).__init__(kvstore, config)
        self.process_id = process_id
        self.disk_name = disk_name
        self.cluster_mapping = cluster_mapping

    def get_key(self):
        key = f"""{self.api_config['PROJECT_ID']}-{self.process_id}-{self.disk_name}-diskmetrics"""
        return key

    def save_state(self, last_time_epoch):
        key = self.get_key()
        obj = {"last_time_epoch": last_time_epoch}
        self.kvstore.set(key, obj)

    def get_state(self):
        key = self.get_key()
        if not self.kvstore.has_key(key):
            self.save_state(self.DEFAULT_START_TIME_EPOCH)
        obj = self.kvstore.get(key)
        return obj

    # API Ref: https://www.mongodb.com/docs/atlas/reference/api-resources-spec/v1/#tag/Monitoring-and-Logs/operation/getDiskMeasurements
    def build_fetch_params(self):
        start_time_epoch, end_time_epoch = self.get_window(
            self.get_state()["last_time_epoch"]
        )
        start_time_date = convert_epoch_to_utc_date(
            start_time_epoch, date_format=self.isoformat
        )
        end_time_date = convert_epoch_to_utc_date(
            end_time_epoch, date_format=self.isoformat
        )
        return (
            f"""{self.api_config['BASE_URL']}/groups/{self.api_config['PROJECT_ID']}/processes/{self.process_id}/disks/{self.disk_name}/measurements""",
            {
                "auth": self.digestauth,
                "params": {
                    "itemsPerPage": self.api_config["PAGINATION_LIMIT"],
                    "granularity": "PT1M",
                    "start": start_time_date,
                    "end": end_time_date,
                    "m": self.api_config["METRIC_TYPES"]["DISK_METRICS"],
                },
            },
        )

    def build_send_params(self):
        return {
            "extra_headers": {"Content-Type": "application/vnd.sumologic.carbon2"},
            "endpoint_key": "HTTP_METRICS_ENDPOINT",
            "jsondump": False,
        }

    def check_move_fetch_window(self, kwargs):
        # hhttps://www.mongodb.com/docs/atlas/reference/api/process-disks-measurements/
        # Atlas retrieves database metrics every 20 minutes by default. Results include data points with 20 minute intervals.
        data_availablity_max_endDate = get_current_timestamp() - 20 * 60
        api_endDate = convert_utc_date_to_epoch(
            kwargs["params"]["end"], date_format=self.isoformat
        )
        if api_endDate < data_availablity_max_endDate:
            return True, {"last_time_epoch": api_endDate}
        else:
            return False, {}

    def transform_data(self, data):
        metrics = []
        last_time_epoch = self.DEFAULT_START_TIME_EPOCH
        for measurement in data["measurements"]:
            for datapoints in measurement["dataPoints"]:
                if datapoints["value"] is None:
                    continue
                current_timestamp = convert_utc_date_to_epoch(
                    datapoints["timestamp"], date_format=self.date_format
                )
                host_id = self._replace_cluster_name(
                    data["hostId"], self.cluster_mapping
                )
                process_id = self._replace_cluster_name(
                    data["processId"], self.cluster_mapping
                )
                cluster_name = self._get_cluster_name(host_id)
                metrics.append(
                    f"""projectId={data['groupId']} partitionName={data['partitionName']} hostId={host_id} processId={process_id} metric={measurement['name']}  units={measurement['units']} cluster_name={cluster_name} {datapoints['value']} {current_timestamp}"""
                )
                last_time_epoch = max(current_timestamp, last_time_epoch)
        return metrics, {"last_time_epoch": last_time_epoch}


class DatabaseMetricsAPI(FetchMixin):
    isoformat = "%Y-%m-%dT%H:%M:%S.%fZ"
    date_format = "%Y-%m-%dT%H:%M:%SZ"
    pathname = "database_metrics.log"

    def __init__(self, kvstore, process_id, database_name, config, cluster_mapping):
        super(DatabaseMetricsAPI, self).__init__(kvstore, config)
        self.process_id = process_id
        self.database_name = database_name
        self.cluster_mapping = cluster_mapping

    def get_key(self):
        key = f"""{self.api_config['PROJECT_ID']}-{self.process_id}-{self.database_name}-dbmetrics"""
        return key

    def save_state(self, last_time_epoch):
        key = self.get_key()
        obj = {"last_time_epoch": last_time_epoch}
        self.kvstore.set(key, obj)

    def get_state(self):
        key = self.get_key()
        if not self.kvstore.has_key(key):
            self.save_state(self.DEFAULT_START_TIME_EPOCH)
        obj = self.kvstore.get(key)
        return obj

    # API Ref: https://www.mongodb.com/docs/atlas/reference/api-resources-spec/v1/#tag/Monitoring-and-Logs/operation/getDatabaseMeasurements
    def build_fetch_params(self):
        start_time_epoch, end_time_epoch = self.get_window(
            self.get_state()["last_time_epoch"]
        )
        start_time_date = convert_epoch_to_utc_date(
            start_time_epoch, date_format=self.isoformat
        )
        end_time_date = convert_epoch_to_utc_date(
            end_time_epoch, date_format=self.isoformat
        )
        return (
            f"""{self.api_config['BASE_URL']}/groups/{self.api_config['PROJECT_ID']}/processes/{self.process_id}/databases/{self.database_name}/measurements""",
            {
                "auth": self.digestauth,
                "params": {
                    "itemsPerPage": self.api_config["PAGINATION_LIMIT"],
                    "granularity": "PT1M",
                    "start": start_time_date,
                    "end": end_time_date,
                    "m": self.api_config["METRIC_TYPES"]["DATABASE_METRICS"],
                },
            },
        )

    def build_send_params(self):
        return {
            "extra_headers": {"Content-Type": "application/vnd.sumologic.carbon2"},
            "endpoint_key": "HTTP_METRICS_ENDPOINT",
            "jsondump": False,
        }

    def check_move_fetch_window(self, kwargs):
        # https://www.mongodb.com/docs/atlas/reference/api/process-databases-measurements/
        # Atlas retrieves database metrics every 20 minutes by default. Results include data points with 20 minute intervals.
        data_availablity_max_endDate = get_current_timestamp() - 20 * 60
        api_endDate = convert_utc_date_to_epoch(
            kwargs["params"]["end"], date_format=self.isoformat
        )
        if api_endDate < data_availablity_max_endDate:
            return True, {"last_time_epoch": api_endDate}
        else:
            return False, {}

    def transform_data(self, data):
        metrics = []
        last_time_epoch = self.DEFAULT_START_TIME_EPOCH
        for measurement in data["measurements"]:
            for datapoints in measurement["dataPoints"]:
                if datapoints["value"] is None:
                    continue
                current_timestamp = convert_utc_date_to_epoch(
                    datapoints["timestamp"], date_format=self.date_format
                )
                process_id = self._replace_cluster_name(
                    data["processId"], self.cluster_mapping
                )
                cluster_name = self._get_cluster_name(process_id)
                metrics.append(
                    f"""projectId={data['groupId']} databaseName={data['databaseName']} hostId={data['hostId']} processId={process_id} metric={measurement['name']}  units={measurement['units']} cluster_name={cluster_name} {datapoints['value']} {current_timestamp}"""
                )
                last_time_epoch = max(current_timestamp, last_time_epoch)
        return metrics, {"last_time_epoch": last_time_epoch}


class ProjectEventsAPI(PaginatedFetchMixin):
    pathname = "projectevents.json"

    def __init__(self, kvstore, config):
        super(ProjectEventsAPI, self).__init__(kvstore, config)

    def get_key(self):
        key = f"""{self.api_config['PROJECT_ID']}-projectevents"""
        return key

    def save_state(self, state):
        key = self.get_key()
        self.kvstore.set(key, state)

    def get_state(self):
        key = self.get_key()
        if not self.kvstore.has_key(key):
            self.save_state(
                {"last_time_epoch": self.DEFAULT_START_TIME_EPOCH, "page_num": 0}
            )
        obj = self.kvstore.get(key)
        return obj

    # API Ref: https://www.mongodb.com/docs/atlas/reference/api-resources-spec/v1/#tag/Events/operation/listProjectEvents
    def build_fetch_params(self):
        state = self.get_state()
        if state["page_num"] == 0:
            start_time_epoch, end_time_epoch = self.get_window(state["last_time_epoch"])
            page_num = 1
        else:
            start_time_epoch = state["start_time_epoch"]
            end_time_epoch = state["end_time_epoch"]
            page_num = state["page_num"]

        start_time_date = convert_epoch_to_utc_date(
            start_time_epoch, date_format=self.isoformat
        )
        end_time_date = convert_epoch_to_utc_date(
            end_time_epoch, date_format=self.isoformat
        )
        return (
            f"""{self.api_config['BASE_URL']}/groups/{self.api_config['PROJECT_ID']}/events""",
            {
                "auth": self.digestauth,
                "params": {
                    "itemsPerPage": self.api_config["PAGINATION_LIMIT"],
                    "minDate": start_time_date,
                    "maxDate": end_time_date,
                    "pageNum": page_num,
                },
            },
        )

    def build_send_params(self):
        return {
            "extra_headers": {"X-Sumo-Name": "events"},
            "endpoint_key": "HTTP_LOGS_ENDPOINT",
        }

    def check_move_fetch_window(self, kwargs):
        # https://www.mongodb.com/docs/atlas/reference/api/events-projects-get-all/
        # no information given so assuming data gets retrieved in 5 min similar to database logs

        data_availablity_max_endDate = get_current_timestamp() - 5 * 60
        api_endDate = convert_utc_date_to_epoch(
            kwargs["params"]["maxDate"], date_format=self.isoformat
        )
        if api_endDate < data_availablity_max_endDate:
            return True, {"last_time_epoch": api_endDate, "page_num": 0}
        else:
            return False, {}

    def transform_data(self, data):
        # assuming file content is small so inmemory possible
        # https://stackoverflow.com/questions/11914472/stringio-in-python3
        # https://stackoverflow.com/questions/8858414/using-python-how-do-you-untar-purely-in-memory
        last_time_epoch = self.DEFAULT_START_TIME_EPOCH
        event_logs = []
        for obj in data["results"]:
            current_timestamp = convert_date_to_epoch(obj["created"])
            last_time_epoch = max(current_timestamp, last_time_epoch)
            event_logs.append(obj)

        return event_logs, {"last_time_epoch": last_time_epoch}


class OrgEventsAPI(PaginatedFetchMixin):
    pathname = "orgevents.json"

    def __init__(self, kvstore, config):
        super(OrgEventsAPI, self).__init__(kvstore, config)

    def get_key(self):
        key = f"""{self.api_config['ORGANIZATION_ID']}-orgevents"""
        return key

    def save_state(self, state):
        key = self.get_key()
        self.kvstore.set(key, state)

    def get_state(self):
        key = self.get_key()
        if not self.kvstore.has_key(key):
            self.save_state(
                {"last_time_epoch": self.DEFAULT_START_TIME_EPOCH, "page_num": 0}
            )
        obj = self.kvstore.get(key)
        return obj

    # API Ref: https://www.mongodb.com/docs/atlas/reference/api-resources-spec/v1/#tag/Events/operation/listOrganizationEvents
    def build_fetch_params(self):
        state = self.get_state()
        if state["page_num"] == 0:
            start_time_epoch, end_time_epoch = self.get_window(state["last_time_epoch"])
            page_num = 1
        else:
            start_time_epoch = state["start_time_epoch"]
            end_time_epoch = state["end_time_epoch"]
            page_num = state["page_num"]

        start_time_date = convert_epoch_to_utc_date(
            start_time_epoch, date_format=self.isoformat
        )
        end_time_date = convert_epoch_to_utc_date(
            end_time_epoch, date_format=self.isoformat
        )
        return (
            f"""{self.api_config['BASE_URL']}/orgs/{self.api_config['ORGANIZATION_ID']}/events""",
            {
                "auth": self.digestauth,
                "params": {
                    "itemsPerPage": self.api_config["PAGINATION_LIMIT"],
                    "minDate": start_time_date,
                    "maxDate": end_time_date,
                    "pageNum": page_num,
                },
            },
        )

    def build_send_params(self):
        return {
            "extra_headers": {"X-Sumo-Name": "orgevents"},
            "endpoint_key": "HTTP_LOGS_ENDPOINT",
        }

    def check_move_fetch_window(self, kwargs):
        # https://www.mongodb.com/docs/atlas/reference/api/events-projects-get-all/
        # no information given so assuming data gets retrieved in 5 min similar to database logs

        data_availablity_max_endDate = get_current_timestamp() - 5 * 60
        api_endDate = convert_utc_date_to_epoch(
            kwargs["params"]["maxDate"], date_format=self.isoformat
        )
        if api_endDate < data_availablity_max_endDate:
            return True, {"last_time_epoch": api_endDate, "page_num": 0}
        else:
            return False, {}

    def transform_data(self, data):
        # assuming file content is small so inmemory possible
        # https://stackoverflow.com/questions/11914472/stringio-in-python3
        # https://stackoverflow.com/questions/8858414/using-python-how-do-you-untar-purely-in-memory
        last_time_epoch = self.DEFAULT_START_TIME_EPOCH
        event_logs = []
        for obj in data["results"]:
            current_timestamp = convert_date_to_epoch(obj["created"])
            last_time_epoch = max(current_timestamp, last_time_epoch)
            event_logs.append(obj)

        return event_logs, {"last_time_epoch": last_time_epoch}


class AlertsAPI(MongoDBAPI):
    # In Alerts API assumption is that no new new alerts will be inserted in previous pages

    pathname = "alerts.json"

    def __init__(self, kvstore, config):
        super(AlertsAPI, self).__init__(kvstore, config)

    def get_key(self):
        key = f"""{self.api_config['PROJECT_ID']}-alerts"""
        return key

    def save_state(self, state):
        key = self.get_key()
        self.kvstore.set(key, state)

    def get_state(self):
        key = self.get_key()
        if not self.kvstore.has_key(key):
            self.save_state({"page_num": 0, "last_page_offset": 0})
        obj = self.kvstore.get(key)
        return obj

    # API Ref: https://www.mongodb.com/docs/atlas/reference/api-resources-spec/v1/#tag/Alerts/operation/listAlerts
    def build_fetch_params(self):
        state = self.get_state()
        if state["page_num"] == 0:
            page_num = 1
        else:
            page_num = state["page_num"]

        return (
            f"""{self.api_config['BASE_URL']}/groups/{self.api_config['PROJECT_ID']}/alerts""",
            {
                "auth": self.digestauth,
                "params": {
                    "itemsPerPage": self.api_config["PAGINATION_LIMIT"],
                    "pageNum": page_num,
                },
            },
        )

    def build_send_params(self):
        return {
            "extra_headers": {"X-Sumo-Name": "alerts"},
            "endpoint_key": "HTTP_LOGS_ENDPOINT",
        }

    def transform_data(self, data):
        # assuming file content is small so inmemory possible
        # https://stackoverflow.com/questions/11914472/stringio-in-python3
        # https://stackoverflow.com/questions/8858414/using-python-how-do-you-untar-purely-in-memory

        event_logs = []
        for obj in data["results"]:
            event_logs.append(obj)

        return event_logs, {
            "last_page_offset": len(data["results"])
            % self.api_config["PAGINATION_LIMIT"]
        }

    def fetch(self):
        current_state = self.get_state()
        output_handler = OutputHandlerFactory.get_handler(
            self.collection_config["OUTPUT_HANDLER"],
            path=self.pathname,
            config=self.config,
        )
        url, kwargs = self.build_fetch_params()
        next_request = True
        sess = ClientMixin.get_new_session()
        log_type = self.get_key()
        count = 0
        self.log.info(
            f"""Fetching LogType: {log_type} pageNum: {kwargs["params"]["pageNum"]}"""
        )
        try:
            while next_request:
                send_success = has_next_page = False
                status, data = ClientMixin.make_request(
                    url,
                    method="get",
                    session=sess,
                    logger=self.log,
                    TIMEOUT=self.collection_config["TIMEOUT"],
                    MAX_RETRY=self.collection_config["MAX_RETRY"],
                    BACKOFF_FACTOR=self.collection_config["BACKOFF_FACTOR"],
                    **kwargs,
                )
                if count < 4 or (count % 5 == 0):
                    self.log.info(f'''Fetched LogType: {log_type} kwargs: {kwargs} url: {url}''')
                fetch_success = status and "results" in data
                if fetch_success:
                    has_next_page = len(data["results"]) > 0
                    if has_next_page:
                        payload, updated_state = self.transform_data(data)
                        send_success = output_handler.send(
                            payload, **self.build_send_params()
                        )
                        if send_success:
                            count += 1
                            if count < 4 or (count % 5 == 0):
                                self.log.info(
                                    f"""Successfully sent LogType: {log_type} Project: {self.api_config['PROJECT_ID']} Alerts Page: {kwargs['params']['pageNum']}  Datalen: {len(payload)} """
                                )
                            current_state.update(updated_state)
                            if current_state["last_page_offset"] == 0:
                                # do not increase if num alerts < page limit
                                kwargs["params"]["pageNum"] += 1
                            else:
                                has_next_page = False
                            # time not available save current state new page num else continue
                            if (not self.is_time_remaining()) or (not has_next_page):
                                self.save_state(
                                    {
                                        "page_num": kwargs["params"]["pageNum"],
                                        "last_page_offset": current_state[
                                            "last_page_offset"
                                        ],
                                    }
                                )
                        else:
                            # show err unable to send save current state
                            self.log.error(
                                f"""Unable to send Project: {self.api_config['PROJECT_ID']} Alerts Page: {kwargs['params']['pageNum']} """
                            )
                            self.save_state(
                                {
                                    "page_num": kwargs["params"]["pageNum"],
                                    "last_page_offset": current_state[
                                        "last_page_offset"
                                    ],
                                }
                            )
                    else:
                        self.log.debug(
                            f"""Moving starttime window Project: {self.api_config['PROJECT_ID']} Alerts Page: {kwargs['params']['pageNum']} """
                        )
                        # here send success is false
                        # genuine no result window no change
                        # page_num has finished increase window calc last_time_epoch  and add 1
                        self.save_state(
                            {
                                "page_num": kwargs["params"]["pageNum"],
                                "last_page_offset": current_state["last_page_offset"],
                            }
                        )
                else:
                    self.log.error(
                        f"""Unable to fetch Project: {self.api_config['PROJECT_ID']} Alerts Page: {kwargs['params']['pageNum']} Reason: {data} """
                    )
                next_request = (fetch_success and send_success and has_next_page and self.is_time_remaining())
        finally:
            sess.close()
            self.log.info(
                f"""Completed LogType: {log_type} Count: {count} Page: {kwargs['params']['pageNum']}"""
            )
