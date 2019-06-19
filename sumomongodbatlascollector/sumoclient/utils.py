# -*- coding: future_fstrings -*-
import time
import json
from datetime import datetime, timezone, timedelta
import dateutil.parser
from common.logger import get_logger


def get_current_timestamp():
    # The time.time() function returns the number of seconds since the epoch, as seconds. Note that the "epoch" is defined as the start of January 1st, 1970 in UTC.
    return time.time()


def convert_epoch_to_utc_date(timestamp, date_format="%Y-%m-%d %H:%M:%S"):
    log = get_logger(__name__)
    try:
        date_str = datetime.utcfromtimestamp(timestamp).strftime(date_format)
    except Exception as e:
        log.error(f'''Error in converting timestamp {timestamp}''', exc_info=True)
        date_str = datetime.utcnow().strftime(date_format)
    return date_str


def convert_utc_date_to_epoch(datestr, date_format='%Y-%m-%dT%H:%M:%S.%fZ', milliseconds=False):
    epoch = datetime(1970, 1, 1)
    timestamp = (datetime.strptime(datestr, date_format) - epoch).total_seconds()
    if milliseconds:
        timestamp = timestamp*1000
    return int(timestamp)


def get_body(data, jsondump=True):
    if isinstance(data, list):
        if jsondump:
            out = [json.dumps(d) for d in data]
        else:
            out = data
        body = "\n".join(out).encode("utf-8")
    else:
        body = json.dumps(data).encode("utf-8")
    return body


def addminutes(date_obj, num_minutes):
    new_date_obj = date_obj + timedelta(minutes=num_minutes)
    return new_date_obj.isoformat()


def get_datetime_from_isoformat(date_str):
    return dateutil.parser.parse(date_str)


def get_current_datetime():
    return datetime.now(tz=timezone.utc)
