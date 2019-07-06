from common.logger import get_logger
from abc import ABCMeta, abstractmethod
import six

@six.add_metaclass(ABCMeta)
class Provider(object):

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
class KeyValueStorage(object):
    #Todo support atomic + updates + batch get/set

    def __init__(self, *args, **kwargs):
        self.log = get_logger(__name__) if not kwargs.get('logger') else kwargs['logger']
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

    @abstractmethod
    def acquire_lock(self, key):
        pass

    @abstractmethod
    def release_lock(self, key):
        pass

    def _get_lock_key(self, key):
        return "lockon_%s" % key

    def release_lock_on_expired_key(self, key):
        pass