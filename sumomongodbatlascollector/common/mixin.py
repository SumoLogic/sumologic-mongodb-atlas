# -*- coding: future_fstrings -*-
import importlib
import sys

from common.logger import get_logger


class DynamicLoadMixin(object):
    INIT_FILE = "__init__.py"

    @classmethod
    def load_class(cls, full_class_string, invoking_module_name):
        """
            dynamically load a class from a string
        """

        #  using importlib https://docs.python.org/3/library/importlib.html find_spec not working in 2.7
        log = get_logger(__name__)
        try:
            module_path, class_name = cls._split_module_class_name(full_class_string, invoking_module_name)
            module = importlib.import_module(module_path)
            return getattr(module, class_name)
        except Exception as e:
            t, v, tb = sys.exc_info()
            log.error(f"Unable to import Module {full_class_string} Error: {e} Traceback: {tb}")
            raise

    @classmethod
    def _split_module_class_name(cls, full_class_string, invoking_module_name):
        file_name, class_name = full_class_string.rsplit(".", 1)
        parent_module = invoking_module_name.rsplit(".", 1)[0]+"." if "." in invoking_module_name else ""
        full_module_path = f"{parent_module}{file_name}"
        return full_module_path, class_name