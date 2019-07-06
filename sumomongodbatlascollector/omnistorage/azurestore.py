# -*- coding: future_fstrings -*-
import os
import hashlib
import sys
import time
import bson

if __name__ == "__main__":
    cur_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    sys.path.insert(0, cur_dir)

from azure.cosmosdb.table import (
    TableService,
    Entity,
    EntityProperty,
    EdmType,
)
from azure.common import AzureMissingResourceHttpError
from azure.cosmosdb.table.models import Entity
from omnistorage.base import Provider, KeyValueStorage
from omnistorage.factory import ProviderFactory
from common.logger import get_logger

class AzureKVStorage(KeyValueStorage):
    KEY_COL = "RowKey"
    VALUE_COL = "RowValue"


    @classmethod
    def get_table_service(cls):
        table_service = TableService(connection_string=os.getenv("APPSETTING_AzureWebJobsStorage"))
        return table_service

    def setup(self, name, force_create=False, *args, **kwargs):
        self.table_service = self.get_table_service()
        self.table_name = name
        if force_create:
            self.destroy()
        if not self.table_exists():
            self._create_table()

    def get(self, key, default=None):
        p_key = self._get_partition_key(key)
        try:
            entity = self.table_service.get_entity(self.table_name, p_key, key)
            value = self._deserialize(entity[self.VALUE_COL].value)
            self.log.debug(f'''Fetched Item from {self.table_name} table''')
            return value
        except AzureMissingResourceHttpError as e:
            self.log.warn(f'''Key: {key} Not Found''')
            return default
        except Exception as e:
            raise

    def _get_partition_key(self, key):
        # assuming keys can only be string or number(float, int)
        if not isinstance(key, str):
            key = str(key)
        key = key.encode('utf-8')
        m = hashlib.md5()
        m.update(key)
        return m.hexdigest()[:9]

    def _serialize(self, value):
        if isinstance(value, dict):
            value = bson.dumps(value)
        return value

    def _deserialize(self, value):
        if isinstance(value, bytes):
            try:
                value = bson.loads(value)
            except Exception as e:
                self.log.warning("Unable to deserialize %s" % str(e))
        return value

    def set(self, key, value):
        entity = Entity()
        entity[self.VALUE_COL] = EntityProperty(EdmType.BINARY, self._serialize(value))
        entity["PartitionKey"] = self._get_partition_key(key)
        entity[self.KEY_COL] = key
        response = self.table_service.insert_or_replace_entity(self.table_name, entity)
        self.log.debug(f'''Saved Item from {self.table_name} table response: {response}''')

    def has_key(self, key):
        # Todo catch item not found in get/delete
        is_present = True if self.get(key) else False
        return is_present

    def _wait_till_exists(self, timeout=10):
        start = time.time()
        while True:
            end = time.time()
            is_exists = self.table_exists()
            if is_exists or (start-end > timeout):
                break

    def _wait_till_not_exists(self, timeout=10):
        start = time.time()
        while True:
            end = time.time()
            not_exists = not self.table_exists()
            if not_exists or (start-end > timeout):
                break

    def delete(self, key):
        p_key = self._get_partition_key(key)
        response = self.table_service.delete_entity(self.table_name, p_key, key)
        self.log.debug(f'''Deleted Item from {self.table_name} table response: {response}''')

    def destroy(self):
        response =   self.table_service.delete_table(self.table_name)
        self._wait_till_not_exists()
        self.log.debug(f'''Deleted Table {self.table_name} response: {response}''')

    def table_exists(self):
        return self.table_service.exists(self.table_name)

    def _create_table(self):
        response = self.table_service.create_table(self.table_name)
        self._wait_till_exists()
        self.log.debug(f'''Created Table {self.table_name} response: {response}''')

    def acquire_lock(self, key):
        pass

    def release_lock(self, key):
        pass

    def release_lock_on_expired_key(self, key):
        pass


class AzureProvider(Provider):  # should we disallow direct access to these classes

    def setup(self, *args, **kwargs):
        pass

    def get_kvstorage(self, name, *args, **kwargs):
        return AzureKVStorage(name, *args, **kwargs)



if __name__ == "__main__":
    key = "abc"
    key2 = 101
    value = {"name": "Himanshu", '1': 23423, "fv": 12.34400}
    cli = ProviderFactory.get_provider("azure")
    kvstore = cli.get_storage("keyvalue", name='kvstore', force_create=True)
    kvstore.set(key, value)
    assert(kvstore.get(key) == value)
    assert(kvstore.has_key(key) == True)
    kvstore.delete(key)
    assert(kvstore.has_key(key) == False)
    # assert(kvstore.acquire_lock(key) == True)
    # assert(kvstore.acquire_lock(key) == False)
    # assert(kvstore.acquire_lock("blah") == True)
    # assert(kvstore.release_lock(key) == True)
    # assert(kvstore.release_lock(key) == False)
    # assert(kvstore.release_lock("blahblah") == False)
    kvstore.set(key2, value)
    assert(kvstore.get(key2) == value)
    assert(kvstore.has_key(key2) == True)
    kvstore.delete(key2)
    assert(kvstore.has_key(key2) == False)
    kvstore.destroy()
