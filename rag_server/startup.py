"""Keep the server answering while it loads its heavy modules.

Two measures, both found by sending a search right after `initialize`, which
left the server silent on every attempt.

1. The stdio channel is moved off the process's standard input (Windows).
   The MCP reader keeps a synchronous ReadFile pending on the stdin pipe. A
   DLL loaded for the first time — numpy's C extension, pyarrow, lancedb —
   initialises its C runtime, which queries the standard handles; on a pipe
   with a read pending, that query waits for the read, i.e. for the client's
   next message. A client waiting for the answer sends none, so the import
   and the call behind it never finish. The channel is read through a
   duplicate of the handle instead, and standard input becomes NUL. (The same
   pipe hung child indexers until they got stdin=DEVNULL.)

2. Tool calls wait while warmup imports the tool chain, so two threads never
   import that stack at once.

The gate is open by default: code that runs without the server's warmup
(tests, scripts, the indexer) never waits.
"""
from __future__ import annotations

import sys
import threading

_imports_done = threading.Event()
_imports_done.set()


def begin_imports() -> None:
    """Close the gate before the server starts reading requests."""
    _imports_done.clear()


def end_imports() -> None:
    _imports_done.set()


def wait_for_imports(timeout: float | None = None) -> bool:
    """True when the heavy imports are done (or none are in progress)."""
    return _imports_done.wait(timeout)


STD_INPUT_HANDLE = 0xFFFFFFF6  # (DWORD)-10


def detach_stdin() -> bool:
    """Read the MCP channel through a private handle; make stdin NUL.

    Must run before anything reads sys.stdin. Returns False where it does not
    apply (not Windows, or no usable standard input).
    """
    if sys.platform != "win32":
        return False
    import ctypes
    import io
    import msvcrt
    import os

    try:
        private = os.dup(0)
    except OSError:
        return False
    nul = os.open(os.devnull, os.O_RDONLY)
    os.dup2(nul, 0)
    os.close(nul)
    ctypes.windll.kernel32.SetStdHandle(ctypes.c_ulong(STD_INPUT_HANDLE),
                                        msvcrt.get_osfhandle(0))
    sys.stdin = io.TextIOWrapper(open(private, "rb"), encoding="utf-8")
    return True
