from __future__ import annotations
import hashlib
import sys
from pathlib import Path

from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileModifiedEvent, FileDeletedEvent
from watchdog.observers import Observer

from parsers.dispatcher import should_defer
from watcher.queue import IndexQueue, IndexTask, Priority

# Расширения которые игнорируем
_IGNORE_SUFFIXES = frozenset({".tmp", ".log", ".db", ".part", ".crdownload"})
_IGNORE_PREFIXES = ("~", ".")


def _should_ignore(path: Path) -> bool:
    name = path.name
    if any(name.startswith(p) for p in _IGNORE_PREFIXES):
        return True
    if path.suffix.lower() in _IGNORE_SUFFIXES:
        return True
    # Игнорируем файлы внутри data/lancedb
    parts = path.parts
    if "lancedb" in parts or "oda_temp" in parts or ".git" in parts:
        return True
    return False


class _RagHandler(FileSystemEventHandler):
    def __init__(self, index_queue: IndexQueue) -> None:
        super().__init__()
        self._queue = index_queue

    def _enqueue(self, path: Path, action: str) -> None:
        if _should_ignore(path):
            return
        priority = (
            Priority.IMMEDIATE
            if action == "delete"
            else Priority.DEFERRED if should_defer(path) else Priority.IMMEDIATE
        )
        self._queue.push(IndexTask(priority=priority, path=path, action=action))
        print(f"[watcher] {action} {priority.name} {path.name}", file=sys.stderr)

    def on_created(self, event):
        if not event.is_directory:
            self._enqueue(Path(event.src_path), "index")

    def on_modified(self, event):
        if not event.is_directory:
            self._enqueue(Path(event.src_path), "reindex")

    def on_deleted(self, event):
        if not event.is_directory:
            p = Path(event.src_path)
            self._enqueue(p, "delete")


class FolderWatcher:
    """Наблюдатель за несколькими папками через Watchdog."""

    def __init__(self, folders: list[str | Path], index_queue: IndexQueue) -> None:
        self._folders = [Path(f) for f in folders]
        self._queue = index_queue
        self._observer = Observer()
        self._handler = _RagHandler(index_queue)

    def start(self) -> None:
        for folder in self._folders:
            if folder.exists():
                self._observer.schedule(self._handler, str(folder), recursive=True)
                print(f"[watcher] watching {folder}", file=sys.stderr)
            else:
                print(f"[watcher] WARN folder not found: {folder}", file=sys.stderr)
        self._observer.start()
        print("[watcher] started", file=sys.stderr)

    def stop(self) -> None:
        self._observer.stop()
        self._observer.join()
        print("[watcher] stopped", file=sys.stderr)
