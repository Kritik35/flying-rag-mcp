"""One folder watcher per store, however many servers run.

Each client session starts its own server, and each server started its own
watcher. On 2026-10-08 eleven servers were running and two indexers were
parsing the same file at once, each started by a different server's watcher;
every one of the eleven was watching the same folders.

The watcher now runs only in the server holding `<store>.watcher.lock`, an
operating-system lock held for the life of the process. The others try again
from time to time and take over when the holder exits or dies.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent


class HoldTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Path(self.tmp.name) / "lancedb"

    def tearDown(self):
        self.tmp.cleanup()

    def test_only_one_holder_at_a_time(self):
        from storage.write_lock import try_hold

        first = try_hold(self.store, owner="a")
        self.assertIsNotNone(first)
        self.assertIsNone(try_hold(self.store, owner="b"))
        first.release()
        second = try_hold(self.store, owner="b")
        self.assertIsNotNone(second)
        second.release()

    def test_the_watcher_lock_is_not_the_writer_lock(self):
        from storage.write_lock import try_hold, writer_lock

        held = try_hold(self.store, owner="watcher")
        with writer_lock(self.store, owner="indexer", wait=0):
            pass
        held.release()

    def test_a_dead_holder_frees_the_lock(self):
        from storage.write_lock import try_hold

        code = ("import sys; sys.path.insert(0, sys.argv[1]);"
                "from storage.write_lock import try_hold;"
                "from pathlib import Path;"
                "assert try_hold(Path(sys.argv[2]), owner='child') is not None;"
                "import os; os._exit(0)")
        subprocess.run([sys.executable, "-c", code, str(ROOT), str(self.store)],
                       check=True, timeout=60)
        held = try_hold(self.store, owner="parent")
        self.assertIsNotNone(held)
        held.release()


class SingleWatcherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Path(self.tmp.name) / "lancedb"
        self.cfg = {"storage": {"lancedb_path": str(self.store)}, "watched_folders": ["x"]}

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_second_server_does_not_start_a_watcher(self):
        import main
        from storage.write_lock import try_hold

        other = try_hold(self.store, owner="other server")
        stop = threading.Event()
        stop.set()
        with mock.patch.object(main, "start_watcher") as start:
            self.assertIsNone(main.start_single_watcher(self.cfg, stop, retry_seconds=0.01))
        start.assert_not_called()
        other.release()

    def test_it_takes_over_when_the_holder_goes(self):
        import main
        from storage.write_lock import try_hold

        other = try_hold(self.store, owner="other server")
        threading.Timer(0.3, other.release).start()
        stop = threading.Event()
        with mock.patch.object(main, "start_watcher", return_value="runtime") as start:
            claimed = main.start_single_watcher(self.cfg, stop, retry_seconds=0.05)
        start.assert_called_once()
        runtime, lock = claimed
        self.assertEqual(runtime, "runtime")
        self.assertIsNone(try_hold(self.store, owner="third"))
        lock.release()

    def test_a_watcher_that_fails_to_start_gives_the_lock_back(self):
        import main
        from storage.write_lock import try_hold

        with mock.patch.object(main, "start_watcher", return_value=None):
            self.assertIsNone(main.start_single_watcher(self.cfg, threading.Event()))
        held = try_hold(self.store, owner="next")
        self.assertIsNotNone(held)
        held.release()


if __name__ == "__main__":
    unittest.main()
