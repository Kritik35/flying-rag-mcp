"""FLYING_RAG_HOME: config and data live apart from the code.

An installed package puts the code where the operator's index cannot live —
site-packages, a uvx cache, a folder the next upgrade replaces. Every path the
runtime reads or writes must therefore come from one resolver, and without the
variable nothing may change for an existing checkout.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config_loader  # noqa: E402


def _env(**values: str) -> dict:
    env = {k: v for k, v in os.environ.items()
           if k not in (config_loader.HOME_ENV, config_loader.CONFIG_ENV)}
    env.update(values)
    return env


class HomeResolution(unittest.TestCase):
    def test_unset_home_is_the_code_folder(self):
        with mock.patch.dict(os.environ, _env(), clear=True):
            self.assertEqual(config_loader.home(), config_loader.ROOT)
            self.assertEqual(config_loader.config_path(), config_loader.ROOT / "config.yaml")
            self.assertEqual(config_loader.resolve("data/lancedb"),
                             config_loader.ROOT / "data" / "lancedb")

    def test_home_owns_config_and_relative_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, _env(FLYING_RAG_HOME=tmp), clear=True):
                home = Path(tmp)
                self.assertEqual(config_loader.home(), home)
                self.assertEqual(config_loader.config_path(), home / "config.yaml")
                self.assertEqual(config_loader.resolve("data/metadata.db"),
                                 home / "data" / "metadata.db")
                self.assertEqual(config_loader.data_dir(), home / "data")
                self.assertEqual(config_loader.log_dir(), home / "storage")

    def test_absolute_paths_are_kept_as_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            absolute = Path(tmp) / "elsewhere" / "lancedb"
            with mock.patch.dict(os.environ, _env(FLYING_RAG_HOME=tmp), clear=True):
                self.assertEqual(config_loader.resolve(str(absolute)), absolute)

    def test_explicit_config_wins_but_data_stays_in_home(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as other:
            cfg = Path(other) / "probe.yaml"
            with mock.patch.dict(os.environ, _env(FLYING_RAG_HOME=home,
                                                  FLYING_RAG_CONFIG=str(cfg)), clear=True):
                self.assertEqual(config_loader.config_path(), cfg)
                self.assertEqual(config_loader.resolve("data/x"), Path(home) / "data" / "x")

    def test_config_is_read_from_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "config.yaml").write_text("storage:\n  metadata_db: data/m.db\n",
                                                   encoding="utf-8")
            with mock.patch.dict(os.environ, _env(FLYING_RAG_HOME=tmp), clear=True):
                self.assertEqual(config_loader.load_config()["storage"]["metadata_db"], "data/m.db")

    def test_store_paths_of_the_server_follow_home(self):
        """The server's store pair comes from the home, not from the code folder."""
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "config.yaml").write_text(
                "storage:\n  lancedb_path: data/lancedb\n  metadata_db: data/metadata.db\n",
                encoding="utf-8")
            code = ("from rag_server import tools; l, m = tools._db_paths(); "
                    "print(l); print(m)")
            out = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT),
                                 env=_env(FLYING_RAG_HOME=tmp), stdin=subprocess.DEVNULL,
                                 capture_output=True, text=True, timeout=120)
            self.assertEqual(out.returncode, 0, out.stderr[-2000:])
            lance, meta = out.stdout.strip().splitlines()[-2:]
            self.assertEqual(Path(lance), Path(tmp) / "data" / "lancedb")
            self.assertEqual(Path(meta), Path(tmp) / "data" / "metadata.db")


class NoPathsBuiltFromTheCodeFolder(unittest.TestCase):
    """Config, data and logs are the operator's; ROOT is only where code sits."""

    PATTERN = re.compile(
        r"ROOT\s*/\s*(cfg|cfg_now|storage_cfg|_cfg\(\)|db_name|\"data\"|'data'|"
        r"\"config\.yaml\"|'config\.yaml'|\"storage\"|'storage')"
    )

    def test_runtime_modules_use_the_resolver(self):
        tracked = subprocess.run(["git", "ls-files", "*.py"], cwd=str(ROOT),
                                 capture_output=True, text=True, check=True).stdout.split()
        offenders = []
        for rel in tracked:
            if rel.startswith("tests/") or rel == "config_loader.py":
                continue
            text = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
            for n, line in enumerate(text.splitlines(), 1):
                # Backticked code in docstrings records what used to stand here.
                code = re.sub(r"`[^`]*`", "", line.split("#", 1)[0])
                if self.PATTERN.search(code):
                    offenders.append(f"{rel}:{n}: {line.strip()}")
        self.assertEqual(offenders, [], "\n".join(offenders))


if __name__ == "__main__":
    unittest.main()
