# -*- coding: future_fstrings -*-
import time
import json
from datetime import datetime
from common.logger import get_logger

def get_current_timestamp():
    return time.time()


def convert_epoch_to_utc_date(timestamp, date_format="%Y-%m-%d %H:%M:%S"):
    log = get_logger(__name__)
    try:
        date_str = datetime.utcfromtimestamp(timestamp).strftime(date_format)
    except Exception as e:
        log.error(f'''Error in converting timestamp {timestamp}''', exc_info=True)
        date_str = datetime.utcnow().strftime(date_format)
    return date_str


def convert_utc_date_to_epoch(datestr, date_format='%Y-%m-%dT%H:%M:%S.%fZ'):
    epoch = datetime(1970, 1, 1)
    timestamp = (datetime.strptime(datestr, date_format) - epoch).total_seconds()
    return timestamp

def get_body(data):
    if isinstance(data, list):
        out = [json.dumps(d) for d in data]
        body = "\n".join(out).encode("utf-8")
    else:
        body = json.dumps(data).encode("utf-8")
    return body



