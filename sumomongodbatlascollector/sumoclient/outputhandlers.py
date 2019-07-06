# -*- coding: future_fstrings -*-
import sys
import math
import zlib
from collections import Iterable
from sumoclient.base import BaseOutputHandler
from sumoclient.httputils import SessionPool, ClientMixin
from sumoclient.utils import get_body


class HTTPHandler(BaseOutputHandler):

    def setUp(self, config, *args, **kwargs):
        self.sumo_config = config["SumoLogic"]
        self.collection_config = config['Collection']
        self.sumoconn = SessionPool(self.collection_config['MAX_RETRY'], self.collection_config['BACKOFF_FACTOR'], logger=self.log)

    def send(self, data, extra_headers=None, jsondump=True, endpoint_key='SUMO_ENDPOINT'):
        if not data:
            return True
        sess = self.sumoconn.get_request_session()
        headers = {
            "content-type": "application/json",
            "accept": "application/json",
            "X-Sumo-Client": self.collection_config['PACKAGENAME']
        }

        if extra_headers:
            headers.update(extra_headers)

        for idx, batch in enumerate(self.bytesize_chunking(data, self.collection_config.get("MAX_PAYLOAD_BYTESIZE", 500000), jsondump), start=1):
            body = get_body(batch, jsondump)
            self.log.debug(f'''Sending batch {idx} len: {len(body)}''')
            if self.collection_config.get("COMPRESSED", True):
                body = zlib.compress(body)
                headers.update({"Content-Encoding": "deflate"})

            fetch_success, respjson = ClientMixin.make_request(self.sumo_config[endpoint_key], method="post",
                                                               session=sess, data=body, TIMEOUT=self.collection_config['TIMEOUT'],
                                                               headers=headers, logger=self.log)
            if not fetch_success:
                self.log.error(f'''Error in Sending to Sumo {respjson}''')
                return False
        return True

    def close(self):
        self.sumoconn.close()

    def bytesize_chunking(self, iterable, max_byte_size, jsondump=False):
        if not isinstance(iterable, Iterable):
            iterable = [iterable]
        num_batches = 0
        total_byte_size = 0
        payload = []
        cur_size = 0
        for item in iterable:
            item_size = self.utf8len(get_body(item, jsondump))
            if cur_size + item_size > max_byte_size:
                num_batches += 1
                yield payload
                payload = [item]
                cur_size = item_size
            else:
                payload.append(item)
                cur_size += item_size
            total_byte_size += item_size
        if payload:
            num_batches += 1
            yield payload
        self.log.debug(f'''Chunking data total_size: {total_byte_size} num_batches: {num_batches}''')

    @classmethod
    def batchsize_chunking(cls, iterable, size=1):
        l = len(iterable)
        for idx in range(0, l, size):
            data = iterable[idx:min(idx + size, l)]
            yield data

    @classmethod
    def utf8len(cls, s):
        if not isinstance(s, bytes):
            s = s.encode('utf-8')
        return len(s)

    @classmethod
    def get_chunk_size(cls, data, MAX_SIZE=500*1000):
        body = get_body(data)
        total_bytes = cls.utf8len(body)
        batch_count = math.ceil(total_bytes/(MAX_SIZE*1.0))
        chunk_size = math.floor(len(data)/(batch_count*1.0))
        chunk_size = 1 if chunk_size == 0 else chunk_size
        return int(batch_count), int(chunk_size)


class STDOUTHandler(BaseOutputHandler):

    def setUp(self, config, *args, **kwargs):
        pass

    def send(self, data):
        if not data:
            return
        body = get_body(data)
        self.log.debug(f'Posting data: len {len(body)}')
        print(body)
        return True

    def close(self):
        sys.stdout.flush()


class FileHandler(BaseOutputHandler):

    def setUp(self, config, path=None, *args, **kwargs):
        self.filepath = path or "alerts.log"
        self.fp = open(self.filepath, "ab")

    def send(self, data):
        if not data:
            return
        body = get_body(data)
        self.log.debug(f'Posting data: len {len(body)}')
        self.fp.write(body)
        return True

    def close(self):
        self.fp.close()
