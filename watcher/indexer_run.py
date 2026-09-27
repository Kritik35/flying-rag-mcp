"""Запуск индексатора для одного пути — со сторожем, который видит зависание.

Раньше `main.py:_run_indexer` звал `process.wait()` без таймаута, вывод
отправлял в DEVNULL, а stdin оставлял унаследованным от MCP-канала. Индексатор
на небольшом .xml завис и простоял больше суток с нулём процессора, и
последовательный рабочий поток наблюдателя стоял вместе с ним: за неделю
проиндексировано пять файлов.

Зависание отличается от медленной работы расходом процессора: большой PDF
индексируется десятки минут, но всё это время считает, а зависший процесс не
тратит ничего. Поэтому сторож убивает за отсутствие прогресса, а не по часам.
Жёсткий предел тоже есть — на случай бесконечного цикла, — но большой.
"""
from __future__ import annotations

import datetime as dt
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Optional

ROOT = Path(__file__).resolve().parent.parent

# Сколько секунд дерево процесса может не тратить процессор, прежде чем
# считаться зависшим. Индексатор, который ждёт ответа Lemonade, тоже почти не
# тратит процессор, поэтому порог — минуты, а не секунды.
DEFAULT_STALL_SECONDS = 600
# Страховка от бесконечного цикла. Самые большие PDF корпуса — около 80 МБ.
DEFAULT_HARD_TIMEOUT = 4 * 3600
# Минимальный прирост процессорного времени, который считается прогрессом.
_PROGRESS_EPS = 0.05


class IndexerStalled(RuntimeError):
    """Процесс не тратил процессор дольше порога и был убит."""


class IndexerTimedOut(RuntimeError):
    """Процесс превысил жёсткий предел и был убит."""


def tree_cpu_seconds(process) -> Optional[float]:
    """Суммарное процессорное время процесса и всех его потомков."""
    try:
        import psutil

        root = psutil.Process(process.pid)
        total = 0.0
        for p in [root, *root.children(recursive=True)]:
            try:
                t = p.cpu_times()
                total += t.user + t.system
            except psutil.Error:
                continue
        return total
    except Exception:
        return None


def kill_tree(process) -> None:
    """Убить процесс вместе с потомками.

    На Windows `.venv\\Scripts\\python.exe` — лаунчер, который запускает
    настоящий интерпретатор дочерним процессом; убийство одного лаунчера
    оставило бы интерпретатор висеть.
    """
    try:
        import psutil

        root = psutil.Process(process.pid)
        for p in root.children(recursive=True):
            try:
                p.kill()
            except psutil.Error:
                pass
        root.kill()
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


def watch(process, *, stall_seconds: float, hard_timeout: float,
          poll_seconds: float = 5.0,
          cpu_seconds: Optional[Callable] = None,
          kill_tree: Optional[Callable] = None,
          now: Optional[Callable[[], float]] = None,
          sleep: Optional[Callable[[float], None]] = None) -> int:
    """Дождаться процесса; убить при зависании или превышении предела.

    Зависимости разрешаются при вызове, а не при определении функции: иначе
    значения по умолчанию намертво привязаны к исходным time.sleep и psutil,
    и их нельзя подменить ни в тесте, ни при переносе на другую платформу.
    """
    cpu_seconds = cpu_seconds or tree_cpu_seconds
    kill_tree = kill_tree or globals()["kill_tree"]
    now = now or time.monotonic
    sleep = sleep or time.sleep
    started = now()
    last_cpu = cpu_seconds(process)
    last_progress = started
    while True:
        rc = process.poll()
        if rc is not None:
            return rc
        t = now()
        if t - started >= hard_timeout:
            kill_tree(process)
            raise IndexerTimedOut(f"превышен предел {hard_timeout:.0f} с")
        cpu = cpu_seconds(process)
        if cpu is None or last_cpu is None:
            # Измерить не удалось — не повод считать зависшим; решает предел.
            last_progress = t
        elif cpu - last_cpu > _PROGRESS_EPS:
            last_progress = t
        last_cpu = cpu if cpu is not None else last_cpu
        if t - last_progress >= stall_seconds:
            kill_tree(process)
            raise IndexerStalled(
                f"нет расхода процессора {t - last_progress:.0f} с")
        sleep(poll_seconds)


def _settings() -> tuple[float, float]:
    try:
        from config_loader import load_config
        idx = (load_config() or {}).get("indexing", {}) or {}
        return (float(idx.get("watcher_stall_seconds", DEFAULT_STALL_SECONDS)),
                float(idx.get("watcher_hard_timeout", DEFAULT_HARD_TIMEOUT)))
    except Exception:
        return DEFAULT_STALL_SECONDS, DEFAULT_HARD_TIMEOUT


def run_indexer(path: Path, *, log_path: Optional[Path] = None,
                python: str = sys.executable) -> None:
    """Проиндексировать путь; при сбое — исключение с понятной причиной.

    stdin не наследуется: у MCP-сервера это канал JSON-RPC, дочернему он не
    нужен. Вывод дописывается в журнал, а не пропадает в DEVNULL — иначе
    причину сбоя не узнать.
    """
    log_path = log_path or (ROOT / "data" / "watcher_indexer.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    stall, hard = _settings()
    with open(log_path, "a", encoding="utf-8", errors="replace") as log:
        log.write(f"\n=== {dt.datetime.now().isoformat(timespec='seconds')} "
                  f"{path}\n")
        log.flush()
        process = subprocess.Popen(
            [python, str(ROOT / "indexer.py"), str(path)],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            rc = watch(process, stall_seconds=stall, hard_timeout=hard)
        except (IndexerStalled, IndexerTimedOut) as exc:
            log.write(f"=== убит: {exc}\n")
            raise
    if rc:
        raise subprocess.CalledProcessError(rc, process.args)
