from __future__ import annotations
import queue
import threading
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path


class Priority(IntEnum):
    IMMEDIATE = 1  # txt, md, py, json, csv < 10MB
    DEFERRED  = 2  # pdf, docx, xlsx, ifc, dwg, rvt или > 10MB


@dataclass(order=True)
class IndexTask:
    priority: Priority
    path: Path  = field(compare=False)
    action: str = field(compare=False)  # "index" | "reindex" | "delete"


class IndexQueue:
    """Thread-safe очередь задач индексации с двумя приоритетами."""

    def __init__(self) -> None:
        self._q: queue.PriorityQueue[IndexTask] = queue.PriorityQueue()
        self._lock = threading.Lock()

    def push(self, task: IndexTask) -> None:
        self._q.put(task)

    def pop_immediate(self, timeout: float = 0.1) -> IndexTask | None:
        """Достать задачу из очереди. Возвращает None если пусто или DEFERRED."""
        try:
            task = self._q.get(timeout=timeout)
            if task.priority == Priority.IMMEDIATE:
                return task
            # Вернуть обратно — это DEFERRED
            self._q.put(task)
            return None
        except queue.Empty:
            return None

    def pop_all_deferred(self) -> list[IndexTask]:
        """Забрать все DEFERRED задачи из очереди (для ночного scheduler)."""
        deferred: list[IndexTask] = []
        remaining: list[IndexTask] = []
        while not self._q.empty():
            try:
                task = self._q.get_nowait()
                if task.priority == Priority.DEFERRED:
                    deferred.append(task)
                else:
                    remaining.append(task)
            except queue.Empty:
                break
        for t in remaining:
            self._q.put(t)
        return deferred

    def size(self) -> int:
        return self._q.qsize()
