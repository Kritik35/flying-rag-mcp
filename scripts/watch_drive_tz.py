"""
scripts/watch_drive_tz.py

Background watcher for Google Drive FlyingRAG TZ Inbox (G:\\Мой диск\\FlyingRAG_TZ_Inbox).
Monitors for new technical assignment (ТЗ) files and updates to existing files.
Upon detecting a new or updated file:
- Computes SHA-256
- Reads the full text
- Logs arrival and summary to console and event log
- Updates persistent state JSON
"""

from __future__ import annotations
import os
import sys
import json
import time
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any

DEFAULT_INBOX_DIR = Path(r"G:\Мой диск\FlyingRAG_TZ_Inbox")
DEFAULT_STATE_FILE = Path(r"C:\Acer_System_Audit\rag_quality_ab_20261113\05_drive_watcher\tz_inbox_monitor_state.json")
DEFAULT_LOG_FILE = Path(r"C:\Acer_System_Audit\rag_quality_ab_20261113\05_drive_watcher\tz_inbox_events.log")


def compute_sha256(file_path: Path) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def read_file_safe(file_path: Path) -> str:
    for enc in ("utf-8", "utf-8-sig", "cp1251"):
        try:
            with open(file_path, "r", encoding=enc) as f:
                return f.read()
        except Exception:
            continue
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


class DriveTZWatcher:
    def __init__(
        self,
        inbox_dir: Path = DEFAULT_INBOX_DIR,
        state_file: Path = DEFAULT_STATE_FILE,
        log_file: Path = DEFAULT_LOG_FILE
    ):
        self.inbox_dir = inbox_dir
        self.state_file = state_file
        self.log_file = log_file
        self.known_files: Dict[str, Dict[str, Any]] = self._load_state()

    def _load_state(self) -> Dict[str, Dict[str, Any]]:
        if self.state_file.exists():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("tracked_files", {})
            except Exception as e:
                self.log(f"[WARN] Failed to load state from {self.state_file}: {e}")
        return {}

    def _save_state(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            state_data = {
                "version": "1.0.0",
                "last_poll_utc": datetime.now(timezone.utc).isoformat(),
                "inbox_dir": str(self.inbox_dir),
                "tracked_files_count": len(self.known_files),
                "tracked_files": self.known_files
            }
            tmp = self.state_file.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(state_data, f, indent=2, ensure_ascii=False)
            if tmp.exists():
                tmp.replace(self.state_file)
        except Exception as e:
            self.log(f"[ERROR] Failed to save state to {self.state_file}: {e}")

    def log(self, message: str):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        line = f"[{now}] {message}"
        print(line, flush=True)
        try:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

    def poll_once(self) -> list[Dict[str, Any]]:
        events = []
        if not self.inbox_dir.exists():
            self.log(f"[WARN] Inbox directory not accessible: {self.inbox_dir}")
            return events

        for p in self.inbox_dir.glob("*.txt"):
            if not p.is_file():
                continue
            name = p.name
            try:
                st = p.stat()
                mtime = st.st_mtime
                size = st.st_size
            except Exception as e:
                self.log(f"[WARN] Failed to stat {name}: {e}")
                continue

            prev = self.known_files.get(name)
            is_new = prev is None
            is_modified = False

            if prev:
                if prev.get("size") != size or abs(prev.get("mtime", 0) - mtime) > 1.0:
                    is_modified = True

            if is_new or is_modified:
                try:
                    sha = compute_sha256(p)
                except Exception as e:
                    self.log(f"[ERROR] Failed to hash {name}: {e}")
                    continue

                if prev and prev.get("sha256") == sha:
                    # Content unchanged despite mtime jitter
                    continue

                event_type = "NEW_FILE" if is_new else "FILE_UPDATED"
                content = read_file_safe(p)
                lines = content.splitlines()
                header_preview = "\n".join(lines[:10])

                event = {
                    "event": event_type,
                    "filename": name,
                    "path": str(p),
                    "size_bytes": size,
                    "sha256": sha,
                    "lines_count": len(lines),
                    "header_preview": header_preview,
                    "detected_at": datetime.now(timezone.utc).isoformat()
                }
                events.append(event)

                self.log(f"[{event_type}] {name} ({size} bytes, SHA-256: {sha[:16]}...)")
                self.log(f"--- Header preview of {name} ---\n{header_preview}\n----------------------------")

                self.known_files[name] = {
                    "filename": name,
                    "size": size,
                    "mtime": mtime,
                    "sha256": sha,
                    "last_seen_utc": datetime.now(timezone.utc).isoformat()
                }

        if events:
            self._save_state()
        return events

    def run_daemon(self, poll_interval_sec: float = 5.0):
        self.log(f"Starting Drive TZ Watcher Daemon (Inbox: {self.inbox_dir}, Interval: {poll_interval_sec}s)...")
        # Initial scan
        self.poll_once()
        while True:
            try:
                time.sleep(poll_interval_sec)
                self.poll_once()
            except KeyboardInterrupt:
                self.log("Drive TZ Watcher Daemon stopped by keyboard interrupt.")
                break
            except Exception as e:
                self.log(f"[ERROR] Exception in watcher loop: {e}")
                time.sleep(2.0)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Google Drive FlyingRAG TZ Inbox Watcher")
    parser.add_argument("--daemon", action="store_true", default=False, help="Run as continuous daemon")
    parser.add_argument("--interval", type=float, default=5.0, help="Polling interval in seconds")
    parser.add_argument("--poll-once", action="store_true", default=False, help="Poll once and exit")
    args = parser.parse_args()

    watcher = DriveTZWatcher()
    if args.poll_once or not args.daemon:
        events = watcher.poll_once()
        print(json.dumps({"poll_completed": True, "new_events_count": len(events), "events": events}, indent=2, ensure_ascii=False))
        sys.exit(0)
    else:
        watcher.run_daemon(poll_interval_sec=args.interval)


if __name__ == "__main__":
    main()
