"""One writer at a time for a store.

The watcher, `reindex_path`, a manual `indexer.py`, maintenance and backup all
write the same LanceDB table and metadata database. LanceDB resolves two
concurrent commits by retrying, and a copy taken for a backup while a commit is
landing is not a consistent snapshot. So every write that changes what search
returns goes through this lock.

The lock is an operating-system lock on a file next to the store
(`<lancedb_path>.writer.lock`), not a marker file: if the holder dies, the OS
releases it, and a crashed indexer cannot leave the store locked for good. The
file also records who holds it, for the message the next writer prints.

Writers hold it only for their commit — seconds — not for the hours a file can
take to parse and embed, so a long indexing run does not block the watcher.
"""
from __future__ import annotations

import json
import os
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

DEFAULT_WAIT_SECONDS = 1800.0
_POLL_SECONDS = 0.5


class WriterBusy(RuntimeError):
    """Another process holds the store's writer lock past the wait limit."""


def lock_path_for(store: Path | str) -> Path:
    store = Path(store)
    return store.with_name(store.name + ".writer.lock")


def _try_lock(handle) -> bool:
    if sys.platform == "win32":
        import msvcrt

        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    import fcntl

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock(handle) -> None:
    if sys.platform == "win32":
        import msvcrt

        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def holder(store: Path | str, kind: str = "writer") -> dict:
    """Who last took the lock — informational; the OS lock is the truth.

    The first byte is the one locked on Windows, so the record starts after it.
    """
    store = Path(store)
    try:
        with open(store.with_name(f"{store.name}.{kind}.lock"), "rb") as f:
            f.seek(1)  # byte 0 is locked by the holder; reading it would fail
            raw = f.read().decode("utf-8", "replace").strip()
        return json.loads(raw) if raw else {}
    except Exception:
        return {}


def _configured_wait() -> float:
    try:
        from config_loader import load_config

        indexing = (load_config() or {}).get("indexing") or {}
        return float(indexing.get("writer_lock_wait_seconds", DEFAULT_WAIT_SECONDS))
    except Exception:
        return DEFAULT_WAIT_SECONDS


@contextmanager
def writer_lock(store: Path | str, *, owner: str, wait: float | None = None,
                sleep=time.sleep, now=time.monotonic) -> Iterator[None]:
    """Hold the store's writer lock for the duration of the block.

    `wait` is how long to wait for another holder (None: from config,
    `indexing.writer_lock_wait_seconds`; 0: fail at once). Raises WriterBusy
    when it does not come free in time — nothing has been written by then.
    """
    path = lock_path_for(store)
    path.parent.mkdir(parents=True, exist_ok=True)
    limit = _configured_wait() if wait is None else max(0.0, float(wait))
    handle = open(path, "a+b")
    try:
        deadline = now() + limit
        while not _try_lock(handle):
            if now() >= deadline:
                who = holder(store)
                raise WriterBusy(
                    f"writer lock {path.name} held by pid {who.get('pid', '?')} "
                    f"({who.get('owner', 'unknown')}) since {who.get('since', '?')}"
                )
            sleep(_POLL_SECONDS)
        try:
            record = json.dumps({
                "pid": os.getpid(),
                "owner": owner,
                "since": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            })
            handle.seek(1)
            handle.truncate()
            handle.write(record.encode("utf-8"))
            handle.flush()
        except OSError:
            pass  # the record is a courtesy; the lock is already ours
        try:
            yield
        finally:
            _unlock(handle)
    finally:
        handle.close()


class HeldLock:
    """An OS lock held until `release()` or the end of the process."""

    def __init__(self, handle, path: Path):
        self._handle = handle
        self.path = path

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            _unlock(self._handle)
        finally:
            self._handle.close()
            self._handle = None


def try_hold(store: Path | str, *, owner: str, kind: str = "watcher") -> HeldLock | None:
    """Take `<store>.<kind>.lock` without waiting, for as long as the caller lives.

    For roles one process at a time should play, like the folder watcher:
    every client session starts its own server, and each started a watcher
    of its own. None when another process holds it; the OS frees it when the
    holder exits or dies.
    """
    store = Path(store)
    path = store.with_name(f"{store.name}.{kind}.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+b")
    if not _try_lock(handle):
        handle.close()
        return None
    try:
        record = json.dumps({
            "pid": os.getpid(),
            "owner": owner,
            "since": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
        handle.seek(1)
        handle.truncate()
        handle.write(record.encode("utf-8"))
        handle.flush()
    except OSError:
        pass  # the record is a courtesy; the lock is already ours
    return HeldLock(handle, path)
