"""Flying RAG MCP v0.1 — точка входа. Запуск: python main.py"""
from __future__ import annotations
import asyncio
from collections import deque
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

import yaml


class CoalescingIndexQueue:
    """Bounded queue that keeps at most one task per canonical path."""

    def __init__(self, maxsize: int = 1024, enqueue_timeout: float = 0.25,
                 overflow_maxsize: int | None = None) -> None:
        self._maxsize = maxsize
        self._overflow_maxsize = maxsize if overflow_maxsize is None else overflow_maxsize
        self._enqueue_timeout = enqueue_timeout
        self._tasks = deque()
        self._pending = {}
        self._active = set()
        self._dirty = {}
        self._overflow = {}
        self._pressure = False
        self._ready = threading.Condition()

    @staticmethod
    def _key(path: Path) -> str:
        return str(Path(path).resolve(strict=False)).casefold()

    def push(self, task, timeout: float | None = None) -> None:
        key = self._key(task.path)
        with self._ready:
            if key in self._active:
                existing = self._dirty.get(key)
                if existing is not None:
                    task.priority = min(existing.priority, task.priority)
                self._dirty[key] = task
                return
            existing = self._pending.get(key)
            if existing is not None:
                existing.action = task.action
                existing.priority = min(existing.priority, task.priority)
                return
            existing = self._overflow.get(key)
            if existing is not None:
                existing.action = task.action
                existing.priority = min(existing.priority, task.priority)
                return
            effective_timeout = self._enqueue_timeout if timeout is None else timeout
            deadline = time.monotonic() + effective_timeout
            while len(self._tasks) + len(self._active) >= self._maxsize:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    while len(self._overflow) >= self._overflow_maxsize:
                        self._pressure = True
                        self._ready.notify_all()
                        self._ready.wait()
                    self._overflow[key] = task
                    _log(f"[watcher] queue full; retained {task.path.name}")
                    return
                self._ready.wait(remaining)
            self._tasks.append(task)
            self._pending[key] = task
            self._ready.notify()

    def _promote_overflow(self) -> None:
        while self._overflow and len(self._tasks) + len(self._active) < self._maxsize:
            key = next(iter(self._overflow))
            task = self._overflow.pop(key)
            self._tasks.append(task)
            self._pending[key] = task

    def pop_immediate(self, timeout: float = 0.1):
        from watcher.queue import Priority
        with self._ready:
            if not self._tasks:
                self._ready.wait(timeout)
            for task in self._tasks:
                if task.priority == Priority.IMMEDIATE:
                    self._tasks.remove(task)
                    key = self._key(task.path)
                    self._pending.pop(key, None)
                    self._active.add(key)
                    return task
            for key, task in list(self._overflow.items()):
                if task.priority == Priority.IMMEDIATE:
                    self._overflow.pop(key)
                    self._active.add(key)
                    self._ready.notify_all()
                    return task
            if self._pressure:
                # Under sustained saturation, process the oldest deferred task
                # early so the bounded producer cannot deadlock watchdog.
                if self._tasks:
                    task = self._tasks.popleft()
                    key = self._key(task.path)
                    self._pending.pop(key, None)
                    self._active.add(key)
                    return task
                if self._overflow:
                    key = next(iter(self._overflow))
                    task = self._overflow.pop(key)
                    self._active.add(key)
                    self._ready.notify_all()
                    return task
            return None

    def task_done(self, task) -> None:
        with self._ready:
            key = self._key(task.path)
            self._active.discard(key)
            dirty = self._dirty.pop(key, None)
            if dirty is not None:
                self._tasks.append(dirty)
                self._pending[key] = dirty
                self._ready.notify()
            self._promote_overflow()
            if len(self._overflow) < self._overflow_maxsize:
                self._pressure = False
            self._ready.notify_all()

    def pop_all_deferred(self) -> list:
        from watcher.queue import Priority
        with self._ready:
            result = [task for task in self._tasks if task.priority == Priority.DEFERRED]
            for task in result:
                self._tasks.remove(task)
                key = self._key(task.path)
                self._pending.pop(key, None)
            overflow_deferred = [
                (key, task) for key, task in self._overflow.items()
                if task.priority == Priority.DEFERRED
            ]
            for key, task in overflow_deferred:
                self._overflow.pop(key, None)
                result.append(task)
            self._promote_overflow()
            self._ready.notify_all()
            return result

    def pop_any(self, timeout: float = 0.1):
        """Pop any queued task during shutdown so no deferred event is lost."""
        with self._ready:
            if not self._tasks and not self._overflow:
                self._ready.wait(timeout)
            if self._tasks:
                task = self._tasks.popleft()
                key = self._key(task.path)
                self._pending.pop(key, None)
            elif self._overflow:
                key = next(iter(self._overflow))
                task = self._overflow.pop(key)
            else:
                return None
            self._active.add(key)
            self._ready.notify_all()
            return task

    def wake(self) -> None:
        with self._ready:
            self._ready.notify_all()

    def has_immediate(self) -> bool:
        from watcher.queue import Priority
        with self._ready:
            return (
                any(task.priority == Priority.IMMEDIATE for task in self._tasks)
                or any(task.priority == Priority.IMMEDIATE for task in self._overflow.values())
            )

    def size(self) -> int:
        with self._ready:
            return len(self._tasks) + len(self._overflow)


class SequentialWatcherWorker:
    """Processes watcher tasks one at a time and releases their coalescing key."""

    def __init__(self, index_queue, run_indexer=None, delete_path=None) -> None:
        self._queue = index_queue
        self._run_indexer = run_indexer or _run_indexer
        self._delete_path = delete_path

    def run_once(self, timeout: float = 1.0, *, drain_deferred: bool = False) -> bool:
        task = (
            self._queue.pop_any(timeout=timeout)
            if drain_deferred
            else self._queue.pop_immediate(timeout=timeout)
        )
        if task is None:
            return False
        try:
            if task.action == "delete":
                if self._delete_path is not None:
                    self._delete_path(task.path)
            else:
                _log(f"[worker] indexing {task.path.name}")
                self._run_indexer(task.path)
            return True
        except Exception as exc:
            _log(
                f"[worker] failed {task.path.name}: {type(exc).__name__}; "
                "will retry only after a new filesystem event"
            )
            return False
        finally:
            self._queue.task_done(task)

    def run(self, stop_event: threading.Event) -> None:
        while True:
            processed = self.run_once(
                timeout=0.5,
                drain_deferred=stop_event.is_set(),
            )
            if stop_event.is_set() and not processed and self._queue.size() == 0:
                return


def _log(msg: str) -> None:
    """Все служебные сообщения — только в stderr. stdout зарезервирован для MCP JSON-RPC."""
    print(msg, file=sys.stderr, flush=True)


def _cfg() -> dict:
    from config_loader import require_config
    return require_config()


def init_storage(cfg: dict) -> None:
    from storage.metadata_db import init_db
    meta = ROOT / cfg["storage"]["metadata_db"]
    lance = ROOT / cfg["storage"]["lancedb_path"]
    meta.parent.mkdir(parents=True, exist_ok=True)
    lance.mkdir(parents=True, exist_ok=True)
    init_db(meta)
    _log(f"[storage] metadata={meta.name}  lancedb={lance.name}")


def warmup(cfg: dict) -> None:
    """Прогрев: импортируем тяжёлые модули и делаем тестовый запрос к lemonade."""
    _log("[warmup] importing heavy modules...")
    try:
        import lancedb  # noqa: F401
        from storage.vector_store import search  # noqa: F401
        _log("[warmup] lancedb OK")
    except Exception as e:
        _log(f"[warmup] lancedb WARN: {e}")
    try:
        from embedder.client import _DEFAULT_PROVIDER, check_connection
        from embedder.contract import EmbeddingContractError

        url = cfg["lemonade"]["base_url"]
        if check_connection():
            # Verify the embedding contract at startup rather than leaving the
            # operator to discover a swapped model as "search got worse".
            try:
                state = _DEFAULT_PROVIDER.verify_contract()
                _log(f"[warmup] lemonade OK  {url}  model={state['actual_model'] or '?'} "
                     f"contract={state['status']}")
            except EmbeddingContractError as ce:
                _log(f"[warmup] EMBEDDING CONTRACT {ce.code}: {ce.detail}")
                _log("[warmup] search will be blocked until the configured model is loaded")
        else:
            _log("[warmup] lemonade OFFLINE — search будет недоступен")
    except Exception as e:
        _log(f"[warmup] lemonade WARN: {e}")

    try:
        from embedder.client import _DEFAULT_PROVIDER
        from storage.index_manifest import load_manifest, verify_manifest

        lance = ROOT / cfg["storage"]["lancedb_path"]
        manifest = load_manifest(lance)
        if manifest is None:
            _log("[warmup] index manifest absent (store not built by a contracted run yet)")
        else:
            status, code, detail = verify_manifest(
                manifest,
                model=_DEFAULT_PROVIDER.get_model_name(),
                dimension=int(manifest.get("dimension") or 0),
            )
            if code:
                _log(f"[warmup] INDEX CONTRACT {code}: {detail}")
            else:
                _log(f"[warmup] index contract OK: {manifest.get('model')} "
                     f"dim={manifest.get('dimension')} chunker={manifest.get('chunker')}")
    except Exception as e:
        _log(f"[warmup] index manifest WARN: {e}")
    try:
        from storage.vector_store import ensure_fts_index
        ensure_fts_index(ROOT / cfg["storage"]["lancedb_path"])
        _log("[warmup] FTS index ready")
    except Exception as e:
        _log(f"[warmup] FTS WARN: {e}")

    _log("[warmup] done — MCP ready")


def _run_indexer(path: Path) -> None:
    """Запускает indexer.py как subprocess для одного файла/папки."""
    CREATE_NO_WINDOW = 0x08000000
    process = subprocess.Popen(
        [sys.executable, str(ROOT / "indexer.py"), str(path)],
        stderr=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        creationflags=CREATE_NO_WINDOW,
    )
    return_code = process.wait()
    if return_code:
        raise subprocess.CalledProcessError(return_code, process.args)


def start_watcher(cfg: dict) -> tuple | None:
    """Запускает FolderWatcher и воркер очереди IMMEDIATE."""
    try:
        from watcher.monitor import FolderWatcher
        folders = cfg.get("watched_folders", [])
        if not folders:
            _log("[watcher] нет watched_folders в config.yaml, пропускаем")
            return None

        q = CoalescingIndexQueue()
        watcher = FolderWatcher(folders, q)
        watcher.start()

        def _delete_path(path: Path) -> None:
            try:
                cfg_now = _cfg()
                from storage.metadata_db import delete_file
                from storage.vector_store import delete_source

                delete_file(ROOT / cfg_now["storage"]["metadata_db"], str(path))
                delete_source(ROOT / cfg_now["storage"]["lancedb_path"], str(path))
                _log(f"[worker] deleted {path.name}")
            except Exception as de:
                _log(f"[worker] delete WARN {path.name}: {de}")

        worker = SequentialWatcherWorker(q, delete_path=_delete_path)

        stop_event = threading.Event()
        t = threading.Thread(target=worker.run, args=(stop_event,), daemon=True)
        t.start()
        _log(f"[watcher] monitoring {len(folders)} folder(s)")
        return watcher, q, stop_event, t

    except Exception as e:
        _log(f"[watcher] WARN: {e}")
        return None


def _shutdown_watcher_runtime(runtime: tuple | None) -> None:
    """Stop new events, drain immediate writes, then wait without interrupting them."""
    if runtime is None:
        return
    watcher, index_queue, stop_event, worker_thread = runtime
    watcher.stop()
    stop_event.set()
    index_queue.wake()
    worker_thread.join()


def _run_daemon_loop(runtime: tuple, sleep=None) -> None:
    if sleep is None:
        import time as time_module
        sleep = time_module.sleep
    try:
        while True:
            sleep(1.0)
    except KeyboardInterrupt:
        print("Daemon stopped by user")
    finally:
        _shutdown_watcher_runtime(runtime)


async def _run_mcp(cfg: dict):
    from rag_server.server import run
    
    async def run_background_tasks():
        _log("[mcp] running background warmup & watcher startup...")
        try:
            await asyncio.to_thread(warmup, cfg)
        except Exception as e:
            _log(f"[mcp] warmup error in background: {e}")
        try:
            return await asyncio.to_thread(start_watcher, cfg)
        except Exception as e:
            _log(f"[mcp] watcher startup error in background: {e}")
            return None

    background_task = asyncio.create_task(run_background_tasks())
    try:
        await run()
    finally:
        runtime = await background_task
        await asyncio.to_thread(_shutdown_watcher_runtime, runtime)


def main():
    import sys
    cfg = _cfg()

    if "--daemon" in sys.argv:
        import logging
        from logging.handlers import TimedRotatingFileHandler

        log_dir = ROOT / "storage"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "flying_rag.log"

        handler = TimedRotatingFileHandler(
            log_file,
            when="midnight",
            interval=1,
            backupCount=5,
            encoding="utf-8"
        )
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)

        logger = logging.getLogger("flying_rag")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        class StreamToLogger:
            def __init__(self, logger, log_level):
                self.logger = logger
                self.log_level = log_level
            def write(self, buf):
                for line in buf.rstrip().splitlines():
                    if line.strip():
                        self.logger.log(self.log_level, line.rstrip())
            def flush(self):
                pass

        sys.stdout = StreamToLogger(logger, logging.INFO)
        sys.stderr = StreamToLogger(logger, logging.ERROR)

        print("Flying RAG MCP Daemon started")
        init_storage(cfg)
        warmup(cfg)
        watcher_data = start_watcher(cfg)
        if watcher_data is None:
            print("Error: Watcher failed to start in daemon mode")
            sys.exit(1)

        print("Daemon running. Press Ctrl+C to stop.")
        _run_daemon_loop(watcher_data)
    else:
        _log("Flying RAG MCP v0.1")
        init_storage(cfg)
        _log("[mcp] Starting stdio server...")
        asyncio.run(_run_mcp(cfg))


if __name__ == "__main__":
    main()
