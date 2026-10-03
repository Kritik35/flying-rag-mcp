"""One writer at a time, across processes, released when the holder dies."""
from __future__ import annotations

import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from storage.write_lock import WriterBusy, holder, lock_path_for, writer_lock  # noqa: E402

HOLD = textwrap.dedent("""
    import sys, time
    sys.path.insert(0, {root!r})
    from storage.write_lock import writer_lock
    with writer_lock({store!r}, owner="other-process", wait=0):
        print("held", flush=True)
        time.sleep({seconds})
""")


def _hold_in_child(store: Path, seconds: float) -> subprocess.Popen:
    code = HOLD.format(root=str(ROOT), store=str(store), seconds=seconds)
    proc = subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, text=True)
    assert proc.stdout.readline().strip() == "held"
    return proc


class WriterLockTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = Path(self._tmp.name) / "lancedb"

    def tearDown(self):
        self._tmp.cleanup()

    def test_lock_file_sits_next_to_the_store(self):
        self.assertEqual(lock_path_for(self.store), self.store.with_name("lancedb.writer.lock"))

    def test_a_second_process_is_refused_while_the_first_holds_it(self):
        proc = _hold_in_child(self.store, 30)
        try:
            with self.assertRaises(WriterBusy) as ctx:
                with writer_lock(self.store, owner="test", wait=0):
                    pass
            self.assertIn("other-process", str(ctx.exception))
            self.assertEqual(holder(self.store).get("owner"), "other-process")
        finally:
            proc.kill()
            proc.wait()

    def test_the_lock_is_released_when_the_holder_dies(self):
        proc = _hold_in_child(self.store, 60)
        proc.kill()
        proc.wait()
        with writer_lock(self.store, owner="test", wait=5):
            self.assertEqual(holder(self.store).get("owner"), "test")

    def test_a_waiting_writer_gets_it_when_it_comes_free(self):
        proc = _hold_in_child(self.store, 1.5)
        started = time.monotonic()
        try:
            with writer_lock(self.store, owner="test", wait=30):
                waited = time.monotonic() - started
        finally:
            proc.wait()
        self.assertGreater(waited, 0.5)

    def test_released_after_the_block_even_on_error(self):
        with self.assertRaises(ValueError):
            with writer_lock(self.store, owner="first", wait=0):
                raise ValueError("boom")
        with writer_lock(self.store, owner="second", wait=0):
            pass


if __name__ == "__main__":
    unittest.main()
