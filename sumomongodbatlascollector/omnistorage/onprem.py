# -*- coding: future_fstrings -*-
import shelve
import threading
import os
from sumoclient.utils import get_logger
from omnistorage.base import Provider, KeyValueStorage
import datetime


class OnPremKVStorage(KeyValueStorage):
    '''
    shelve is not thread safe therefore using table locks currently but one can also use a thread safe version
    with sqlite backend https://github.com/devnull255/sqlite-shelve
    # as d was opened WITHOUT writeback=True, beware:
    d['xx'] = [0, 1, 2]        # this works as expected, but...
    d['xx'].append(3)          # *this doesn't!* -- d['xx'] is STILL [0, 1, 2]!

    # having opened d without writeback=True, you need to code carefully:
    temp = d['xx']             # extracts the copy
    temp.append(5)             # mutates the copy
    d['xx'] = temp

    # default flag mode is c which is different than w because it creates db if it doesn't exists
    '''

    def setup(self, name, force_create=False, *args, **kwargs):
        self.lock = threading.RLock()
        cur_dir = os.path.dirname(__file__)
        self.file_name = os.path.join(cur_dir, name)
        self.logger = get_logger(__name__)
        if force_create:
            self.destroy()
        self.create_db()

    def create_db(self):
        if os.path.isfile(self.file_name+".db"):
            msg = "Old db exists"
        else:
            msg = "Creating new db"
            db = shelve.open(self.file_name)
            db.close()
        self.logger.info(msg)

    def _get_actual_key(self, key):
        ''' in shelve keys needs to be string therefore converting them to strings
            could have used not instance(key, str) but it's better to be explicit(need to test what will happen in case of objects as keys)
        '''
        if isinstance(key, (float, int, datetime.datetime)):
            return str(key)
        return key

    def get(self, key, default=None):
        key = self._get_actual_key(key)
        value = None
        with self.lock:
            db = shelve.open(self.file_name, flag="r")
            value = db.get(key, default)
            db.close()
        self.logger.info(f'''Fetched Item {key} in {self.file_name} table''')
        return value

    def set(self, key, value):
        key = self._get_actual_key(key)
        with self.lock:
            db = shelve.open(self.file_name)
            db[key] = value
            db.close()
        self.logger.info(f'''Saved Item {key} in {self.file_name} table''')

    def delete(self, key):
        key = self._get_actual_key(key)
        with self.lock:
            db = shelve.open(self.file_name)
            if key in db:
                del db[key]
            db.close()
        self.logger.info(f'''Deleted Item {key} in {self.file_name} table''')

    def has_key(self, key):
        key = self._get_actual_key(key)
        with self.lock:
            db = shelve.open(self.file_name, flag="r")
            flag = key in db
            db.close()
        return flag

    def destroy(self):
        try:
            if os.path.isfile(self.file_name):
                os.remove(self.file_name)
                self.logger.info(f'''Deleted File {self.file_name}''')
            else:
                self.logger.info(f'''File {self.file_name} does not exists''')
        except OSError as e:
            raise Exception(f'''Error in removing {e.filename}:  {e.strerror}''')


class OnPremProvider(Provider):

    def setup(self, *args, **kwargs):
        pass

    def get_kvstorage(self, name, *args, **kwargs):
        return OnPremKVStorage(name, *args, **kwargs)


