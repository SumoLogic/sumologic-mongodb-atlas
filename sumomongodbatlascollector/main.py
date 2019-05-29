# -*- coding: future_fstrings -*-
import traceback
import sys
import time
import os
import datetime
from concurrent import futures
from common.logger import get_logger
from omnistorage.factory import ProviderFactory
from sumoclient.factory import OutputHandlerFactory
from sumoclient.utils import get_current_timestamp, convert_epoch_to_utc_date, convert_utc_date_to_epoch
from common.config import Config
from oauth2client.service_account import ServiceAccountCredentials
from googleapiclient.discovery import build


class MongoDBAtlasCollector(object):

    CONFIG_FILENAME = "mongodbatlas.yaml"
    STOP_TIME_OFFSET_SECONDS = 10
    DATE_FORMAT = '%Y-%m-%dT%H:%M:%S.%fZ'
    MOVING_WINDOW_DELTA = 0.001
    FUNCTION_TIMEOUT = 5*60

    def __init__(self):
        self.start_time = datetime.datetime.utcnow()
        cfgpath = sys.argv[1] if len(sys.argv) > 1 else ''
        self.root_dir = self.get_current_dir()
        self.config = Config().get_config(self.CONFIG_FILENAME, self.root_dir, cfgpath)
        self.log = get_logger(__name__, force_create=True, **self.config['Logging'])
        self.collection_config = self.config['Collection']
        self.api_config = self.config['MongoDBAtlas']
        op_cli = ProviderFactory.get_provider(self.config['Collection']['ENVIRONMENT'])
        self.kvstore = op_cli.get_storage("keyvalue", name=self.config['Collection']['DBNAME'])
        self.DEFAULT_START_TIME_EPOCH = get_current_timestamp() - self.collection_config['BACKFILL_DAYS']*24*60*60
        self.alertcli = self.get_alert_client()

    def get_current_dir(self):
        cur_dir = os.path.dirname(__file__)
        return cur_dir

    def set_fetch_state(self, alert_type, start_time_epoch, end_time_epoch, pageToken=None):
        if end_time_epoch:  # end time epoch could be none in cases where no event is present
            assert start_time_epoch <= end_time_epoch
        obj = {
            "pageToken": pageToken,
            "alert_type": alert_type,
            "start_time_epoch": start_time_epoch,
            "end_time_epoch": end_time_epoch
        }

        self.kvstore.set(alert_type, obj)
        return obj

    def build_params(self, alert_type, start_time_epoch, end_time_epoch, pageToken, page_size):
        params = {
            'pageSize': page_size,
            'pageToken': pageToken,
            'filter': f'''create_time >= \"{convert_epoch_to_utc_date(start_time_epoch, self.DATE_FORMAT)}\" AND create_time <= \"{convert_epoch_to_utc_date(end_time_epoch, self.DATE_FORMAT)}\" AND type = \"{alert_type}\"''',
            'orderBy': "create_time desc"
        }
        return params

    def set_new_end_epoch_time(self, alert_type, start_time_epoch):
        end_time_epoch = get_current_timestamp() - self.collection_config['END_TIME_EPOCH_OFFSET_SECONDS']
        params = self.build_params(alert_type, start_time_epoch, end_time_epoch, None, 1)
        response = self.alertcli.alerts().list(**params).execute()
        start_date = convert_epoch_to_utc_date(start_time_epoch, self.DATE_FORMAT)
        end_date = convert_epoch_to_utc_date(end_time_epoch, self.DATE_FORMAT)
        if response.get("alerts") and len(response["alerts"]) > 0:
            new_end_date = response["alerts"][0]["createTime"]
            new_end_time_epoch = convert_utc_date_to_epoch(new_end_date)
            obj = self.set_fetch_state(alert_type, start_time_epoch, new_end_time_epoch)
            self.log.info(f'''Creating task for {alert_type} from {start_date} to {new_end_date}''')
            return obj
        else:
            self.log.info(f'''No events are available for {alert_type} from {start_date} to {end_date}''')
            return None

    def transform_data(self, data):
        # import random
        # srcip = ["216.161.180.148", "54.203.63.36"]
        for d in data:
            d["createTime"] = convert_epoch_to_utc_date(int(time.time()), self.DATE_FORMAT)
        return data

    def is_time_remaining(self):
        now = datetime.datetime.utcnow()
        time_passed =  (now - self.start_time).total_seconds()
        self.log.info("checking time_passed: %s" % time_passed)
        return time_passed + self.STOP_TIME_OFFSET_SECONDS < self.FUNCTION_TIMEOUT

    def fetch(self, alert_type, start_time_epoch, end_time_epoch, pageToken):
        params = self.build_params(alert_type, start_time_epoch, end_time_epoch, pageToken, self.api_config['PAGINATION_LIMIT'])
        output_handler = OutputHandlerFactory.get_handler(self.config['Collection']['OUTPUT_HANDLER'], path="%s.json" % alert_type, config=self.config)
        next_request = True
        send_success = has_next_page = False
        count = 0
        alertcli = self.get_alert_client()

        try:
            while next_request:
                count += 1
                response = alertcli.alerts().list(**params).execute()
                fetch_success = response.get("alerts")
                if fetch_success:
                    data = response["alerts"]
                    data = self.transform_data(data)
                    send_success = output_handler.send(data)
                    # Todo save data and separate out fetching and sending pipelines
                    params['pageToken'] = response.get('next_page_token') if send_success else params['pageToken']
                    has_next_page = True if params['pageToken'] else False
                    self.log.info(f'''Finished Fetching Page: {count} Event Type: {alert_type} Datalen: {len(data)} starttime: {convert_epoch_to_utc_date(start_time_epoch, self.DATE_FORMAT)} endtime: {convert_epoch_to_utc_date(end_time_epoch, self.DATE_FORMAT)}''')
                is_data_ingested  = fetch_success and send_success
                next_request = is_data_ingested and has_next_page and self.is_time_remaining()

                if not (is_data_ingested or self.is_time_remaining()):  # saving in case of failures or function timeout
                    self.set_fetch_state(alert_type, start_time_epoch, end_time_epoch, params["pageToken"])
                elif not has_next_page:
                    self.log.info(f'''Moving starttime window for {alert_type} to {convert_epoch_to_utc_date(end_time_epoch + self.MOVING_WINDOW_DELTA, self.DATE_FORMAT)}''')
                    self.set_fetch_state(alert_type, end_time_epoch + self.MOVING_WINDOW_DELTA, None)


        finally:
            output_handler.close()
        self.log.info(f''' Total Pages fetched {count} for Event Type: {alert_type}''')

    def build_task_params(self):
        PROJECT_ID = "5cd0343ff2a30b3880beddb0"
        CLUSTER_NAME = "MongoDbTestCluster"
        tasks = []
        for alert_type in self.api_config['ALERT_TYPES']:
            if self.kvstore.has_key(alert_type):
                obj = self.kvstore.get(alert_type)
                if obj["end_time_epoch"] is None:
                    obj = self.set_new_end_epoch_time(alert_type, obj["start_time_epoch"])
            else:
                obj = self.set_new_end_epoch_time(alert_type, self.DEFAULT_START_TIME_EPOCH)
            if obj is None:  # no new events so continue
                continue
            tasks.append(obj)
        self.log.info(f'''Building tasks {len(tasks)}''')
        return tasks

    def run(self):
        self.log.info('Starting MongoDB Atlas Forwarder...')
        task_params = self.build_task_params()
        all_futures = {}
        self.log.info("spawning %d workers" % self.config['Collection']['NUM_WORKERS'])
        with futures.ThreadPoolExecutor(max_workers=self.config['Collection']['NUM_WORKERS']) as executor:
            results = {executor.submit(self.fetch, **param): param for param in task_params}
            all_futures.update(results)
        for future in futures.as_completed(all_futures):
            param = all_futures[future]
            alert_type = param["alert_type"]
            try:
                future.result()
                obj = self.kvstore.get(alert_type)
            except Exception as exc:
                self.log.error(f'''Alert Type: {alert_type} thread generated an exception: {exc}''', exc_info=True)
            else:
                self.log.info(f'''Alert Type: {alert_type} thread completed {obj}''')

    def test(self):
        params = {
            "start_time_epoch": 1505228760,
            "end_time_epoch": int(time.time()),
            "alert_type": "User reported phishing",
            "pageToken": None
        }
        self.fetch(**params)


def main(context=None):
    try:
        ns = MongoDBAtlasCollector()
        ns.run()
        # ns.test()
    except BaseException as e:
        traceback.print_exc()


if __name__ == '__main__':
    main()
