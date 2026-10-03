"""A tool call that arrives while the server is warming up must not hang it.

Warmup imports lancedb, numpy and pyarrow in a background thread so the server
can answer `initialize` at once. Loading numpy's C extension queries the
standard handles, and on Windows that waits behind the MCP reader's pending
read on the stdin pipe — that is, for the client's next message. A client
waiting for its answer sends none: a search sent right after `initialize`
never got one. Reproduced on every attempt against the live checkout before
the fix (rag_server/startup.py).
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ANSWER_WITHIN = 120


class StartupImportGateTests(unittest.TestCase):
    def test_the_gate_is_open_when_nothing_is_warming_up(self):
        from rag_server import startup

        self.assertTrue(startup.wait_for_imports(timeout=0))

    def test_a_call_waits_for_the_imports_to_finish(self):
        from rag_server import startup

        startup.begin_imports()
        try:
            self.assertFalse(startup.wait_for_imports(timeout=0.05))
        finally:
            startup.end_imports()
        self.assertTrue(startup.wait_for_imports(timeout=0))


class ServerStartupRaceTests(unittest.TestCase):
    def test_search_sent_during_warmup_gets_an_answer(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / "config.yaml").write_text(
                "lemonade:\n  base_url: http://127.0.0.1:9/api/v1\n"
                "storage:\n  lancedb_path: data/lancedb\n  metadata_db: data/metadata.db\n"
                "watched_folders: []\n", encoding="utf-8")
            env = {k: v for k, v in os.environ.items() if k != "FLYING_RAG_CONFIG"}
            env.update(FLYING_RAG_HOME=str(home), NO_PROXY="*", PYTHONIOENCODING="utf-8")
            proc = subprocess.Popen([sys.executable, str(ROOT / "main.py")], cwd=str(ROOT),
                                    env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, text=True, encoding="utf-8")
            lines: queue.Queue = queue.Queue()
            threading.Thread(target=lambda: [lines.put(x) for x in proc.stdout],
                             daemon=True).start()

            def send(message):
                proc.stdin.write(json.dumps(message) + "\n")
                proc.stdin.flush()

            def receive(wanted_id, timeout):
                deadline = time.monotonic() + timeout
                while True:
                    line = lines.get(timeout=max(0.1, deadline - time.monotonic()))
                    if line.strip().startswith("{"):
                        message = json.loads(line)
                        if message.get("id") == wanted_id:
                            return message

            try:
                send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                      "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                                 "clientInfo": {"name": "test", "version": "1"}}})
                receive(1, 60)
                send({"jsonrpc": "2.0", "method": "notifications/initialized"})
                send({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                      "params": {"name": "search_documents",
                                 "arguments": {"query": "вентиляция", "top_k": 1}}})
                try:
                    answer = receive(2, ANSWER_WITHIN)
                except queue.Empty:
                    self.fail(f"no answer to a search sent during warmup in {ANSWER_WITHIN} s")
                self.assertIn("result", answer)
            finally:
                proc.kill()
                proc.wait()


if __name__ == "__main__":
    unittest.main()
