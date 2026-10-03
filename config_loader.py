"""One place that decides which config.yaml the runtime is using.

Two problems this fixes.

*Working directory.* Several modules resolved `config.yaml` relative to the
current directory first. An MCP server is started by its client from an
arbitrary directory, so that either missed the project config or — worse —
silently picked up an unrelated `config.yaml` that happened to sit in the
client's working directory.

*Testability.* Verifying the real indexer or the real search path meant
overwriting the operator's live `config.yaml`. `FLYING_RAG_CONFIG` points the
whole runtime at another file instead, so a local verification run never touches
the working setup.

*Where the operator's files live.* Code and data used to share one folder:
config and every relative storage path were resolved against the directory
holding this file. That holds for a git checkout and breaks for any installed
form — pip puts the code in site-packages, uvx in a throwaway cache, and an
upgrade replaces the folder, index included. `FLYING_RAG_HOME` names the folder
that owns `config.yaml` and `data/`; unset, it is the code folder, so an
existing checkout keeps working unchanged.
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
CONFIG_ENV = "FLYING_RAG_CONFIG"
HOME_ENV = "FLYING_RAG_HOME"
DEFAULT_NAME = "config.yaml"


def _absolute(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (Path.cwd() / path)


def home() -> Path:
    """Folder that owns the operator's config and data."""
    override = os.getenv(HOME_ENV, "").strip()
    return _absolute(override) if override else ROOT


def config_path() -> Path:
    """Absolute path of the config file the runtime should use."""
    override = os.getenv(CONFIG_ENV, "").strip()
    if override:
        return _absolute(override)
    return home() / DEFAULT_NAME


def resolve(value: str | os.PathLike) -> Path:
    """A path taken from config: absolute as written, otherwise under home().

    Relative paths in a config named by FLYING_RAG_CONFIG resolve the same way,
    against home() and not against that file's folder — as they always have.
    """
    path = Path(value).expanduser()
    return path if path.is_absolute() else (home() / path)


SHARED_DIR_NAME = "flying-rag-mcp"


def shared_file(relative: str) -> Path:
    """A file shipped with the code: beside it in a checkout, else in share/.

    An installed package (pip, uvx, an installer) has no repository around it;
    pyproject.toml puts these files under <environment>/share/flying-rag-mcp.
    The checkout location wins, so a working copy keeps using its own files.
    """
    import sys

    beside = ROOT / relative
    if beside.exists():
        return beside
    installed = Path(sys.prefix) / "share" / SHARED_DIR_NAME / relative
    return installed if installed.exists() else beside


def data_dir() -> Path:
    """The runtime's own files: logs, reports, backups next to the stores."""
    return home() / "data"


def log_dir() -> Path:
    """Server and reindex job logs; the folder name is kept from before."""
    return home() / "storage"


def load_config() -> dict:
    """Config as a dict; empty dict when absent or unreadable."""
    path = config_path()
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def require_config() -> dict:
    """Config for callers that cannot run without one."""
    path = config_path()
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
