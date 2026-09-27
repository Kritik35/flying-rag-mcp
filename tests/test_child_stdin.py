"""Дочерний процесс MCP-сервера не должен наследовать его stdin.

Причина, по которой индексатор, запущенный наблюдателем, висел больше суток с
нулём процессора и без единого кадра Python, установлена опытом. У stdio
MCP-сервера stdin — канал JSON-RPC, и сервер держит на нём блокирующее
чтение. На Windows дочерний интерпретатор, унаследовавший такой дескриптор,
зависает на старте, пока то чтение не завершится, — то есть навсегда.
Воспроизведение: с унаследованным stdin `python -c "print('ok')"` висит, с
`stdin=DEVNULL` заканчивается за 0.1 с.

Это касается каждого запуска из процесса сервера: наблюдателя (исправлено в
watcher/indexer_run.py), `reindex_path` — отсюда задания, проваленные с
«finished without DONE marker», — и вспомогательных вызовов PowerShell и
конвертера DWG.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


@unittest.skipUnless(sys.platform == "win32", "поведение дескрипторов Windows")
class PlatformBehaviourTests(unittest.TestCase):
    """Само явление: без него исправление выглядит как перестраховка."""

    PARENT = textwrap.dedent('''
        import subprocess, sys, threading, time, os
        threading.Thread(target=lambda: sys.stdin.buffer.read(1), daemon=True).start()
        time.sleep(0.5)
        kw = {"stdout": subprocess.PIPE}
        if sys.argv[1] == "devnull":
            kw["stdin"] = subprocess.DEVNULL
        p = subprocess.Popen([sys.executable, "-c", "print('ok')"], **kw)
        try:
            p.communicate(timeout=4)
            print("finished")
        except subprocess.TimeoutExpired:
            p.kill()
            print("hung")
        sys.stdout.flush()
        os._exit(0)
    ''')

    def _run(self, mode: str) -> str:
        script = Path(tempfile.mkdtemp()) / "parent.py"
        script.write_text(self.PARENT, encoding="utf-8")
        # stdin родителя — канал, в который никто не пишет: как у MCP-сервера.
        feeder = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"],
                                  stdout=subprocess.PIPE)
        try:
            out = subprocess.run([sys.executable, str(script), mode],
                                 stdin=feeder.stdout, capture_output=True,
                                 text=True, timeout=30).stdout.strip()
        finally:
            feeder.kill()
        return out

    def test_an_inherited_blocked_stdin_hangs_the_child(self):
        self.assertEqual(self._run("inherit"), "hung")

    def test_devnull_stdin_lets_the_child_start(self):
        self.assertEqual(self._run("devnull"), "finished")


class ReindexPathTests(unittest.TestCase):
    def test_reindex_path_does_not_hand_its_stdin_to_the_indexer(self):
        import rag_server.tools as tools

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            watched = root / "watched"
            target = watched / "fixture.txt"
            target.parent.mkdir(parents=True)
            target.write_text("fixture", encoding="utf-8")
            cfg = {"watched_folders": [str(watched)],
                   "storage": {"lancedb_path": "lancedb", "metadata_db": "metadata.db"}}
            with patch.object(tools, "ROOT", root), \
                    patch.object(tools, "_cfg", return_value=cfg), \
                    patch("subprocess.Popen", return_value=Mock(pid=1)) as popen, \
                    patch("storage.metadata_db.create_reindex_job"):
                tools.reindex_path(str(target))

        self.assertIs(popen.call_args.kwargs.get("stdin"), subprocess.DEVNULL)


class HelperCallsTests(unittest.TestCase):
    def test_thermal_powershell_calls_do_not_inherit_stdin(self):
        from embedder import thermal

        with patch("subprocess.run") as run:
            run.return_value = Mock(returncode=1, stdout="")
            ctl = thermal.ThermalController.__new__(thermal.ThermalController)
            for probe in ("get_cpu_temp_perf_counters", "get_cpu_temp_wmi"):
                getattr(ctl, probe)()

        self.assertTrue(run.call_args_list)
        for call in run.call_args_list:
            self.assertIs(call.kwargs.get("stdin"), subprocess.DEVNULL, call)


if __name__ == "__main__":
    unittest.main()
