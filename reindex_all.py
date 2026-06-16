from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).parent


def configure_process_io() -> None:
    """Keep Windows console output readable for Cyrillic paths."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def parse_reindex_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Re-index all configured watched folders.")
    parser.add_argument("--force", action="store_true", help="Ignore SHA skip for every file")
    parser.add_argument(
        "--no-cache",
        dest="use_cache",
        action="store_false",
        help="Recompute embeddings instead of reusing cached chunk vectors",
    )
    parser.add_argument(
        "--reset-store",
        action="store_true",
        help="Delete configured LanceDB data and metadata DB before indexing",
    )
    parser.set_defaults(use_cache=True)
    return parser.parse_args(argv)


def build_indexer_command(
    python_exe: str,
    indexer_script: str,
    folder_path: Path,
    force: bool = False,
    use_cache: bool = True,
) -> list[str]:
    command = [python_exe, indexer_script]
    if force:
        command.append("--force")
    if not use_cache:
        command.append("--no-cache")
    command.append(str(folder_path))
    return command


def load_config(root: Path = ROOT) -> dict:
    with open(root / "config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_folder_cooldown_sec(cfg: dict) -> float:
    return max(0.0, float(cfg.get("indexing", {}).get("folder_cooldown_sec", 0.0)))


def reset_store(cfg: dict, root: Path = ROOT) -> list[Path]:
    storage_cfg = cfg.get("storage", {})
    targets = [
        root / storage_cfg["lancedb_path"],
        root / storage_cfg["metadata_db"],
    ]
    removed: list[Path] = []

    for target in targets:
        resolved = target.resolve()
        if not resolved.exists():
            continue
        if resolved.is_dir():
            shutil.rmtree(resolved)
        else:
            resolved.unlink()
        removed.append(resolved)

    return removed


def run_folder_index(
    folder: str,
    idx: int,
    total: int,
    force: bool,
    use_cache: bool,
) -> int:
    folder_path = Path(folder)
    if not folder_path.exists():
        print(f"[{idx}/{total}] Skipping non-existing folder: {folder}", flush=True)
        return 0

    print(f"[{idx}/{total}] Indexing folder: {folder}", flush=True)
    env = os.environ.copy()
    env["NO_PROXY"] = "*"
    env["no_proxy"] = "*"
    env["PYTHONIOENCODING"] = "utf-8"

    process = subprocess.Popen(
        build_indexer_command(
            sys.executable,
            str(ROOT / "indexer.py"),
            folder_path,
            force=force,
            use_cache=use_cache,
        ),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        cwd=str(ROOT),
    )

    assert process.stdout is not None
    while True:
        line = process.stdout.readline()
        if not line and process.poll() is not None:
            break
        if line:
            print(f"  {line.strip()}", flush=True)

    rc = process.poll()
    if rc == 0:
        print(f"[{idx}/{total}] Successfully indexed: {folder}", flush=True)
    else:
        print(f"[{idx}/{total}] Failed to index: {folder} (Exit code {rc})", flush=True)
    return int(rc or 0)


def main(argv: list[str] | None = None) -> int:
    configure_process_io()
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"

    args = parse_reindex_args(argv)
    cfg = load_config()

    if args.reset_store:
        removed = reset_store(cfg)
        for path in removed:
            print(f"Removed store artifact: {path}", flush=True)

    folders = cfg.get("watched_folders", [])
    print(
        f"Starting re-indexing for {len(folders)} folders "
        f"(force={args.force}, cache={args.use_cache})...",
        flush=True,
    )

    failures = 0
    folder_cooldown_sec = get_folder_cooldown_sec(cfg)
    for idx, folder in enumerate(folders, 1):
        rc = run_folder_index(folder, idx, len(folders), args.force, args.use_cache)
        if rc != 0:
            failures += 1
        if folder_cooldown_sec > 0 and idx < len(folders):
            print(f"Cooling down for {folder_cooldown_sec:.1f}s before next folder...", flush=True)
            time.sleep(folder_cooldown_sec)

    print("All configured folders processed.", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
