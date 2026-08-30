"""Flying RAG MCP v0.1 — точка входа. Запуск: python main.py"""
from __future__ import annotations
import asyncio
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

import yaml


def _log(msg: str) -> None:
    """Все служебные сообщения — только в stderr. stdout зарезервирован для MCP JSON-RPC."""
    print(msg, file=sys.stderr, flush=True)


def _cfg() -> dict:
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


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
    import subprocess
    CREATE_NO_WINDOW = 0x08000000
    subprocess.Popen(
        [sys.executable, str(ROOT / "indexer.py"), str(path)],
        stderr=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        creationflags=CREATE_NO_WINDOW,
    )


def start_watcher(cfg: dict) -> tuple | None:
    """Запускает FolderWatcher и воркер очереди IMMEDIATE."""
    try:
        from watcher.monitor import FolderWatcher
        from watcher.queue import IndexQueue, Priority

        folders = cfg.get("watched_folders", [])
        if not folders:
            _log("[watcher] нет watched_folders в config.yaml, пропускаем")
            return None

        q = IndexQueue()
        watcher = FolderWatcher(folders, q)
        watcher.start()

        # Воркер: обрабатывает IMMEDIATE задачи из очереди
        def _worker():
            while True:
                task = q.pop_immediate(timeout=1.0)
                if task is None:
                    continue
                if task.action == "delete":
                    try:
                        cfg_now = _cfg()
                        from storage.metadata_db import delete_file
                        from storage.vector_store import delete_source

                        delete_file(ROOT / cfg_now["storage"]["metadata_db"], str(task.path))
                        delete_source(ROOT / cfg_now["storage"]["lancedb_path"], str(task.path))
                        _log(f"[worker] deleted {task.path.name}")
                    except Exception as de:
                        _log(f"[worker] delete WARN {task.path.name}: {de}")
                    continue
                _log(f"[worker] indexing {task.path.name}")
                _run_indexer(task.path)

        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        _log(f"[watcher] monitoring {len(folders)} folder(s)")
        return watcher, q

    except Exception as e:
        _log(f"[watcher] WARN: {e}")
        return None


async def _run_mcp(cfg: dict):
    from rag_server.server import run
    
    async def run_background_tasks():
        _log("[mcp] running background warmup & watcher startup...")
        try:
            await asyncio.to_thread(warmup, cfg)
        except Exception as e:
            _log(f"[mcp] warmup error in background: {e}")
        try:
            await asyncio.to_thread(start_watcher, cfg)
        except Exception as e:
            _log(f"[mcp] watcher startup error in background: {e}")
            
    asyncio.create_task(run_background_tasks())
    await run()


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
        try:
            while True:
                import time
                time.sleep(1.0)
        except KeyboardInterrupt:
            print("Daemon stopped by user")
            watcher_data[0].stop()
    else:
        _log("Flying RAG MCP v0.1")
        init_storage(cfg)
        _log("[mcp] Starting stdio server...")
        asyncio.run(_run_mcp(cfg))


if __name__ == "__main__":
    main()
