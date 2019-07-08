# -*- coding: future_fstrings -*-
import shelve
import threading
import os
import sys
import datetime
import tempfile
import time

if __name__ == "__main__":
    cur_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    sys.path.insert(0, cur_dir)

from omnistorage.factory import ProviderFactory
from omnistorage.base import Provider, KeyValueStorage


if sys.platform != "win32":
    import fcntl


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
    LOCK_DATE_KEY = "last_locked_date"

    def setup(self, name, force_create=False, project_dir='', *args, **kwargs):
        self.key_locks = {}
        self.lock = threading.RLock()
        self.file_path = os.path.join(project_dir, name + ".db")
        if force_create:
            self.destroy()
        self.create_db()

    def create_db(self):
        if os.path.isfile(self.file_path):
            msg = "Old db exists"
        else:
            msg = "Creating new db"
            db = shelve.open(self.file_path)
            db.close()
        self.log.debug(msg)

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
            db = shelve.open(self.file_path, flag="r")
            value = db.get(key, None)
            db.close()
        if not value:
            self.log.warning("Key %s not Found" % key)
            return default
        self.log.debug(f'''Fetched Item {key} in {self.file_path} table''')
        return value

    def set(self, key, value):
        key = self._get_actual_key(key)
        with self.lock:
            db = shelve.open(self.file_path)
            db[key] = value
            db.close()
        self.log.debug(f'''Saved Item {key} in {self.file_path} table''')

    def delete(self, key):
        key = self._get_actual_key(key)
        with self.lock:
            db = shelve.open(self.file_path)
            if key in db:
                del db[key]
            db.close()
        self.log.debug(f'''Deleted Item {key} in {self.file_path} table''')

    def has_key(self, key):
        key = self._get_actual_key(key)
        with self.lock:
            db = shelve.open(self.file_path, flag="r")
            flag = key in db
            db.close()
        return flag

    def destroy(self):
        try:
            if os.path.isfile(self.file_path):
                os.remove(self.file_path)
                self.log.debug(f'''Deleted File {self.file_path}''')
            else:
                self.log.debug(f'''File {self.file_path} does not exists''')
        except OSError as e:
            raise Exception(f'''Error in removing {e.filename}:  {e.strerror}''')

    def acquire_lock(self, key):
        # In onprem the number of lock keys should fit in memory ie self.key_locks
        # In onprem these are actually process level locks so another process won't be able to access the key. This is because thread level locking is implemented via self.Lock
        # Todo move to context manager and have exclusive and shared lock option
        lockkey = self._get_lock_key(key)
        lockfile = os.path.normpath(tempfile.gettempdir() + '/' + lockkey)

        if sys.platform == 'win32':
            try:
                # file already exists, we try to remove (in case previous
                # execution was interrupted)
                if os.path.exists(lockfile):
                    os.unlink(lockfile)
                self.key_locks[lockkey] = os.open(lockfile, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NONBLOCK) # is this non blocking?
                self.log.debug("acquired_lock lockfile: %s" % lockfile)
                self.set(lockkey, {self.LOCK_DATE_KEY: time.time()})
                return True
            except OSError:
                _, e, tb = sys.exc_info()
                if e.errno == 13:
                    self.log.warning("Another instance is already running, quitting. %s" % (e))
                    return False
                else:
                    raise
        else:  # non Windows
            if lockkey not in self.key_locks:
                self.key_locks[lockkey] = open(lockfile, 'w')
                self.key_locks[lockkey].flush()
            try:
                fcntl.lockf(self.key_locks[lockkey], fcntl.LOCK_EX | fcntl.LOCK_NB) # non blocking
                self.log.debug("acquired_lock lockfile: %s" % lockfile)
                self.set(lockkey, {self.LOCK_DATE_KEY: time.time()})
                return True
            except IOError:
                self.log.warning("Another instance is already running, quitting.")
                self.log.debug("remove lock forcefully by removing %s" % lockfile)
                return False

    def release_lock(self, key):
        lockkey = self._get_lock_key(key)
        lockfile = os.path.normpath(tempfile.gettempdir() + '/' + lockkey)
        if lockkey in self.key_locks:
            try:
                if sys.platform == 'win32':
                    os.close(self.key_locks[lockkey])
                else:
                    fcntl.lockf(self.key_locks[lockkey], fcntl.LOCK_UN)
                    # os.close(self.fp)
                    self.key_locks[lockkey].close()
                if os.path.isfile(lockfile):
                    os.unlink(lockfile)
                del self.key_locks[lockkey]
                self.delete(lockkey)
                self.log.debug("released_lock lockfile: %s" % lockfile)
                return True
            except Exception as e:
                self.log.error("release_lock error")
                raise
        else:
            self.log.warning("lock not found lockfile: %s" % lockfile)
            return False

    def release_lock_on_expired_key(self, key, expiry_min=5):
        lock_key = self._get_lock_key(key)
        data = self.get(lock_key)
        if data and self.LOCK_DATE_KEY in data:
            now = time.time()
            past = data[self.LOCK_DATE_KEY]
            if (now - past) > expiry_min * 60:
                self.log.debug(f'''Lock time expired key: {key} passed time: {(now-past)/60} min''')
                self.release_lock(key)
        else:
            lockfile = os.path.normpath(tempfile.gettempdir() + '/' + lock_key)
            self.log.debug("remove lock forcefully by removing %s" % lockfile)


class OnPremProvider(Provider):

    def setup(self, *args, **kwargs):
        pass

    def get_kvstorage(self, name, *args, **kwargs):
        return OnPremKVStorage(name, *args, **kwargs)



if __name__ == "__main__":

    key = "abc"
    value = {"name": "Himanshu"}
    cli = ProviderFactory.get_provider("onprem")
    kvstore = cli.get_storage("keyvalue", name='kvstore', force_create=True)

    cli2 = ProviderFactory.get_provider("onprem")
    kvstore2 = cli.get_storage("keyvalue", name='kvstore', force_create=True)

    kvstore.set(key, value)
    assert(kvstore.get(key) == value)
    assert(kvstore.has_key(key) == True)
    kvstore.delete(key)
    assert(kvstore.has_key(key) == False)
    assert(kvstore.acquire_lock(key) == True)
    assert(kvstore2.acquire_lock(key) == True)
    assert(kvstore.acquire_lock("blah") == True)
    assert(kvstore.release_lock(key) == True)
    assert(kvstore.release_lock(key) == False)
    assert(kvstore.release_lock("blahblah") == False)
    kvstore.destroy()
