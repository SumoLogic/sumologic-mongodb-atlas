import os, sys
from google.cloud import datastore

if __name__ == "__main__":
    cur_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    sys.path.insert(0, cur_dir)

from omnistorage.base import KeyValueStorage, Provider
from omnistorage.factory import ProviderFactory
from omnistorage.errors import ItemNotFound


class GCPKVStorage(KeyValueStorage):
    VALUE_COL = "value"

    def setup(self, name, force_create=False, *args, **kwargs):
        self.table_name = name
        self.datastore_cli = datastore.Client() # don't need a project id if creds path is exported
        if force_create:
            self.destroy()

    def get(self, key, default=None):
        entity_key = self.datastore_cli.key(self.table_name, key)
        row = self.datastore_cli.get(entity_key)
        if not row:
            self.log.warning("Key %s not Found" % key)
            return default
        self.log.debug(f'''Fetched Item from {self.table_name} table''')
        return row[self.VALUE_COL]

    def set(self, key, value):
        entity_key = self.datastore_cli.key(self.table_name, key)
        row = datastore.Entity(key=entity_key)
        row[self.VALUE_COL] = value
        self.datastore_cli.put(row)
        self.log.debug(f'''Saved Item with key {row.key.name} table {row.key.path}''')

    def has_key(self, key):
        is_present = False if self.get(key) is None else True
        return is_present

    def delete(self, key):
        entity_key = self.datastore_cli.key(self.table_name, key)
        self.datastore_cli.delete(entity_key)  # no error in case of key not found
        self.log.debug(f'''Deleted Item from {self.table_name} table''')

    def destroy(self):
        # enabling it costs
        # setup - project/service account creation/enabling the API for project
        query = self.datastore_cli.query(kind=self.table_name)
        all_keys = query.keys_only()
        self.datastore_cli.delete_multi(all_keys)
        self.log.debug(f'''Deleted Table {self.table_name}''')

    def acquire_lock(self, key):
        pass

    def release_lock(self, key):
        pass

    def release_lock_on_expired_key(self, key):
        pass


class GCPProvider(Provider):

    def setup(self, *args, **kwargs):
        pass

    def get_kvstorage(self, name, *args, **kwargs):
        return GCPKVStorage(name, *args, **kwargs)



if __name__ == "__main__":
    key = "abc"
    key2 = 101
    value = {"name": "Himanshu", '1': 23423, "fv": 12.34400}
    cli = ProviderFactory.get_provider("gcp")
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
