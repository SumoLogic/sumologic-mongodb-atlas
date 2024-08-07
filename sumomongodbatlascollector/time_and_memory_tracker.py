import time
import psutil
from typing import List, Dict, Any


class TimeAndMemoryTracker:
    def __init__(self, activate: bool = False):
        self._stack: List[Dict[str, Any]] = []
        self.activate = activate

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        while self._stack:
            self.end()

    def start(self, operation_name: str) -> str:
        if not self.activate:
            return ""
        operation_name = operation_name.lower()
        entry = {
            "operation_name": operation_name,
            "start_time": time.time(),
            "start_memory": psutil.Process().memory_info().rss,
        }
        self._stack.append(entry)
        return self._format_start_message(entry)

    def end(self, operation_name: str = None) -> str:
        if not self.activate:
            return ""
        if self._stack:
            exit_time = time.time()
            exit_memory = psutil.Process().memory_info().rss
            entry = self._stack[-1]

            if operation_name:
                operation_name = operation_name.lower()
                if entry["operation_name"] != operation_name:
                    raise ValueError(
                        f"Attempting to end '{operation_name}' but the current operation is '{entry['operation_name']}'"
                    )

            self._stack.pop()
            return self._format_end_message(entry, exit_time, exit_memory)
        return ""

    def _format_start_message(self, entry: Dict[str, Any]) -> str:
        return (
            f"Starting {entry['operation_name']} at {entry['start_time']:.2f}, "
            f"initial memory: {entry['start_memory'] / 1024 / 1024:.2f} MB"
        )

    def _format_end_message(
        self, entry: Dict[str, Any], exit_time: float, exit_memory: int
    ) -> str:
        execution_time = exit_time - entry["start_time"]
        memory_used = exit_memory - entry["start_memory"]
        return (
            f"{entry['operation_name']} completed in {execution_time:.2f} seconds, "
            f"used {memory_used / 1024 / 1024:.2f} MB, "
            f"end time: {exit_time:.2f}, final memory: {exit_memory / 1024 / 1024:.2f} MB"
        )
