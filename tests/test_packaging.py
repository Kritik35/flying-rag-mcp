"""The package installs what the server needs, and a fresh home can be set up.

The server is a set of top-level modules and packages rather than one package,
so pyproject.toml lists them by hand; a module added to the repository and
forgotten there would install a server that fails on import.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config_loader  # noqa: E402


def _tracked() -> list[str]:
    return subprocess.run(["git", "ls-files"], cwd=str(ROOT), capture_output=True,
                          text=True, check=True).stdout.split()


class PyprojectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    def test_every_top_level_module_is_installed(self):
        modules = {Path(p).stem for p in _tracked() if "/" not in p and p.endswith(".py")}
        listed = set(self.cfg["tool"]["setuptools"]["py-modules"])
        self.assertEqual(modules - listed, set(), "modules missing from py-modules")
        self.assertEqual(listed - modules, set(), "py-modules that do not exist")

    def test_every_package_is_installed(self):
        packages = {p.split("/")[0] for p in _tracked()
                    if p.count("/") >= 1 and p.endswith(".py")}
        packages -= {"tests", "golden", "docs", ".github"}
        include = self.cfg["tool"]["setuptools"]["packages"]["find"]["include"]
        missing = {p for p in packages if not any(p == pat.rstrip("*") for pat in include)}
        self.assertEqual(missing, set())

    def test_entry_points_resolve(self):
        import importlib

        for name, target in self.cfg["project"]["scripts"].items():
            module, func = target.split(":")
            self.assertTrue(callable(getattr(importlib.import_module(module), func)), name)

    def test_shipped_data_files_exist(self):
        for files in self.cfg["tool"]["setuptools"]["data-files"].values():
            for rel in files:
                self.assertTrue((ROOT / rel).is_file(), rel)


class ReadmeToolsTests(unittest.TestCase):
    def test_every_tool_is_documented(self):
        from rag_server.tools import get_tool_definitions

        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        missing = [t["name"] for t in get_tool_definitions() if f"`{t['name']}(" not in readme]
        self.assertEqual(missing, [], "tools missing from the README table")


class SharedFileTests(unittest.TestCase):
    def test_checkout_copy_wins(self):
        self.assertEqual(config_loader.shared_file("config.example.yaml"),
                         ROOT / "config.example.yaml")

    def test_installed_copy_is_found_under_share(self):
        with tempfile.TemporaryDirectory() as code, tempfile.TemporaryDirectory() as prefix:
            shipped = Path(prefix) / "share" / "flying-rag-mcp" / "config" / "terms.yaml"
            shipped.parent.mkdir(parents=True)
            shipped.write_text("x", encoding="utf-8")
            with mock.patch.object(config_loader, "ROOT", Path(code)), \
                    mock.patch.object(sys, "prefix", prefix):
                self.assertEqual(config_loader.shared_file("config/terms.yaml"), shipped)


class InitHomeTests(unittest.TestCase):
    def _init(self, home: Path):
        env = {k: v for k, v in os.environ.items()
               if k not in (config_loader.HOME_ENV, config_loader.CONFIG_ENV)}
        return subprocess.run([sys.executable, str(ROOT / "main.py"), "--init", str(home)],
                              cwd=str(ROOT), env=env, stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, encoding="utf-8", timeout=120)

    def test_a_new_home_gets_config_data_and_a_client_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            out = self._init(home)
            self.assertEqual(out.returncode, 0, out.stderr[-2000:])
            self.assertEqual((home / "config.yaml").read_text(encoding="utf-8"),
                             (ROOT / "config.example.yaml").read_text(encoding="utf-8"))
            self.assertTrue((home / "data").is_dir())
            entry = json.loads(out.stdout)["mcpServers"]["flying-rag"]
            self.assertEqual(Path(entry["env"]["FLYING_RAG_HOME"]), home.resolve())

    def test_an_existing_config_is_left_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / "config.yaml").write_text("mine: true\n", encoding="utf-8")
            self.assertEqual(self._init(home).returncode, 0)
            self.assertEqual((home / "config.yaml").read_text(encoding="utf-8"), "mine: true\n")


if __name__ == "__main__":
    unittest.main()
