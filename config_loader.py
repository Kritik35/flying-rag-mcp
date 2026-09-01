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
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
CONFIG_ENV = "FLYING_RAG_CONFIG"
DEFAULT_NAME = "config.yaml"


def config_path() -> Path:
    """Absolute path of the config file the runtime should use."""
    override = os.getenv(CONFIG_ENV, "").strip()
    if override:
        path = Path(override)
        return path if path.is_absolute() else (Path.cwd() / path)
    return ROOT / DEFAULT_NAME


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
