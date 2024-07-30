import time
import psutil
import os
import json
from functools import wraps
from contextlib import contextmanager


class TimeAndMemoryTracker:
    def __init__(self, logger, operation_name, active=True, log_level="INFO", **kwargs) -> None:
        self.active = active
        self.logger = logger
        self.operation_name = operation_name
        self.start_time = None
        self.end_time = None
        self.kwargs = kwargs
        self.log_level = log_level.lower()

    def __enter__(self):
        if self.active:
            self.start_time = time.time()
            self.start_memory = psutil.Process().memory_info().rss
            self.log_start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.active:
            self.end_time = time.time()
            self.end_memory = psutil.Process().memory_info().rss
            self.log_end()

    def log_message(self, message):
        if self.log_level == "error":
            self.logger.error(message)
        else:
            self.logger.info(message)

    def log_start(self, message):
        log_message = f"Starting {self.operation_name}"
        if self.kwargs:
            log_message += f" with parameters: {json.dumps(self.kwargs, default=str)}"
        self.log_message(log_message)

    def log_end(self, message):
        execution_time = self.end_time - self.start_time
        memory_used = self.end_memory - self.start_memory
        log_message = (
        f"{self.operation_name} completed in {execution_time:.2f} seconds and used {memory_used / 1024 / 1024:.2f} MB"
        )
        self.log_message(log_message)


def track_time_and_memory(logger, operation_name, active=True, log_level="INFO"):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            self = args[0] if args else None
            logger = self.log if self and hasattr(self, "log") else None
            log_kwargs = {k: v for k, v in self.kwargs.items() if not k.startswith("_")}
            with TimeAndMemoryTracker(logger, operation_name, active, log_level, **log_kwargs):
                return func(*args, **kwargs)
        return wrapper
    return decorator