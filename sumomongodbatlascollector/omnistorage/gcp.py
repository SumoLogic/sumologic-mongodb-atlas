from google.cloud import datastore
from omnistorage.base import KeyValueStorage, Provider
from omnistorage.factory import ProviderFactory
from common.logger import get_logger
from omnistorage.errors import ItemNotFound


class GCPKVStorage(KeyValueStorage):
    VALUE_COL = "value"


    def setup(self, name, force_create=False, *args, **kwargs):
        self.table_name = name
        self.datastore_cli = datastore.Client() # don't need a project id if creds path is exported
        self.logger = get_logger(__name__)
        if force_create:
            self.destroy()
        # if not self.table_exists(self.table_name, self.region_name):
        #     self._create_table()

    def get(self, key, raise_exc=False):
        entity_key = self.datastore_cli.key(self.table_name, key)
        row = self.datastore_cli.get(entity_key)
        if not row:
            if raise_exc:
                raise ItemNotFound(f'Item with {key} does not exist.')
            else:
                return None
        self.logger.info(f'''Fetched Item from {self.table_name} table''')
        return row[self.VALUE_COL]

    def set(self, key, value):
        entity_key = self.datastore_cli.key(self.table_name, key)
        row = datastore.Entity(key=entity_key)
        row[self.VALUE_COL] = value
        self.datastore_cli.put(row)
        self.logger.info(f'''Saved Item with key {row.key.name} table {row.key.path}''')

    def has_key(self, key):
        is_present = True if self.get(key, raise_exc=False) else False
        return is_present

    def delete(self, key):
        entity_key = self.datastore_cli.key(self.table_name, key)
        self.datastore_cli.delete(entity_key)  # no error in case of key not found
        self.logger.info(f'''Deleted Item from {self.table_name} table''')

    def destroy(self):
        # enabling it costs
        # setup - project/service account creation/enabling the API for project
        query = self.datastore_cli.query(kind=self.table_name)
        all_keys = query.keys_only()
        self.datastore_cli.delete_multi(all_keys)


class GCPProvider(Provider):

    def setup(self, *args, **kwargs):
        pass

    def get_kvstorage(self, name, *args, **kwargs):
        return GCPKVStorage(name, *args, **kwargs)



if __name__ == "__main__":
    key = "abc"
    value = {"name": "Himanshu"}
    gcp_cli = ProviderFactory.get_provider("gcp")
    gcp_kvstore = gcp_cli.get_storage("keyvalue", name='kvstore', force_create=True)
    gcp_kvstore.set(key, value)
    print(gcp_kvstore.get(key) == value)
    print(gcp_kvstore.has_key(key) == True)
    gcp_kvstore.delete(key)
    print(gcp_kvstore.has_key(key) == False)

