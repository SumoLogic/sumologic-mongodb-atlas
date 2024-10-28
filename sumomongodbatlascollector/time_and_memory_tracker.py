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

        operation_name = operation_name.lower()
        entry = {
            "operation_name": operation_name
        }
        if self.activate:
            entry.update({
                "start_time": time.time(),
                "start_memory": psutil.Process().memory_info().rss
            })

        self._stack.append(entry)
        return self._format_start_message(entry)

    def end(self, operation_name: str = None) -> str:
        if self._stack:

            entry = self._stack[-1]
            if operation_name:
                operation_name = operation_name.lower()
                if entry["operation_name"] != operation_name:
                    raise ValueError(
                        f"Attempting to end '{operation_name}' but the current operation is '{entry['operation_name']}'"
                    )
            self._stack.pop()
            if self.activate:
                entry.update({
                    "exit_time": time.time(),
                    "exit_memory": psutil.Process().memory_info().rss
                })
            return self._format_end_message(entry)
        else:
            return f"{operation_name.lower()} completed "

    def _format_start_message(self, entry: Dict[str, Any]) -> str:
        if self.activate:
            return (
                f"Starting {entry['operation_name']} start_time: {entry['start_time']:.2f} "
                f"initial_memory_mb: {entry['start_memory'] / 1024 / 1024:.2f}"
            )
        else:
            return f"Starting {entry['operation_name']} "

    def _format_end_message(self, entry: Dict[str, Any]) -> str:
        if self.activate:
            execution_time = exit_time - entry["start_time"]
            memory_used = exit_memory - entry["start_memory"]
            return (
                f"Completed {entry['operation_name']} execution_seconds: {execution_time:.2f}"
                f"memory_used_mb: {memory_used / 1024 / 1024:.2f}"
                f"start_time: {entry['start_time']:.2f}, end_time: {exit_time:.2f}, final_memory_mb: {exit_memory / 1024 / 1024:.2f}"
            )
        else:
            return f"Completed {entry['operation_name']} "
