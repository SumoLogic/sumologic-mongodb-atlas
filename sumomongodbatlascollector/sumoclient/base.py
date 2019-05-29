from abc import ABCMeta, abstractmethod

import six

from common.logger import get_logger


@six.add_metaclass(ABCMeta)
class BaseOutputHandler():

    def __init__(self, *args, **kwargs):
        self.log = get_logger(__name__)
        self.setUp(*args, **kwargs)

    @abstractmethod
    def setUp(self, *args, **kwargs):
        pass

    @abstractmethod
    def send(self, data):
        pass