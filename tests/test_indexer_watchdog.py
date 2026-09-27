"""Наблюдатель ждал индексатор вечно — и один зависший файл останавливал всё.

`main.py:_run_indexer` запускал индексатор и звал `process.wait()` без
таймаута, вывод отправлял в DEVNULL, а stdin оставлял унаследованным от
MCP-канала. Индексатор на небольшом .xml завис 26.09 и простоял больше суток:
стек пустой, ноль секунд процессора — он встал ещё до первой строки Python.
Рабочий поток наблюдателя последовательный, так что за неделю проиндексировано
пять файлов; кто-то убивал зомби вручную скриптом с жёстко вписанными PID.

Сторож отличает зависание от медленной работы по расходу процессора. Большой
PDF индексируется десятки минут — но всё это время тратит процессор. Зависший
процесс не тратит ничего. Поэтому убивает не часы, а отсутствие прогресса:
если за `stall_seconds` дерево процесса не потратило процессора, оно убивается
целиком (на Windows у venv-лаунчера есть дочерний интерпретатор). Жёсткий
предел тоже есть, но большой — на случай бесконечного цикла.
"""
from __future__ import annotations

import subprocess
import unittest

from watcher.indexer_run import IndexerStalled, IndexerTimedOut, watch


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s


class FakeProcess:
    def __init__(self, exits_at=None, returncode=0):
        self.exits_at = exits_at
        self.returncode = None
        self._rc = returncode
        self.clock = None
        self.killed = False

    def poll(self):
        if self.exits_at is not None and self.clock.now() >= self.exits_at:
            self.returncode = self._rc
        return self.returncode


def run(proc, cpu_fn, **kw):
    clock = FakeClock()
    proc.clock = clock
    killed = []
    return watch(proc, cpu_seconds=cpu_fn, kill_tree=lambda p: killed.append(p),
                 now=clock.now, sleep=clock.sleep, poll_seconds=5, **kw), killed


class WatchdogTests(unittest.TestCase):
    def test_a_normal_run_returns_its_exit_code(self):
        proc = FakeProcess(exits_at=30, returncode=0)
        rc, killed = run(proc, cpu_fn=lambda p: proc.clock.now(),
                         stall_seconds=60, hard_timeout=3600)

        self.assertEqual(rc, 0)
        self.assertEqual(killed, [])

    def test_a_process_that_spends_no_cpu_is_killed_as_stalled(self):
        """Ровно наблюдённое зависание: ноль процессора, выхода нет."""
        proc = FakeProcess(exits_at=None)
        with self.assertRaises(IndexerStalled):
            run(proc, cpu_fn=lambda p: 0.0, stall_seconds=60, hard_timeout=3600)

    def test_the_stalled_tree_is_killed(self):
        proc = FakeProcess(exits_at=None)
        killed = []
        clock = FakeClock()
        proc.clock = clock
        with self.assertRaises(IndexerStalled):
            watch(proc, cpu_seconds=lambda p: 0.0, kill_tree=killed.append,
                  now=clock.now, sleep=clock.sleep, poll_seconds=5,
                  stall_seconds=60, hard_timeout=3600)
        self.assertEqual(killed, [proc])

    def test_a_slow_but_working_process_is_left_alone(self):
        """Большой PDF: 40 минут, но процессор тратится всё время."""
        proc = FakeProcess(exits_at=2400, returncode=0)
        rc, killed = run(proc, cpu_fn=lambda p: proc.clock.now() * 0.5,
                         stall_seconds=60, hard_timeout=7200)

        self.assertEqual(rc, 0)
        self.assertEqual(killed, [])

    def test_the_hard_limit_still_applies_to_an_endless_loop(self):
        proc = FakeProcess(exits_at=None)
        with self.assertRaises(IndexerTimedOut):
            run(proc, cpu_fn=lambda p: proc.clock.now(), stall_seconds=60,
                hard_timeout=600)

    def test_cpu_measurement_failure_is_not_a_stall(self):
        """Если процессор измерить нельзя, решает только жёсткий предел."""
        proc = FakeProcess(exits_at=120, returncode=0)
        rc, _ = run(proc, cpu_fn=lambda p: None, stall_seconds=60, hard_timeout=3600)

        self.assertEqual(rc, 0)


class LaunchTests(unittest.TestCase):
    def test_stdin_is_not_inherited_and_output_is_kept(self):
        """stdin MCP-сервера — это канал JSON-RPC; дочернему он не нужен.
        Вывод пишется в журнал, а не в DEVNULL: иначе причину не узнать."""
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from watcher import indexer_run

        log = Path(tempfile.mkdtemp()) / "indexer.log"
        with patch("subprocess.Popen") as popen, \
                patch.object(indexer_run, "watch", return_value=0):
            indexer_run.run_indexer(Path("файл.xml"), log_path=log)

        kwargs = popen.call_args.kwargs
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
        self.assertIsNot(kwargs["stdout"], subprocess.DEVNULL)
        self.assertTrue(log.exists())


if __name__ == "__main__":
    unittest.main()
