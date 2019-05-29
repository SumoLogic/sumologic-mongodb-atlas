from abc import ABCMeta, abstractmethod
import six

@six.add_metaclass(ABCMeta)
class Provider():

    def __init__(self, *args, **kwargs):
        self.setup(*args, **kwargs)

    def get_storage(self, storage_type, *args, **kwargs):
        storage_type_map = {
            "keyvalue": self.get_kvstorage
        }

        if storage_type in storage_type_map:
            instance = storage_type_map[storage_type](*args, **kwargs)
            return instance
        else:
            raise Exception("%s storage_type not found" % storage_type)


    @abstractmethod
    def get_kvstorage(self, *args, **kwargs):
        pass

    @abstractmethod
    def setup(self, *args, **kwargs):
        pass

@six.add_metaclass(ABCMeta)
class KeyValueStorage():
    #Todo support atomic + updates + batch get/set

    def __init__(self, *args, **kwargs):
        self.setup(*args, **kwargs)

    @abstractmethod
    def setup(self, *args, **kwargs):
        pass

    @abstractmethod
    def get(self, key):
        # returns  none if no key found
        pass

    @abstractmethod
    def set(self, key, value):
        pass

    @abstractmethod
    def delete(self, key):
        # does not throw exception if no key exists
        pass

    @abstractmethod
    def has_key(self, key):
        pass

    @abstractmethod
    def destroy(self):
        pass

