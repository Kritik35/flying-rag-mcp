from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from storage.rules_maintenance import deduplicate_engineering_rules


def main() -> int:
    parser = argparse.ArgumentParser(description="Dry-run/apply deduplication for engineering_rules.")
    parser.add_argument("--db", default="data/metadata.db", help="SQLite metadata DB path")
    parser.add_argument("--apply", action="store_true", help="Actually delete duplicates; default is dry-run")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"Metadata DB not found: {db_path}")

    result = deduplicate_engineering_rules(db_path, apply=args.apply)
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"Mode: {mode}")
    print(f"Duplicate groups: {result['duplicate_groups']}")
    print(f"Duplicate rows: {result['duplicate_rows']}")
    print(f"Deleted rows: {result['deleted_rows']}")
    if not args.apply and result["duplicate_rows"]:
        print("No rows deleted. Re-run with --apply after backfill is complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
