from __future__ import annotations

import asyncio
import threading
import queue as queue_module
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import main


class WatcherSerializationTests(unittest.TestCase):
    def _task(self, path: str, action: str = "index"):
        return SimpleNamespace(path=Path(path), action=action, priority=1)

    def test_worker_waits_for_indexer_before_starting_next_task(self):
        queue = main.CoalescingIndexQueue()
        queue.push(self._task("first.txt"))
        queue.push(self._task("second.txt"))
        first_started = threading.Event()
        release_first = threading.Event()
        calls: list[Path] = []

        def run_indexer(path: Path):
            calls.append(path)
            if path.name == "first.txt":
                first_started.set()
                release_first.wait(timeout=2)

        worker = main.SequentialWatcherWorker(queue, run_indexer=run_indexer)
        thread = threading.Thread(target=lambda: (worker.run_once(), worker.run_once()))
        thread.start()
        self.assertTrue(first_started.wait(timeout=1))
        self.assertEqual([Path("first.txt")], calls)
        release_first.set()
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        self.assertEqual([Path("first.txt"), Path("second.txt")], calls)

    def test_queue_coalesces_repeated_events_for_same_canonical_path(self):
        queue = main.CoalescingIndexQueue()
        queue.push(self._task("folder/../document.txt", "index"))
        queue.push(self._task("document.txt", "reindex"))

        self.assertEqual(1, queue.size())
        task = queue.pop_immediate(timeout=0)
        self.assertIsNotNone(task)
        self.assertEqual("reindex", task.action)

    def test_event_arriving_while_path_is_active_is_requeued(self):
        queue = main.CoalescingIndexQueue()
        queue.push(self._task("document.txt", "index"))
        active = queue.pop_immediate(timeout=0)

        queue.push(self._task("document.txt", "reindex"))
        queue.task_done(active)

        latest = queue.pop_immediate(timeout=0)
        self.assertIsNotNone(latest)
        self.assertEqual("reindex", latest.action)

    def test_full_queue_raises_observable_error(self):
        queue = main.CoalescingIndexQueue(maxsize=1)
        queue.push(self._task("first.txt"))

        with self.assertRaises(queue_module.Full):
            queue.push(self._task("second.txt"), timeout=0)

    def test_worker_logs_task_failure_and_continues(self):
        queue = main.CoalescingIndexQueue()
        queue.push(self._task("first.txt"))
        queue.push(self._task("second.txt"))
        calls = []

        def run_indexer(path):
            calls.append(path.name)
            if path.name == "first.txt":
                raise subprocess.CalledProcessError(1, "indexer")

        worker = main.SequentialWatcherWorker(queue, run_indexer=run_indexer)
        with patch.object(main, "_log") as log:
            self.assertFalse(worker.run_once(timeout=0))
            self.assertTrue(worker.run_once(timeout=0))

        self.assertEqual(["first.txt", "second.txt"], calls)
        self.assertTrue(any("failed" in call.args[0] for call in log.call_args_list))

    def test_deferred_batch_does_not_leave_paths_active(self):
        queue = main.CoalescingIndexQueue()
        deferred = self._task("drawing.pdf")
        deferred.priority = 2
        queue.push(deferred)

        self.assertEqual([deferred], queue.pop_all_deferred())
        queue.push(self._task("drawing.pdf"))
        self.assertEqual(1, queue.size())

    def test_worker_run_stops_cleanly_when_stop_event_is_set(self):
        queue = main.CoalescingIndexQueue()
        stop_event = threading.Event()
        worker = main.SequentialWatcherWorker(queue, run_indexer=Mock())
        thread = threading.Thread(target=worker.run, args=(stop_event,))
        thread.start()

        stop_event.set()
        queue.wake()
        thread.join(timeout=1)

        self.assertFalse(thread.is_alive())

    def test_shutdown_waits_for_active_indexer_before_returning(self):
        queue = main.CoalescingIndexQueue()
        queue.push(self._task("document.txt"))
        started = threading.Event()
        release = threading.Event()
        watcher = Mock()
        worker = main.SequentialWatcherWorker(
            queue,
            run_indexer=lambda path: (started.set(), release.wait(timeout=2)),
        )
        stop_event = threading.Event()
        worker_thread = threading.Thread(target=worker.run, args=(stop_event,))
        worker_thread.start()
        self.assertTrue(started.wait(timeout=1))
        runtime = (watcher, queue, stop_event, worker_thread)

        shutdown_thread = threading.Thread(target=main._shutdown_watcher_runtime, args=(runtime,))
        shutdown_thread.start()
        self.assertTrue(shutdown_thread.is_alive())
        release.set()
        shutdown_thread.join(timeout=2)

        self.assertFalse(shutdown_thread.is_alive())
        watcher.stop.assert_called_once_with()

    def test_mcp_mode_cleans_up_watcher_runtime(self):
        runtime = (Mock(), Mock(), Mock(), Mock())

        async def server_run():
            await asyncio.sleep(0)

        with patch.object(main, "warmup"), patch.object(main, "start_watcher", return_value=runtime), \
             patch.object(main, "_shutdown_watcher_runtime") as shutdown, \
             patch.dict(sys.modules, {"rag_server.server": SimpleNamespace(run=server_run)}):
            asyncio.run(main._run_mcp({}))

        shutdown.assert_called_once_with(runtime)

    def test_daemon_cleanup_uses_safe_runtime_shutdown(self):
        runtime = (Mock(), Mock(), Mock(), Mock())
        with patch.object(main, "_shutdown_watcher_runtime") as shutdown:
            main._run_daemon_loop(runtime, sleep=lambda _: (_ for _ in ()).throw(KeyboardInterrupt))

        shutdown.assert_called_once_with(runtime)

    def test_default_enqueue_timeout_is_finite_and_logged(self):
        queue = main.CoalescingIndexQueue(maxsize=1, enqueue_timeout=0)
        queue.push(self._task("first.txt"))

        with patch.object(main, "_log") as log, self.assertRaises(queue_module.Full):
            queue.push(self._task("second.txt"))

        self.assertTrue(any("queue full" in call.args[0] for call in log.call_args_list))

    @patch("subprocess.Popen")
    def test_indexer_subprocess_is_waited_for(self, popen):
        process = Mock()
        process.wait.return_value = 0
        popen.return_value = process

        main._run_indexer(Path("document.txt"))

        process.wait.assert_called_once_with()

    @patch("subprocess.Popen")
    def test_nonzero_indexer_exit_raises_controlled_failure(self, popen):
        process = Mock()
        process.wait.return_value = 7
        popen.return_value = process

        with self.assertRaises(subprocess.CalledProcessError):
            main._run_indexer(Path("document.txt"))


if __name__ == "__main__":
    unittest.main()
