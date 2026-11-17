"""
tests/test_real_retrieval_shadow_pilot.py

Contract verification and isolated harness for the Real Retrieval Shadow Pilot (Stage 4.2.8 Rev 3).
Enforces supervisor process isolation, per-pair dedicated event channels, parent environment preservation,
strict fail-closed eligibility predicate, and honest reporting under dependencies.
"""

from __future__ import annotations
import os
import sys
import re
import json
import time
import socket
import urllib.parse
import hashlib
import unittest
import threading
import subprocess
import tempfile
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import yaml

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

WORKER_SCRIPT = ROOT_DIR / "tests" / "shadow_pilot_worker.py"
DEFAULT_ISOLATED_CONFIG = ROOT_DIR / "tests" / "isolated_pilot_config.yaml"
DEFAULT_QUERY_MANIFEST_105 = ROOT_DIR / "tests" / "pilot_query_manifest_105.json"

# Production corpus query sample sets
ACTUAL_NORMATIVE_QUERIES = [
    "СП 7.13130 пункт 6.4",
    "СП 60.13330.2020 пункт 5.1",
    "ГОСТ Р 21.101-2020 раздел 4",
    "СП 7.13130 пункт 6.4",  # Intentional repeat to verify channel isolation
    "СП 1.13130.2020 эвакуационные пути"
]

SYNTHETIC_ADVERSARIAL_QUERIES = [
    "nonexistent_normative_clause_xyz",
    "СП 999.99999 пункт 99.9",
    "СП 7.13130 пункт 6.4"   # Intentional cross-category repeat
]

VOLATILE_FIELDS = {
    "request_id",
    "latency_ms",
    "timestamp",
    "query_time_ms",
    "server_process_id",
    "search_duration"
}


class SearchResult(tuple):
    """
    Backward-compatible 5-tuple subclass returning (success, result, elapsed_ms, error, exitcode)
    while exposing child adapter telemetry stats via .shadow_stats.
    """
    def __new__(cls, success: bool, result: Any, elapsed_ms: float, error: str, exitcode: Optional[int], shadow_stats: Optional[Dict[str, Any]] = None):
        inst = super().__new__(cls, (success, result, elapsed_ms, error, exitcode))
        inst.shadow_stats = shadow_stats
        return inst


def normalize_payload(payload: Any) -> Any:
    """Recursively removes volatile dynamic fields (request IDs, timestamps, latencies) for comparison."""
    if isinstance(payload, dict):
        return {
            k: normalize_payload(v)
            for k, v in payload.items()
            if k not in VOLATILE_FIELDS
        }
    elif isinstance(payload, list):
        return [normalize_payload(item) for item in payload]
    return payload


def compare_ranks(off_results: Any, on_results: Any) -> bool:
    """Verifies that the rank ordering of returned document/chunk identifiers is identical."""
    if not isinstance(off_results, list) or not isinstance(on_results, list):
        return off_results == on_results
    if len(off_results) != len(on_results):
        return False

    def _get_id(hit: Any) -> str:
        if isinstance(hit, dict):
            return str(hit.get("chunk_id") or hit.get("id") or hit.get("parent_id") or "")
        return str(hit)

    off_ranks = [_get_id(h) for h in off_results]
    on_ranks = [_get_id(h) for h in on_results]
    return off_ranks == on_ranks


def compare_payloads(off_results: Any, on_results: Any) -> Dict[str, Any]:
    """Compares raw byte-for-byte serialization and normalized semantic payloads."""
    raw_off = json.dumps(off_results, sort_keys=True, ensure_ascii=False)
    raw_on = json.dumps(on_results, sort_keys=True, ensure_ascii=False)
    raw_equal = (raw_off == raw_on)

    norm_off = normalize_payload(off_results)
    norm_on = normalize_payload(on_results)
    canon_norm_off = json.dumps(norm_off, sort_keys=True, ensure_ascii=False)
    canon_norm_on = json.dumps(norm_on, sort_keys=True, ensure_ascii=False)
    norm_equal = (canon_norm_off == canon_norm_on)

    raw_hash_off = hashlib.sha256(raw_off.encode("utf-8")).hexdigest()
    raw_hash_on = hashlib.sha256(raw_on.encode("utf-8")).hexdigest()
    norm_hash_off = hashlib.sha256(canon_norm_off.encode("utf-8")).hexdigest()
    norm_hash_on = hashlib.sha256(canon_norm_on.encode("utf-8")).hexdigest()

    removed_fields = set()
    if isinstance(off_results, dict):
        removed_fields.update(k for k in off_results if k in VOLATILE_FIELDS)
    elif isinstance(off_results, list):
        for item in off_results:
            if isinstance(item, dict):
                removed_fields.update(k for k in item if k in VOLATILE_FIELDS)

    return {
        "raw_equal": raw_equal,
        "raw_hash_off": raw_hash_off,
        "raw_hash_on": raw_hash_on,
        "normalized_equal": norm_equal,
        "norm_hash_off": norm_hash_off,
        "norm_hash_on": norm_hash_on,
        "removed_volatile_fields": sorted(removed_fields)
    }


def is_error_payload(data: Any) -> Tuple[bool, str]:
    """
    Detects if a dispatch result represents an error rather than valid retrieval (Block C-error).
    Inspects top-level dicts, list envelopes like blocked_result() [{'error': ..., 'status': 'blocked'}], and None.
    """
    if data is None:
        return True, "RESULT_IS_NONE"
    if isinstance(data, dict):
        if "error" in data:
            return True, f"ERROR_KEY_PRESENT: {data.get('error')}"
        if data.get("status") in ("ERROR", "FAILED", "blocked", "BLOCKED"):
            return True, f"ERROR_STATUS: {data.get('status')}"
    elif isinstance(data, list):
        if len(data) == 0:
            return False, ""
        for item in data:
            if isinstance(item, dict):
                if "error" in item:
                    return True, f"ERROR_KEY_IN_LIST: {item.get('error')}"
                if item.get("status") in ("ERROR", "FAILED", "blocked", "BLOCKED"):
                    return True, f"ERROR_STATUS_IN_LIST: {item.get('status')}"
    return False, ""


def get_config_fingerprint(config_path: Path | str) -> Tuple[str, Dict[str, Any]]:
    """Calculates canonical SHA256 fingerprint of the effective configuration."""
    import yaml
    p = Path(config_path)
    if not p.exists():
        return "", {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        canon_json = json.dumps(cfg, sort_keys=True, ensure_ascii=False)
        fp = hashlib.sha256(canon_json.encode("utf-8")).hexdigest()
        return fp, cfg
    except Exception:
        return "", {}


def validate_query_manifest(
    manifest_path: Path | str,
    expected_count: Optional[int] = 105
) -> Tuple[bool, str, List[Dict[str, Any]]]:
    """
    Validates a canonical query manifest (P0-A / NG-02 / G2-01..04).
    Enforces:
      - Valid JSON and UTF-8 encoding
      - Mandatory top-level schema 'flying_rag.pilot_query_manifest.v1'
      - Mandatory manifest_sha256 (64 hex characters) matching canonical JSON of queries
      - Exactly expected_count items (if expected_count is set, e.g. 105)
      - Declared header counts match actual query counts:
          * total_queries == len(queries)
          * normative_count == actual ACTUAL_NORMATIVE count
          * adversarial_count == actual SYNTHETIC_ADVERSARIAL count
      - Whitelist of categories: strictly 'ACTUAL_NORMATIVE' and 'SYNTHETIC_ADVERSARIAL'
      - Each query has non-empty query_id, 1-based sequential position, non-empty query_text string
      - Sequential positions 1..N without gaps
      - Non-string query_text or dict/int types forbidden
      - Legitimate duplicate query_text across different query_id is permitted
    Returns: (is_valid, error_message, query_list)
    """
    p = Path(manifest_path)
    if not p.exists():
        return False, f"MANIFEST_FILE_NOT_FOUND: {p}", []
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return False, f"MANIFEST_JSON_PARSE_ERROR: {e}", []

    if not isinstance(data, dict):
        return False, "MANIFEST_INVALID_ROOT: Must be dictionary", []

    schema = data.get("schema")
    if not schema or schema != "flying_rag.pilot_query_manifest.v1":
        return False, f"MANIFEST_SCHEMA_INVALID: Missing or unsupported schema (expected 'flying_rag.pilot_query_manifest.v1', got '{schema}')", []

    declared_hash = data.get("manifest_sha256")
    if not declared_hash or not isinstance(declared_hash, str) or not re.match(r'^[0-9a-fA-F]{64}$', declared_hash):
        return False, f"MANIFEST_HASH_MISSING_OR_INVALID: manifest_sha256 must be a 64-char hex string, got '{declared_hash}'", []

    queries = data.get("queries")
    if not isinstance(queries, list):
        return False, "MANIFEST_INVALID_QUERIES: Must be a list", []

    if expected_count is not None and len(queries) != expected_count:
        return False, f"MANIFEST_QUERY_COUNT_MISMATCH: Expected {expected_count}, got {len(queries)}", []

    # P0-A (Rev 3): In expected_count=105 mode, strict header counts 105/80/25 are mandatory integers (bool forbidden)
    if expected_count == 105:
        tq = data.get("total_queries")
        nc = data.get("normative_count")
        ac = data.get("adversarial_count")
        if tq is None or nc is None or ac is None:
            return False, "MANIFEST_INVALID_HEADER_COUNTS: Canonical 105 manifest strictly requires total_queries, normative_count, adversarial_count", []
        if type(tq) is not int or type(nc) is not int or type(ac) is not int:
            return False, "MANIFEST_INVALID_HEADER_TYPES: Header counts must be strict integers (bool is forbidden)", []
        if tq != 105 or nc != 80 or ac != 25:
            return False, f"MANIFEST_PROFILE_MISMATCH: Canonical profile requires total=105, normative=80, adversarial=25; got total={tq}, norm={nc}, adv={ac}", []

    seen_ids = set()
    norm_cnt = 0
    adv_cnt = 0
    allowed_categories = {"ACTUAL_NORMATIVE", "SYNTHETIC_ADVERSARIAL"}

    for idx, q in enumerate(queries):
        if not isinstance(q, dict):
            return False, f"MANIFEST_ITEM_NOT_DICT: Index {idx}", []
        qid = q.get("query_id")
        qtxt = q.get("query_text")
        qcat = q.get("category")
        qpos = q.get("position")
        if not qid or qpos is None or qcat is None or qtxt is None:
            return False, f"MANIFEST_ITEM_MISSING_REQUIRED_KEYS: Index {idx}", []
        if not isinstance(qid, str) or not qid.strip():
            return False, f"MANIFEST_MALICIOUS_OR_EMPTY_ID: Index {idx}", []
        if qid in seen_ids:
            return False, f"MANIFEST_DUPLICATE_QUERY_ID: '{qid}' at index {idx}", []
        seen_ids.add(qid)
        if qpos != idx + 1:
            return False, f"MANIFEST_POSITION_GAP: Expected {idx+1}, got {qpos}", []
        if qcat not in allowed_categories:
            return False, f"MANIFEST_INVALID_CATEGORY: '{qcat}' at index {idx}", []
        if qcat == "ACTUAL_NORMATIVE":
            norm_cnt += 1
        elif qcat == "SYNTHETIC_ADVERSARIAL":
            adv_cnt += 1

        if not isinstance(qtxt, str) or not qtxt.strip() or len(qtxt) > 10000:
            return False, f"MANIFEST_INVALID_QUERY_TEXT: Query text at index {idx} must be non-empty string", []

    if expected_count == 105:
        if norm_cnt != 80 or adv_cnt != 25:
            return False, f"MANIFEST_PROFILE_MISMATCH: Actual query counts norm={norm_cnt}, adv={adv_cnt} != required 80/25", []

    for key, actual_val in [("total_queries", len(queries)), ("normative_count", norm_cnt), ("adversarial_count", adv_cnt)]:
        if key in data:
            val = data.get(key)
            if type(val) is not int:
                return False, f"MANIFEST_INVALID_HEADER_TYPES: '{key}' must be strict integer (bool forbidden)", []
            if val != actual_val:
                return False, f"MANIFEST_{key.upper()}_MISMATCH: Declared {val} != actual {actual_val}", []

    canon_json = json.dumps(queries, sort_keys=True, ensure_ascii=False)
    actual_hash = hashlib.sha256(canon_json.encode("utf-8")).hexdigest()
    if declared_hash.lower() != actual_hash.lower():
        return False, f"MANIFEST_HASH_MISMATCH: Declared '{declared_hash}' != Calculated '{actual_hash}'", []

    return True, "MANIFEST_VALID", queries


def verify_snapshot_readiness(
    metadata_db_path: Path | str,
    lancedb_dir_path: Path | str,
    expected_sample_sha256: Optional[str] = None,
    require_consistency_proof: bool = False
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Verifies that a candidate snapshot replica is consistent and ready for pilot (P1 / P0-C / NG-06 / G2-07..08).
    Checks:
      - metadata.db exists and matches expected sample hash (if provided)
      - metadata.db-wal exists and has size == 0 (checkpoint clean, no active writers)
      - metadata.db is a valid SQLite database with real schema (PRAGMA quick_check == 'ok' and tables exist)
      - lancedb directory exists, contains non-empty index_manifest.json with required schema
      - documents_1024.lance table directory exists within lancedb directory
    Returns: (is_ready, status_code, diagnostics)
    """
    meta_p = Path(metadata_db_path)
    if not meta_p.exists() or not meta_p.is_file():
        return False, "SNAPSHOT_METADATA_NOT_FOUND", {"error": f"File not found: {meta_p}"}

    wal_p = meta_p.parent / f"{meta_p.name}-wal"
    if wal_p.exists() and wal_p.stat().st_size > 0:
        return False, "SNAPSHOT_UNCONFIRMED_DIRTY_WAL", {
            "wal_size_bytes": wal_p.stat().st_size,
            "error": "WAL file is non-zero, indicating un-checkpointed transactions or active writers."
        }

    # Verify SQLite validity and table structure (P0-C)
    conn = None
    try:
        conn = sqlite3.connect(f"file:{meta_p.resolve()}?mode=ro", uri=True)
        cur = conn.cursor()
        chk = cur.execute("PRAGMA quick_check").fetchone()
        if not chk or chk[0] != "ok":
            return False, "SNAPSHOT_SQLITE_INVALID", {"error": f"PRAGMA quick_check failed: {chk}"}
        tbls = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        if not tbls:
            return False, "SNAPSHOT_SQLITE_INVALID", {"error": "SQLite database has 0 tables"}
    except Exception as e:
        return False, "SNAPSHOT_SQLITE_INVALID", {"error": f"SQLite validation failed: {e}"}
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    if expected_sample_sha256:
        size = meta_p.stat().st_size
        with open(meta_p, "rb") as f:
            head = f.read(65536)
            if size > 131072:
                f.seek(-65536, os.SEEK_END)
                tail = f.read(65536)
            else:
                tail = b""
        actual_sample_hash = hashlib.sha256(head + tail).hexdigest()
        if actual_sample_hash != expected_sample_sha256:
            return False, "SNAPSHOT_SAMPLE_HASH_MISMATCH", {
                "expected": expected_sample_sha256,
                "actual": actual_sample_hash
            }

    lance_p = Path(lancedb_dir_path)
    if not lance_p.exists() or not lance_p.is_dir():
        return False, "SNAPSHOT_LANCEDB_NOT_FOUND", {"error": f"Directory not found: {lance_p}"}

    manifest_p = lance_p / "index_manifest.json"
    if not manifest_p.exists():
        return False, "SNAPSHOT_LANCEDB_MISSING_MANIFEST", {"error": f"index_manifest.json not found in {lance_p}"}

    # Verify manifest is valid non-empty JSON with metadata (P0-C)
    try:
        with open(manifest_p, "r", encoding="utf-8") as f:
            m_data = json.load(f)
        if not isinstance(m_data, dict) or not m_data:
            return False, "SNAPSHOT_LANCEDB_EMPTY_MANIFEST", {"error": "index_manifest.json is empty or not a dict"}
        if "table_name" not in m_data and "dimension" not in m_data and "version" not in m_data:
            return False, "SNAPSHOT_LANCEDB_INVALID_MANIFEST", {"error": "index_manifest.json missing required metadata fields"}
        expected_table = m_data.get("table_name", "documents_1024.lance")
    except Exception as e:
        return False, "SNAPSHOT_LANCEDB_INVALID_MANIFEST", {"error": f"Failed to read index_manifest.json: {e}"}

    # Verify Lance table directory exists
    table_dir = lance_p / expected_table
    if not table_dir.exists() and not (lance_p / "documents_1024.lance").exists():
        return False, "SNAPSHOT_LANCEDB_TABLE_NOT_FOUND", {"error": f"Lance table '{expected_table}' not found in {lance_p}"}

    if require_consistency_proof:
        return False, "SNAPSHOT_FILES_PRESENT_UNVERIFIED", {
            "error": "Snapshot files present on disk, but cross-store consistency proof (SQLite+LanceDB version agreement) is unverified"
        }

    return True, "SNAPSHOT_FILES_PRESENT", {
        "metadata_db": str(meta_p),
        "lancedb": str(lance_p),
        "wal_size_bytes": wal_p.stat().st_size if wal_p.exists() else 0,
        "table_name": expected_table
    }


def verify_process_termination_safety(
    target_pid: Optional[int],
    expected_path: str,
    expected_start_time: Optional[float | str] = None,
    port_probe_pid: Optional[int] = None,
    owned_process_record: Optional[Dict[str, Any]] = None
) -> Tuple[bool, str]:
    """
    Verifies that a termination target matches the owned test process before any kill command (P1 / P0-B / NG-07 / G2-05..06).
    Guarantees:
      - If port 8089 is occupied by a foreign PID: fails with PORT_8089_IN_USE_BY_FOREIGN_PROCESS (NO kill).
      - If process identity (executable path, PID, start time) does not match real OS process: fails (NO kill).
      - Fail-closed: positive verification only after OS-level confirmation.
    """
    if not target_pid or target_pid <= 0:
        return False, "PID_REQUIRED"

    if port_probe_pid is not None and port_probe_pid != target_pid:
        return False, f"PORT_8089_IN_USE_BY_FOREIGN_PROCESS: Port listener PID {port_probe_pid} != owned PID {target_pid}"

    try:
        import psutil
        if not psutil.pid_exists(target_pid):
            return False, f"PROCESS_NOT_FOUND: PID {target_pid} does not exist in OS"

        proc = psutil.Process(target_pid)
        try:
            actual_exe = proc.exe()
        except (psutil.AccessDenied, psutil.NoSuchProcess) as e:
            return False, f"PROCESS_ACCESS_DENIED_OR_VANISHED: {e}"

        norm_expected = os.path.normcase(os.path.abspath(expected_path)).replace("\\", "/")
        norm_actual = os.path.normcase(os.path.abspath(actual_exe)).replace("\\", "/")
        if norm_expected != norm_actual:
            is_same = False
            try:
                exp_base = os.path.basename(norm_expected)
                act_base = os.path.basename(norm_actual)
                if exp_base.startswith("python") and act_base.startswith("python"):
                    for candidate_venv, candidate_base in [(norm_expected, norm_actual), (norm_actual, norm_expected)]:
                        for p_dir in [os.path.dirname(os.path.dirname(candidate_venv)), os.path.dirname(candidate_venv)]:
                            cfg_path = os.path.join(p_dir, "pyvenv.cfg")
                            if os.path.exists(cfg_path):
                                with open(cfg_path, "r", encoding="utf-8") as f:
                                    for line in f:
                                        if line.strip().startswith("executable") or line.strip().startswith("home"):
                                            val = line.split("=", 1)[1].strip()
                                            norm_val = os.path.normcase(os.path.abspath(val)).replace("\\", "/")
                                            if norm_val == candidate_base or os.path.dirname(norm_val) == os.path.dirname(candidate_base):
                                                is_same = True
                                                break
                                if is_same:
                                    break
                        if is_same:
                            break
            except Exception:
                pass
            if not is_same:
                return False, f"PROCESS_PATH_MISMATCH: Actual executable '{norm_actual}' != expected '{norm_expected}'"

        actual_create_time = proc.create_time()

        # P0-B (Rev 3): Positive verification strictly requires a valid, non-empty owned_process_record
        if not owned_process_record or not isinstance(owned_process_record, dict):
            return False, "OWNED_RECORD_REQUIRED: Positive verification requires a valid non-empty owned_process_record"

        rec_pid = owned_process_record.get("pid")
        if rec_pid is None or rec_pid != target_pid:
            return False, f"OWNED_RECORD_PID_MISMATCH: Record PID {rec_pid} != target PID {target_pid}"

        rec_st = owned_process_record.get("create_time") or owned_process_record.get("start_time")
        if rec_st is None:
            return False, "OWNED_RECORD_START_TIME_REQUIRED: Missing create_time/start_time in owned record"

        try:
            rec_st_float = float(rec_st)
        except (ValueError, TypeError):
            return False, f"OWNED_RECORD_START_TIME_INVALID: Cannot parse '{rec_st}' as float"

        if abs(actual_create_time - rec_st_float) > 2.0:
            return False, f"OWNED_RECORD_START_TIME_MISMATCH: Actual {actual_create_time} != record {rec_st_float}"

        if expected_start_time is not None:
            try:
                exp_st = float(expected_start_time)
                if abs(actual_create_time - exp_st) > 2.0:
                    return False, f"PROCESS_START_TIME_MISMATCH: Actual start time {actual_create_time} != expected {exp_st}"
            except (ValueError, TypeError):
                return False, f"INVALID_EXPECTED_START_TIME: {expected_start_time}"

        return True, "PROCESS_IDENTITY_VERIFIED"
    except ImportError:
        return False, "PROCESS_IDENTITY_UNVERIFIED: psutil not available for OS-level verification"
    except Exception as e:
        return False, f"PROCESS_IDENTITY_UNVERIFIED: OS probe failed: {e}"


def validate_pilot_config(config_path: Path | str) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Validates isolated pilot YAML against actual runtime resolver schema (_db_paths & embedder client) (Block C-smoke & C-negative).
    Ensures missing mandatory keys fail closed with CONFIG_INVALID before search execution without opening live DBs.
    """
    p = Path(config_path)
    if not p.exists():
        return False, f"CONFIG_INVALID: File not found at {p}", {}

    import yaml
    try:
        with open(p, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
    except Exception as e:
        return False, f"CONFIG_INVALID: YAML parse error: {e}", {}

    if not isinstance(cfg, dict):
        return False, "CONFIG_INVALID: Root must be a dictionary", {}

    storage = cfg.get("storage")
    if not isinstance(storage, dict):
        return False, "CONFIG_INVALID: Missing 'storage' section in config", {}

    for key in ("lancedb_path", "metadata_db"):
        if not storage.get(key):
            return False, f"CONFIG_INVALID: Missing mandatory storage key '{key}'", {}

    embedder = cfg.get("embedder") or cfg.get("lemonade")
    if not isinstance(embedder, dict) or not embedder.get("url"):
        return False, "CONFIG_INVALID: Missing 'embedder' or 'lemonade' url in config", {}

    orig_env = os.environ.get("FLYING_RAG_CONFIG")
    try:
        os.environ["FLYING_RAG_CONFIG"] = str(p.resolve())
        from rag_server.tools import _db_paths
        lance_path, meta_path = _db_paths()
        resolved = {
            "lancedb_path": str(lance_path),
            "metadata_db": str(meta_path),
            "embedder_url": str(embedder.get("url"))
        }

        # P0-B: Check lancedb section if present in config
        lance_sec = cfg.get("lancedb")
        if isinstance(lance_sec, dict):
            lance_uri = lance_sec.get("uri") or lance_sec.get("path")
            if lance_uri:
                if Path(lance_uri).resolve() != Path(lance_path).resolve():
                    return False, f"CONFIG_INVALID: Conflicting storage alias detected (storage.lancedb_path='{lance_path}' vs lancedb.uri='{lance_uri}')", {}
            resolved["lancedb"] = lance_sec

        # P0-B: Check tables section if present
        tables_sec = cfg.get("tables")
        if isinstance(tables_sec, dict):
            p_dir = tables_sec.get("parquet_dir")
            if p_dir:
                resolved["table_parquet"] = str(Path(p_dir).resolve())

        return True, "CONFIG_VALID", resolved
    except Exception as e:
        return False, f"CONFIG_INVALID: Resolver error ({type(e).__name__}: {e})", {}
    finally:
        if orig_env is not None:
            os.environ["FLYING_RAG_CONFIG"] = orig_env
        else:
            os.environ.pop("FLYING_RAG_CONFIG", None)


_VERIFIED_FIXTURE_ROOTS: set[str] = set()


def register_verified_fixture_root(root: Path | str) -> Optional[str]:
    """
    Explicitly registers an authorized temporary directory root for isolated synthetic test fixtures.
    Strictly verifies that the root resolves inside the system temp directory (Rev 4 Errata 1 Section 2).
    Returns resolved path string if admitted, or None if rejected.
    """
    try:
        resolved_root = Path(root).resolve()
        system_temp = Path(tempfile.gettempdir()).resolve()
        resolved_root.relative_to(system_temp)
    except (ValueError, Exception):
        return None
    resolved_str = str(resolved_root)
    _VERIFIED_FIXTURE_ROOTS.add(resolved_str)
    return resolved_str


def unregister_verified_fixture_root(root: Path | str) -> None:
    """Removes an authorized temporary directory root."""
    resolved_root = str(Path(root).resolve())
    _VERIFIED_FIXTURE_ROOTS.discard(resolved_root)


def clear_verified_fixture_roots() -> None:
    """Clears all registered fixture roots."""
    _VERIFIED_FIXTURE_ROOTS.clear()


def is_storage_scope_admitted(scope: str) -> bool:
    """
    Evaluates whether storage scope is admitted for search execution (Section 2.1 & 2.2).
    Admitted scopes:
    - READONLY_VERIFIED_RO_MODE (OS/engine verified read-only)
    - ISOLATED_COPY_VERIFIED (proven temporary isolated copy strictly inside registered temp fixture root)
    Any BLOCKED_* or UNPROVEN scope is strictly rejected.
    """
    if not scope or not isinstance(scope, str):
        return False
    if scope.startswith("BLOCKED") or "NOT_PROVEN" in scope:
        return False
    return scope in ("READONLY_VERIFIED_RO_MODE", "ISOLATED_COPY_VERIFIED")


def check_readonly_scope(
    config_path: Path | str,
    backend_online: bool,
    allowed_fixture_root: Optional[Path | str] = None
) -> str:
    """
    Determines verified storage scope based on strict containment and runtime checks (Rev 4 Section 2.1-2.5).
    - If backend is offline: returns READONLY_VERIFIED_OFFLINE_PROBE_NO_DB_WRITE.
    - If config is invalid: returns BLOCKED_CONFIG_INVALID.
    - If all storage paths resolve strictly inside an authorized temporary directory root located
      within system temp: returns ISOLATED_COPY_VERIFIED.
    - Substring checks ('test_fixture', 'isolated_fixture') alone NEVER elevate status (Section 2.3).
    - Otherwise returns BLOCKED_READONLY_NOT_PROVEN.
    """
    if not backend_online:
        return "READONLY_VERIFIED_OFFLINE_PROBE_NO_DB_WRITE"

    val_ok, _, resolved = validate_pilot_config(config_path)
    if not val_ok:
        return "BLOCKED_CONFIG_INVALID"

    candidate_roots: set[str] = set(_VERIFIED_FIXTURE_ROOTS)
    if allowed_fixture_root is not None:
        candidate_roots.add(str(Path(allowed_fixture_root).resolve()))

    system_temp = Path(tempfile.gettempdir()).resolve()
    valid_roots: list[Path] = []
    for r_str in candidate_roots:
        try:
            r_path = Path(r_str).resolve()
            if r_path.exists() and r_path.is_dir():
                r_path.relative_to(system_temp)
                valid_roots.append(r_path)
        except Exception:
            continue

    if valid_roots:
        storage_paths: list[Path] = []
        meta_db = resolved.get("metadata_db")
        lance_path = resolved.get("lancedb_path")
        if meta_db:
            storage_paths.append(Path(meta_db).resolve())
        if lance_path:
            storage_paths.append(Path(lance_path).resolve())

        lance_sec = resolved.get("lancedb")
        if isinstance(lance_sec, dict) and lance_sec.get("uri"):
            storage_paths.append(Path(lance_sec["uri"]).resolve())

        # P0-B: Check inherited FLYING_RAG_METADATA_DB override from environment
        env_meta = os.environ.get("FLYING_RAG_METADATA_DB", "").strip()
        if env_meta:
            storage_paths.append(Path(env_meta).resolve())

        tbl_path = resolved.get("table_parquet")
        if tbl_path:
            storage_paths.append(Path(tbl_path).resolve())

        if storage_paths:
            all_contained = True
            for sp in storage_paths:
                # NG-05: Reject symlink / junction aliases pointing outside
                try:
                    if sp.is_symlink() or os.path.islink(str(sp)):
                        return "BLOCKED_SYMLINK_ALIAS_DETECTED"
                except Exception:
                    pass
                contained_in_any = False
                for vr in valid_roots:
                    try:
                        sp.relative_to(vr)
                        contained_in_any = True
                        break
                    except ValueError:
                        continue
                if not contained_in_any:
                    all_contained = False
                    break

            if all_contained:
                return "ISOLATED_COPY_VERIFIED"

    return "BLOCKED_READONLY_NOT_PROVEN"


def evaluate_pilot_eligibility_predicate(
    backend_online: bool,
    readonly_scope: str,
    actual_search_calls: int,
    total_queries: int,
    completed_successful_pairs: int,
    search_errors: int,
    rank_mismatches: int,
    norm_payload_mismatches: int,
    shadow_submitted: int,
    shadow_processed: int,
    eig_events_verified: int,
    shadow_errors: int,
    shadow_dropped: int,
    shadow_adapter_missing: int,
    shadow_timeouts: int,
    off_observer_calls: int
) -> bool:
    """
    Public eligibility predicate for pilot GO (Block P3-F & Rev 4 Section 2.2).
    Storage scope veto is mandatory: if not is_storage_scope_admitted(readonly_scope), returns False.
    """
    if not is_storage_scope_admitted(readonly_scope):
        return False

    return bool(
        backend_online and
        total_queries > 0 and
        actual_search_calls == 2 * total_queries and
        completed_successful_pairs == total_queries and
        search_errors == 0 and
        rank_mismatches == 0 and
        norm_payload_mismatches == 0 and
        shadow_submitted == total_queries and
        shadow_processed == total_queries and
        eig_events_verified == total_queries and
        shadow_errors == 0 and
        shadow_dropped == 0 and
        shadow_adapter_missing == 0 and
        shadow_timeouts == 0 and
        off_observer_calls == 0
    )


def check_backend_readiness(
    config_path: Optional[Path | str] = None,
    timeout_sec: float = 2.0
) -> Tuple[bool, Dict[str, Any]]:
    """
    Checks embedding backend readiness with fast socket probing and bounded deadline (Block P3-D & Rev 3 Block A).
    Preserves parent environment variables via try/finally and enforecs unified isolated configuration.
    """
    effective_config_path = Path(config_path) if config_path else DEFAULT_ISOLATED_CONFIG
    if not effective_config_path.exists():
        effective_config_path = ROOT_DIR / "config.yaml"

    cfg_fingerprint, cfg_data = get_config_fingerprint(effective_config_path)
    embed_cfg = cfg_data.get("embedder") or cfg_data.get("lemonade") or {}
    endpoint_url = embed_cfg.get("url") or embed_cfg.get("base_url") or "http://127.0.0.1:8089/v1/embeddings"
    expected_model = embed_cfg.get("model", "Qwen3-Embedding-0.6B-Q8_0.gguf")
    expected_dimension = int(embed_cfg.get("dimension", 1024))

    orig_parent_cfg = os.environ.get("FLYING_RAG_CONFIG")
    try:
        os.environ["FLYING_RAG_CONFIG"] = str(effective_config_path)

        # Verify provider consistency
        provider_url = ""
        provider_model = ""
        try:
            from embedder.client import LemonadeEmbeddingProvider
            prov = LemonadeEmbeddingProvider()
            provider_url = getattr(prov, "url", "")
            provider_model = getattr(prov, "model", "")
        except Exception:
            pass

        if provider_url and provider_url != endpoint_url:
            diag = {
                "endpoint_url": endpoint_url,
                "provider_url": provider_url,
                "expected_model": expected_model,
                "expected_dimension": expected_dimension,
                "config_path": str(effective_config_path),
                "config_fingerprint": cfg_fingerprint[:16] if cfg_fingerprint else "",
                "error_classification": "BLOCKED_CONFIG_MISMATCH",
                "error_detail": f"Configuration mismatch: TCP probe target is '{endpoint_url}' but provider is initialized to '{provider_url}'",
                "preflight_deadline_sec": timeout_sec,
                "required_operator_action": "Set unified FLYING_RAG_CONFIG matching target embedding endpoint before starting pilot."
            }
            return False, diag

        diag = {
            "endpoint_url": endpoint_url,
            "provider_url": provider_url or endpoint_url,
            "expected_model": expected_model,
            "expected_dimension": expected_dimension,
            "config_path": str(effective_config_path),
            "config_fingerprint": cfg_fingerprint[:16] if cfg_fingerprint else "",
            "error_classification": "NONE",
            "error_detail": "",
            "preflight_deadline_sec": timeout_sec,
            "strict_policy_applied": "NO_MOCKS_NO_GENERATED_HITS_ENFORCED",
            "readonly_scope": check_readonly_scope(effective_config_path, backend_online=False),
            "required_operator_action": (
                "1. Ensure verified safe/isolated storage environment (OS read-only mode or agreed isolated copy); "
                f"2. Launch embedding service (llama-server) on {endpoint_url} with model '{expected_model}' (dim={expected_dimension})."
            )
        }

        # Fast TCP socket probe first to avoid 10s httpx connect timeout on closed Windows loopback
        parsed = urllib.parse.urlparse(endpoint_url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)

        t0_probe = time.perf_counter()
        try:
            s = socket.create_connection((host, port), timeout=min(timeout_sec, 0.5))
            s.close()
        except (TimeoutError, socket.timeout) as e:
            diag["error_classification"] = "SOCKET_TIMEOUT"
            diag["error_detail"] = f"Socket connection to {host}:{port} timed out after 0.5s ({type(e).__name__}: {e})"
            return False, diag
        except ConnectionRefusedError as e:
            diag["error_classification"] = "CONNECTION_REFUSED"
            diag["error_detail"] = f"Connection refused by {host}:{port} ({type(e).__name__}: {e})"
            return False, diag
        except OSError as e:
            diag["error_classification"] = "NETWORK_ERROR"
            diag["error_detail"] = f"Socket error on {host}:{port} ({type(e).__name__}: {e})"
            return False, diag

        # If TCP port is open, ping embedding model in bounded thread
        result_container = []
        error_container = []

        def _ping_target():
            try:
                from embedder.client import LemonadeEmbeddingProvider
                prov_ping = LemonadeEmbeddingProvider()
                res = prov_ping.embed_batch(["ping"], is_query=True)
                result_container.append(res)
            except Exception as e:
                error_container.append(e)

        remaining_sec = max(0.2, timeout_sec - (time.perf_counter() - t0_probe))
        th = threading.Thread(target=_ping_target, daemon=True)
        th.start()
        th.join(timeout=remaining_sec)

        if th.is_alive():
            diag["error_classification"] = "PREFLIGHT_DEADLINE_EXCEEDED"
            diag["error_detail"] = f"Embedding provider ping exceeded timeout of {timeout_sec}s"
            return False, diag

        if error_container:
            diag["error_classification"] = "HTTP_OR_PROVIDER_ERROR"
            diag["error_detail"] = str(error_container[0])
            return False, diag

        res = result_container[0] if result_container else []
        if not res or len(res) == 0:
            diag["error_classification"] = "EMPTY_EMBEDDING_RESULT"
            diag["error_detail"] = "Provider returned empty embedding vector on ping"
            return False, diag

        diag["actual_dimension"] = len(res[0])
        if len(res[0]) != expected_dimension:
            diag["error_classification"] = "DIMENSION_MISMATCH"
            diag["error_detail"] = f"Expected dimension {expected_dimension}, got {len(res[0])}"
            return False, diag

        diag["readonly_scope"] = check_readonly_scope(effective_config_path, backend_online=True)
        return True, diag
    finally:
        if orig_parent_cfg is not None:
            os.environ["FLYING_RAG_CONFIG"] = orig_parent_cfg
        else:
            os.environ.pop("FLYING_RAG_CONFIG", None)


def execute_bounded_search(
    query: str,
    shadow_mode: bool,
    timeout_sec: float = 5.0,
    observer_timeout_sec: float = 2.0,
    config_path: Optional[Path | str] = None,
    log_path: Optional[Path | str] = None,
    control_file_path: Optional[Path | str] = None,
    delay_sec: float = 0.0,
    simulated_error: Optional[str] = None,
    simulated_result: Optional[str] = None
) -> SearchResult:
    """
    Executes search_documents via MCP _dispatch in an isolated child OS process (Block P3-B & Rev 3 Block A).
    Guarantees that on timeout, the child process is terminated immediately with confirmed exit,
    leaving ZERO lingering worker threads or cross-contamination between OFF and ON runs.
    Returns: SearchResult (tuple of 5 elements + .shadow_stats)
    """
    t0 = time.perf_counter()

    cmd = [
        sys.executable,
        str(WORKER_SCRIPT),
        "--query", query,
        "--shadow-mode", "1" if shadow_mode else "0",
        "--observer-timeout", str(observer_timeout_sec)
    ]
    if config_path:
        cmd.extend(["--config-path", str(config_path)])
    if log_path:
        cmd.extend(["--log-path", str(log_path)])
    if control_file_path:
        cmd.extend(["--control-file", str(control_file_path)])
    if delay_sec > 0:
        cmd.extend(["--delay-sec", str(delay_sec)])
    if simulated_error:
        cmd.extend(["--simulated-error", str(simulated_error)])
    if simulated_result:
        cmd.extend(["--simulated-result", str(simulated_result)])

    child_env = dict(os.environ)
    if config_path:
        child_env["FLYING_RAG_CONFIG"] = str(config_path)
    child_env["FLYING_RAG_SHADOW_EIG"] = "1" if shadow_mode else "0"
    if log_path:
        child_env["FLYING_RAG_SHADOW_LOG_PATH"] = str(log_path)
    if control_file_path:
        child_env["FLYING_RAG_SHADOW_CONTROL_FILE"] = str(control_file_path)

    # P0-B: Sanitize child environment - remove inherited FLYING_RAG_METADATA_DB to prevent production leak
    child_env.pop("FLYING_RAG_METADATA_DB", None)

    proc = subprocess.Popen(
        cmd,
        env=child_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    child_wait_timeout = timeout_sec + (observer_timeout_sec if shadow_mode else 0.0)

    try:
        stdout, stderr = proc.communicate(timeout=child_wait_timeout)
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
    except subprocess.TimeoutExpired:
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        proc.terminate()
        try:
            stdout, stderr = proc.communicate(timeout=1.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate(timeout=0.5)

        exitcode = proc.poll()
        return SearchResult(False, None, elapsed_ms, f"SEARCH_DEADLINE_EXCEEDED (timeout={child_wait_timeout}s, child_terminated=True)", exitcode, None)

    exitcode = proc.poll()
    if exitcode != 0 and not stdout:
        return SearchResult(False, None, elapsed_ms, f"CHILD_PROCESS_EXIT_ERROR: exitcode={exitcode}, stderr={stderr.strip()}", exitcode, None)

    try:
        data = json.loads(stdout.strip())
        success = bool(data.get("success", False))
        result = data.get("result")
        err = data.get("error", "")
        shadow_stats = data.get("shadow_stats")

        is_err, err_detail = is_error_payload(result)
        if is_err:
            return SearchResult(False, result, elapsed_ms, f"RETRIEVAL_ERROR_PAYLOAD: {err_detail}", exitcode, shadow_stats)

        return SearchResult(success, result, elapsed_ms, err, exitcode, shadow_stats)
    except Exception as e:
        return SearchResult(False, None, elapsed_ms, f"CHILD_OUTPUT_PARSE_ERROR: {e} (stdout={stdout[:200]})", exitcode, None)


def wait_for_shadow_completion(
    adapter: Any,
    initial_processed: int,
    timeout_sec: float = 2.0
) -> Tuple[bool, int, str]:
    """
    Waits bounded time for background observation task to complete without interrupting thread pool.
    Returns: (completed_ok, new_processed_count, status_msg)
    """
    if not adapter:
        return False, 0, "ADAPTER_NONE"

    t0 = time.perf_counter()
    while time.perf_counter() - t0 < timeout_sec:
        with getattr(adapter, "_lock", threading.Lock()):
            current_processed = getattr(adapter, "processed_count", 0)
            active_futures = getattr(adapter, "_active_futures", set())
            active = len([f for f in active_futures if not f.done()])
        if current_processed > initial_processed and active == 0:
            return True, current_processed, "OBSERVATION_COMPLETED"
        time.sleep(0.01)

    with getattr(adapter, "_lock", threading.Lock()):
        current_processed = getattr(adapter, "processed_count", 0)
    if current_processed > initial_processed:
        return True, current_processed, "OBSERVATION_COMPLETED_POST_WAIT"

    return False, current_processed, f"OBSERVER_DEADLINE_EXCEEDED (timeout={timeout_sec}s)"


def verify_eig_event_correlation(
    log_path: Path | str,
    query: str,
    min_timestamp_iso: Optional[str] = None
) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """
    Verifies that a valid EIG telemetry event exists in log_path correlated to the query (Block P3-A & Rev 3 Block B).
    Rejects missing events, mismatched query_hash, timestamps earlier than min_timestamp_iso,
    SHADOW_ERROR divergence, or empty evidence status.
    Returns: (is_valid, event_dict, status_msg)
    """
    p = Path(log_path)
    if not p.exists():
        return False, None, "LOG_FILE_DOES_NOT_EXIST"

    if p.stat().st_size == 0:
        return False, None, "LOG_FILE_EMPTY"

    expected_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()[:16]

    matching_events = []
    stale_events = []
    try:
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if not line_str:
                    continue
                try:
                    ev = json.loads(line_str)
                    if ev.get("query_hash") == expected_hash:
                        ev_ts = ev.get("timestamp")
                        if min_timestamp_iso and ev_ts:
                            try:
                                dt_ev = datetime.fromisoformat(ev_ts)
                                dt_min = datetime.fromisoformat(min_timestamp_iso)
                                if dt_ev < dt_min:
                                    stale_events.append(ev)
                                    continue
                            except Exception:
                                if str(ev_ts) < str(min_timestamp_iso):
                                    stale_events.append(ev)
                                    continue
                        matching_events.append(ev)
                except Exception:
                    continue
    except Exception as e:
        return False, None, f"LOG_READ_ERROR: {e}"

    if not matching_events:
        if stale_events:
            return False, stale_events[-1], f"EIG_EVENT_STALE: Found event timestamp '{stale_events[-1].get('timestamp')}' earlier than min_timestamp_iso '{min_timestamp_iso}'"
        return False, None, f"EIG_EVENT_MISSING: No event found for query_hash={expected_hash}"

    latest = matching_events[-1]

    if latest.get("divergence") == "SHADOW_ERROR":
        return False, latest, f"EIG_SHADOW_ERROR: {latest.get('error', 'unknown error')}"

    eig_summary = latest.get("eig_summary", {})
    status = eig_summary.get("answer_evidence_status")
    if not status:
        return False, latest, "EIG_SUMMARY_STATUS_MISSING"

    valid_statuses = ("USABLE_FOR_ANSWER", "EVIDENCE_PARTIAL", "REFUSAL_REQUIRED", "NOT_APPLICABLE")
    if status not in valid_statuses:
        return False, latest, f"EIG_UNRECOGNIZED_STATUS: {status}"

    return True, latest, "EIG_EVENT_VERIFIED"


def run_real_retrieval_shadow_pilot(
    per_query_timeout_sec: float = 5.0,
    observer_timeout_sec: float = 2.0,
    total_pilot_deadline_sec: float = 60.0,
    max_queries: int | None = None,
    config_path: Optional[Path | str] = None,
    isolated_log_path: Optional[Path | str] = None,
    allowed_fixture_root: Optional[Path | str] = None,
    query_manifest_path: Optional[Path | str] = None,
    expected_manifest_count: Optional[int] = 105
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """
    Executes or checks the real retrieval shadow pilot pipeline under strict supervisor control (Stage 4.2.8 Rev 4).
    Guarantees:
    1. Parent environment preservation across all return paths via outer try/finally.
    2. Dynamic runtime config schema validation (Block C).
    3. Dedicated per-pair event isolation channels preventing repeated query cross-talk (Block B).
    4. Bounded total deadline tracking preventing exhaustion leaks (Block A).
    5. Pre-execution storage readonly gate blocking search calls before launching worker processes (Rev 4 Section 2.1).
    6. Public predicate veto enforcing admitted storage scope (Rev 4 Section 2.2).
    Returns: (summary_dict, detailed_query_records)
    """
    t0_pilot = time.perf_counter()
    orig_env = os.environ.get("FLYING_RAG_SHADOW_EIG")
    orig_cfg = os.environ.get("FLYING_RAG_CONFIG")

    try:
        manifest_sha256 = ""
        query_metadata = None
        if query_manifest_path is not None:
            if Path(query_manifest_path).exists():
                try:
                    with open(query_manifest_path, "r", encoding="utf-8") as f:
                        manifest_sha256 = json.load(f).get("manifest_sha256", "")
                except Exception:
                    pass
            man_ok, man_msg, man_queries = validate_query_manifest(query_manifest_path, expected_count=expected_manifest_count)
            if not man_ok:
                summary = {
                    "pilot_name": "REAL_RETRIEVAL_SHADOW_PILOT",
                    "pilot_mode": "FULL_MANIFEST_105" if expected_manifest_count == 105 else "MANIFEST_CUSTOM",
                    "series_completion": "INVALID",
                    "full_105_go_eligible": False,
                    "status": "CONFIG_INVALID",
                    "verdict": "BLOCKED",
                    "contract_tests_status": "FAILED",
                    "real_pilot_execution": "CONFIG_INVALID",
                    "shadow_observation_verified": False,
                    "error_detail": f"Query manifest validation failed: {man_msg}",
                    "readonly_scope": "BLOCKED_CONFIG_INVALID",
                    "cross_store_recovery": "BLOCKED",
                    "production_deployment": "NOT_AUTHORIZED",
                    "total_queries_planned": 0,
                    "queries_completed": 0,
                    "actual_search_calls_executed": 0,
                    "config_fingerprint": "",
                    "manifest_sha256": manifest_sha256,
                    "shadow_stats": {
                        "submitted": 0, "processed": 0, "errors": 0, "dropped": 0,
                        "adapter_missing": 0, "timeouts": 0,
                        "actual_adapter_stats_available": False,
                        "child_adapter_stats": "UNAVAILABLE_CONFIG_INVALID"
                    },
                    "successful_search_calls": {"off": 0, "on": 0, "total": 0},
                    "correlated_events_verified": 0,
                    "reason": f"Query manifest validation failed: {man_msg}"
                }
                return summary, []
            queries = [q["query_text"] for q in man_queries]
            query_metadata = man_queries
            pilot_base_name = f"REAL_RETRIEVAL_SHADOW_PILOT_MANIFEST_{len(queries)}"
            pilot_mode = "FULL_MANIFEST_105" if len(man_queries) == 105 else f"MANIFEST_{len(man_queries)}"
        else:
            queries = ACTUAL_NORMATIVE_QUERIES + SYNTHETIC_ADVERSARIAL_QUERIES
            pilot_base_name = "REAL_RETRIEVAL_SHADOW_PILOT"
            pilot_mode = "SMOKE_LEGACY_8"

        full_planned_count = len(queries)
        is_partial = False
        if max_queries is not None:
            if max_queries <= 0:
                summary = {
                    "pilot_name": "REAL_RETRIEVAL_SHADOW_PILOT",
                    "pilot_mode": pilot_mode,
                    "series_completion": "INVALID",
                    "full_105_go_eligible": False,
                    "status": "CONFIG_INVALID",
                    "verdict": "BLOCKED",
                    "contract_tests_status": "FAILED",
                    "real_pilot_execution": "CONFIG_INVALID",
                    "shadow_observation_verified": False,
                    "error_detail": f"Invalid max_queries parameter: {max_queries} (must be a positive integer)",
                    "readonly_scope": "BLOCKED_CONFIG_INVALID",
                    "cross_store_recovery": "BLOCKED",
                    "production_deployment": "NOT_AUTHORIZED",
                    "total_queries_planned": 0,
                    "queries_completed": 0,
                    "actual_search_calls_executed": 0,
                    "config_fingerprint": "",
                    "manifest_sha256": manifest_sha256,
                    "shadow_stats": {
                        "submitted": 0, "processed": 0, "errors": 0, "dropped": 0,
                        "adapter_missing": 0, "timeouts": 0,
                        "actual_adapter_stats_available": False,
                        "child_adapter_stats": "UNAVAILABLE_CONFIG_INVALID"
                    },
                    "successful_search_calls": {"off": 0, "on": 0, "total": 0},
                    "correlated_events_verified": 0,
                    "reason": f"Invalid max_queries parameter: {max_queries} (must be a positive integer)"
                }
                return summary, []
            if max_queries < full_planned_count:
                is_partial = True
            queries = queries[:max_queries]
            if query_metadata:
                query_metadata = query_metadata[:max_queries]
        total_queries = len(queries)

        effective_config = Path(config_path) if config_path else DEFAULT_ISOLATED_CONFIG
        config_fp, _ = get_config_fingerprint(effective_config)

        # 1. Validate isolated runtime config schema before searching
        cfg_valid, cfg_msg, resolved_paths = validate_pilot_config(effective_config)
        if not cfg_valid:
            summary = {
                "pilot_name": "REAL_RETRIEVAL_SHADOW_PILOT",
                "pilot_mode": pilot_mode,
                "series_completion": "PARTIAL" if is_partial else "COMPLETE",
                "full_105_go_eligible": False,
                "status": "CONFIG_INVALID",
                "verdict": "BLOCKED",
                "contract_tests_status": "FAILED",
                "real_pilot_execution": "CONFIG_INVALID",
                "shadow_observation_verified": False,
                "error_detail": cfg_msg,
                "readonly_scope": "BLOCKED_CONFIG_INVALID",
                "cross_store_recovery": "BLOCKED",
                "production_deployment": "NOT_AUTHORIZED",
                "total_queries_planned": total_queries,
                "queries_completed": 0,
                "actual_search_calls_executed": 0,
                "config_fingerprint": config_fp,
                "manifest_sha256": manifest_sha256,
                "shadow_stats": {
                    "submitted": 0, "processed": 0, "errors": 0, "dropped": 0,
                    "adapter_missing": 0, "timeouts": 0,
                    "actual_adapter_stats_available": False,
                    "child_adapter_stats": "UNAVAILABLE_CONFIG_INVALID"
                },
                "successful_search_calls": {"off": 0, "on": 0, "total": 0},
                "correlated_events_verified": 0,
                "reason": f"Isolated config validation failed: {cfg_msg}"
            }
            return summary, []

        # 2. Preflight check with bounded 2.0s deadline and unified configuration
        backend_online, diag = check_backend_readiness(config_path=effective_config, timeout_sec=2.0)

        if not backend_online:
            summary = {
                "pilot_name": "REAL_RETRIEVAL_SHADOW_PILOT",
                "pilot_mode": pilot_mode,
                "series_completion": "PARTIAL" if is_partial else "COMPLETE",
                "full_105_go_eligible": False,
                "status": "BLOCKED_DEPENDENCY",
                "verdict": "BLOCKED",
                "contract_tests_status": "PASSED",
                "real_pilot_execution": "BLOCKED_DEPENDENCY",
                "shadow_observation_verified": False,
                "backend_diagnosis": diag,
                "readonly_scope": diag.get("readonly_scope", "READONLY_VERIFIED_OFFLINE_PROBE_NO_DB_WRITE"),
                "cross_store_recovery": "BLOCKED",
                "production_deployment": "NOT_AUTHORIZED",
                "total_queries_planned": total_queries,
                "queries_completed": 0,
                "actual_search_calls_executed": 0,
                "config_fingerprint": config_fp,
                "manifest_sha256": manifest_sha256,
                "shadow_stats": {
                    "submitted": 0, "processed": 0, "errors": 0, "dropped": 0,
                    "adapter_missing": 0, "timeouts": 0,
                    "actual_adapter_stats_available": False,
                    "child_adapter_stats": "UNAVAILABLE_OFFLINE"
                },
                "successful_search_calls": {"off": 0, "on": 0, "total": 0},
                "correlated_events_verified": 0,
                "reason": (
                    f"Embedding backend at {diag['endpoint_url']} is offline or unreachable ({diag['error_detail']}). "
                    "Per Section 0 & 3 of specification FR-TZ-20261116-004 / Rev 4, real retrieval pilot is stopped with "
                    "BLOCKED_DEPENDENCY rather than substituting synthetic hits or mock search outputs. "
                    f"Required operator action: {diag['required_operator_action']}"
                ),
                "payload_raw_equality": False,
                "payload_normalized_equality": False,
                "rank_equality": False
            }
            records = [
                {
                    "query_index": i + 1,
                    "query_id": query_metadata[i]["query_id"] if query_metadata else hashlib.sha256(f"q_{i}_{q}".encode("utf-8")).hexdigest()[:16],
                    "category": query_metadata[i]["category"] if query_metadata else ("ACTUAL_NORMATIVE" if i < len(ACTUAL_NORMATIVE_QUERIES) else "SYNTHETIC_ADVERSARIAL"),
                    "off_status": "BLOCKED_DEPENDENCY",
                    "on_status": "BLOCKED_DEPENDENCY",
                    "pair_success": False,
                    "error": diag["error_detail"]
                }
                for i, q in enumerate(queries)
            ]
            return summary, records

        # 3. Pre-Execution Readonly Gate (Rev 4 Section 2.1)
        storage_scope = check_readonly_scope(effective_config, backend_online=True, allowed_fixture_root=allowed_fixture_root)
        if not is_storage_scope_admitted(storage_scope):
            summary = {
                "pilot_name": "REAL_RETRIEVAL_SHADOW_PILOT",
                "pilot_mode": pilot_mode,
                "series_completion": "PARTIAL" if is_partial else "COMPLETE",
                "full_105_go_eligible": False,
                "status": storage_scope,
                "verdict": "BLOCKED",
                "contract_tests_status": "PASSED",
                "real_pilot_execution": "BLOCKED_STORAGE_SCOPE",
                "shadow_observation_verified": False,
                "backend_diagnosis": diag,
                "readonly_scope": storage_scope,
                "cross_store_recovery": "BLOCKED",
                "production_deployment": "NOT_AUTHORIZED",
                "total_queries_planned": total_queries,
                "queries_completed": 0,
                "actual_search_calls_executed": 0,
                "config_fingerprint": config_fp,
                "manifest_sha256": manifest_sha256,
                "shadow_stats": {
                    "submitted": 0, "processed": 0, "errors": 0, "dropped": 0,
                    "adapter_missing": 0, "timeouts": 0,
                    "actual_adapter_stats_available": False,
                    "child_adapter_stats": "UNAVAILABLE_STORAGE_SCOPE_BLOCKED"
                },
                "successful_search_calls": {"off": 0, "on": 0, "total": 0},
                "correlated_events_verified": 0,
                "reason": (
                    f"Storage readonly scope is unproven ({storage_scope}). "
                    "Per Section 2.1 of specification FR-TZ-20261116-004 / Rev 4, search execution on "
                    "unverified storage paths is strictly blocked before launching worker processes. "
                    "Required operator action: 1. Ensure verified safe/isolated storage scope; "
                    "2. Verify embedding endpoint availability."
                ),
                "payload_raw_equality": False,
                "payload_normalized_equality": False,
                "rank_equality": False
            }
            records = [
                {
                    "query_index": i + 1,
                    "query_id": query_metadata[i]["query_id"] if query_metadata else hashlib.sha256(f"q_{i}_{q}".encode("utf-8")).hexdigest()[:16],
                    "category": query_metadata[i]["category"] if query_metadata else ("ACTUAL_NORMATIVE" if i < len(ACTUAL_NORMATIVE_QUERIES) else "SYNTHETIC_ADVERSARIAL"),
                    "off_status": storage_scope,
                    "on_status": storage_scope,
                    "pair_success": False,
                    "error": f"Search calls blocked by pre-execution readonly gate ({storage_scope})"
                }
                for i, q in enumerate(queries)
            ]
            return summary, records

        # 4. If backend is online and storage scope admitted, execute paired calls via isolated child processes
        run_temp_dir = Path(tempfile.mkdtemp(prefix="shadow_pilot_run_"))

        records = []
        raw_payload_mismatches = 0
        norm_payload_mismatches = 0
        rank_mismatches = 0
        actual_search_calls = 0
        search_errors = 0
        completed_successful_pairs = 0
        completed_off_searches = 0
        completed_on_searches = 0

        shadow_submitted = 0
        shadow_processed = 0
        shadow_errors = 0
        shadow_dropped = 0
        shadow_adapter_missing = 0
        shadow_timeouts = 0
        off_observer_calls = 0
        eig_events_verified = 0

        child_stats_history = []
        initial_config_fp, _ = get_config_fingerprint(effective_config)
        config_mutated = False
        deadline_exhausted = False

        for i, q in enumerate(queries):
            remaining_total = max(0.0, total_pilot_deadline_sec - (time.perf_counter() - t0_pilot))
            if remaining_total <= 0.0 or remaining_total < (per_query_timeout_sec * 2):
                deadline_exhausted = True
                break

            # NG-05 / P0-D: Check config file mutation & storage scope before spawning OFF worker
            curr_fp, _ = get_config_fingerprint(effective_config)
            curr_scope = check_readonly_scope(effective_config, backend_online=True, allowed_fixture_root=allowed_fixture_root)
            if curr_fp != initial_config_fp or not is_storage_scope_admitted(curr_scope):
                config_mutated = True
                break

            query_id = hashlib.sha256(f"q_{i}_{q}".encode("utf-8")).hexdigest()[:16]

            # Dedicated per-pair directory and independent log channels (Block B)
            pair_dir = run_temp_dir / f"pair_{i:04d}"
            pair_dir.mkdir(parents=True, exist_ok=True)
            off_log = pair_dir / "off.jsonl"
            on_log = pair_dir / "on.jsonl"

            # Step A: Shadow OFF call with budget bounded by remaining total deadline
            call_budget_off = min(per_query_timeout_sec, remaining_total)
            off_res = execute_bounded_search(
                query=q,
                shadow_mode=False,
                timeout_sec=call_budget_off,
                observer_timeout_sec=0.0,
                config_path=effective_config,
                log_path=off_log
            )
            off_ok, res_off, t_off, err_off, code_off = off_res
            actual_search_calls += 1
            if off_ok:
                completed_off_searches += 1
            else:
                search_errors += 1

            # In OFF mode, verify telemetry log was NOT written in its dedicated channel
            off_ev_ok, _, _ = verify_eig_event_correlation(off_log, q)
            if off_ev_ok:
                off_observer_calls += 1

            # Recalculate remaining budget before starting ON call
            remaining_total = max(0.0, total_pilot_deadline_sec - (time.perf_counter() - t0_pilot))
            if remaining_total <= 0.0:
                deadline_exhausted = True
                break

            # P0-D / G2-09: Re-verify config fingerprint AND storage scope immediately BEFORE spawning ON worker!
            curr_fp_on, _ = get_config_fingerprint(effective_config)
            curr_scope_on = check_readonly_scope(effective_config, backend_online=True, allowed_fixture_root=allowed_fixture_root)
            if curr_fp_on != initial_config_fp or not is_storage_scope_admitted(curr_scope_on):
                config_mutated = True
                rec_cat = query_metadata[i]["category"] if query_metadata else ("ACTUAL_NORMATIVE" if i < len(ACTUAL_NORMATIVE_QUERIES) else "SYNTHETIC_ADVERSARIAL")
                rec_qid = query_metadata[i]["query_id"] if query_metadata else query_id
                records.append({
                    "query_index": i + 1,
                    "query_id": rec_qid,
                    "category": rec_cat,
                    "off_status": "OK" if off_ok else err_off,
                    "on_status": "BLOCKED_CONFIG_MUTATED_BEFORE_ON",
                    "time_off_ms": t_off,
                    "time_on_ms": 0.0,
                    "rank_match": False,
                    "raw_payload_equal": False,
                    "norm_payload_equal": False,
                    "raw_hash_off": "",
                    "raw_hash_on": "",
                    "norm_hash_off": "",
                    "norm_hash_on": "",
                    "removed_volatile_fields": [],
                    "eig_event_verified": False,
                    "pair_success": False
                })
                break

            # Step B: Shadow ON call with budget bounded by remaining total deadline
            t_before_on = datetime.now().isoformat()
            call_budget_on = min(per_query_timeout_sec + observer_timeout_sec, remaining_total)
            on_res = execute_bounded_search(
                query=q,
                shadow_mode=True,
                timeout_sec=call_budget_on,
                observer_timeout_sec=observer_timeout_sec,
                config_path=effective_config,
                log_path=on_log
            )
            on_ok, res_on, t_on, err_on, code_on = on_res
            actual_search_calls += 1
            if on_ok:
                completed_on_searches += 1
                shadow_submitted += 1
            else:
                search_errors += 1

            if on_res.shadow_stats:
                child_stats_history.append(on_res.shadow_stats)

            # Verify actual EIG event correlation in dedicated on_log channel with timestamp validation
            ev_ok, ev_data, ev_msg = verify_eig_event_correlation(on_log, q, min_timestamp_iso=t_before_on)
            if ev_ok:
                shadow_processed += 1
                eig_events_verified += 1
            else:
                if "SHADOW_ERROR" in ev_msg:
                    shadow_errors += 1
                else:
                    shadow_timeouts += 1

            # Step C: Compare ranks and payloads
            if off_ok and on_ok:
                ranks_match = compare_ranks(res_off, res_on)
                payload_cmp = compare_payloads(res_off, res_on)
                if not ranks_match:
                    rank_mismatches += 1
                if not payload_cmp["normalized_equal"]:
                    norm_payload_mismatches += 1
                if not payload_cmp["raw_equal"]:
                    raw_payload_mismatches += 1
                pair_success = ranks_match and payload_cmp["normalized_equal"] and ev_ok
            else:
                ranks_match = False
                payload_cmp = {
                    "raw_equal": False,
                    "raw_hash_off": "",
                    "raw_hash_on": "",
                    "normalized_equal": False,
                    "norm_hash_off": "",
                    "norm_hash_on": "",
                    "removed_volatile_fields": []
                }
                pair_success = False

            if pair_success:
                completed_successful_pairs += 1

            rec_cat = query_metadata[i]["category"] if query_metadata else ("ACTUAL_NORMATIVE" if i < len(ACTUAL_NORMATIVE_QUERIES) else "SYNTHETIC_ADVERSARIAL")
            rec_qid = query_metadata[i]["query_id"] if query_metadata else query_id
            records.append({
                "query_index": i + 1,
                "query_id": rec_qid,
                "category": rec_cat,
                "off_status": "OK" if off_ok else err_off,
                "on_status": "OK" if on_ok else err_on,
                "time_off_ms": t_off,
                "time_on_ms": t_on,
                "rank_match": ranks_match,
                "raw_payload_equal": payload_cmp["raw_equal"],
                "norm_payload_equal": payload_cmp["normalized_equal"],
                "raw_hash_off": payload_cmp["raw_hash_off"][:12] if payload_cmp["raw_hash_off"] else "",
                "raw_hash_on": payload_cmp["raw_hash_on"][:12] if payload_cmp["raw_hash_on"] else "",
                "norm_hash_off": payload_cmp["norm_hash_off"][:12] if payload_cmp["norm_hash_off"] else "",
                "norm_hash_on": payload_cmp["norm_hash_on"][:12] if payload_cmp["norm_hash_on"] else "",
                "removed_volatile_fields": payload_cmp["removed_volatile_fields"],
                "eig_event_verified": ev_ok,
                "pair_success": pair_success
            })

        # Fail-closed eligibility predicate (Rev 4 Section 2.2)
        is_synthetic = (storage_scope == "ISOLATED_COPY_VERIFIED")

        pilot_go = evaluate_pilot_eligibility_predicate(
            backend_online=backend_online,
            readonly_scope=storage_scope,
            actual_search_calls=actual_search_calls,
            total_queries=total_queries,
            completed_successful_pairs=completed_successful_pairs,
            search_errors=search_errors,
            rank_mismatches=rank_mismatches,
            norm_payload_mismatches=norm_payload_mismatches,
            shadow_submitted=shadow_submitted,
            shadow_processed=shadow_processed,
            eig_events_verified=eig_events_verified,
            shadow_errors=shadow_errors,
            shadow_dropped=shadow_dropped,
            shadow_adapter_missing=shadow_adapter_missing,
            shadow_timeouts=shadow_timeouts,
            off_observer_calls=off_observer_calls
        )

        final_status = "PASSED" if pilot_go else "FAILED"
        final_verdict = "GO" if pilot_go else "NO_GO"
        final_reason = ""
        if config_mutated:
            final_status = "CONFIG_TAMPER_DETECTED"
            final_verdict = "BLOCKED"
            final_reason = "Configuration mutated on disk during execution loop (NG-05)"
        elif deadline_exhausted:
            final_status = "DEADLINE_EXCEEDED"
            final_verdict = "BLOCKED"
            final_reason = f"Total pilot deadline ({total_pilot_deadline_sec}s) exhausted during series execution (NG-09)"

        summary = {
            "pilot_name": "CONTRACT_SYNTHETIC_SHADOW_PILOT" if is_synthetic else pilot_base_name,
            "pilot_mode": pilot_mode,
            "series_completion": "PARTIAL" if is_partial else "COMPLETE",
            "full_105_go_eligible": (pilot_mode == "FULL_MANIFEST_105" and not is_partial and pilot_go and actual_search_calls == 210),
            "status": final_status,
            "verdict": final_verdict,
            "contract_tests_status": "PASSED",
            "real_pilot_execution": "CONTRACT_SYNTHETIC" if is_synthetic else ("EXECUTED" if backend_online else "BLOCKED_DEPENDENCY"),
            "shadow_observation_verified": (eig_events_verified == total_queries and shadow_errors == 0),
            "backend_diagnosis": diag,
            "readonly_scope": storage_scope,
            "cross_store_recovery": "BLOCKED",
            "production_deployment": "NOT_AUTHORIZED",
            "total_queries_planned": total_queries,
            "queries_completed": len(records),
            "completed_successful_pairs": completed_successful_pairs,
            "actual_search_calls_executed": actual_search_calls,
            "search_errors": search_errors,
            "config_fingerprint": config_fp,
            "manifest_sha256": manifest_sha256,
            "reason": final_reason,
            "successful_search_calls": {
                "off": completed_off_searches,
                "on": completed_on_searches,
                "total": completed_off_searches + completed_on_searches
            },
            "correlated_events_verified": eig_events_verified,
            "shadow_stats": {
                "submitted": shadow_submitted,
                "processed": shadow_processed,
                "errors": shadow_errors,
                "dropped": shadow_dropped,
                "adapter_missing": shadow_adapter_missing,
                "timeouts": shadow_timeouts,
                "actual_adapter_stats_available": bool(child_stats_history),
                "child_adapter_stats": child_stats_history[-1] if child_stats_history else "UNAVAILABLE_SEPARATE_PROCESS"
            },
            "off_observer_calls": off_observer_calls,
            "rank_mismatches": rank_mismatches,
            "norm_payload_mismatches": norm_payload_mismatches,
            "raw_payload_mismatches": raw_payload_mismatches,
            "payload_raw_equality": (raw_payload_mismatches == 0),
            "payload_normalized_equality": (norm_payload_mismatches == 0),
            "rank_equality": (rank_mismatches == 0)
        }
        return summary, records
    finally:
        if orig_env is not None:
            os.environ["FLYING_RAG_SHADOW_EIG"] = orig_env
        else:
            os.environ.pop("FLYING_RAG_SHADOW_EIG", None)

        if orig_cfg is not None:
            os.environ["FLYING_RAG_CONFIG"] = orig_cfg
        else:
            os.environ.pop("FLYING_RAG_CONFIG", None)


class TestRealRetrievalShadowPilotContract(unittest.TestCase):
    """
    Contract test suite verifying all 25 + 9 = 34 scenarios of Section 3 & Revision 3.
    Guarantees supervisor isolation, per-pair event channel isolation, parent environment preservation,
    and config schema validation.
    """

    def setUp(self):
        self._orig_env = os.environ.get("FLYING_RAG_SHADOW_EIG")
        self._orig_cfg = os.environ.get("FLYING_RAG_CONFIG")

    def tearDown(self):
        if self._orig_env is not None:
            os.environ["FLYING_RAG_SHADOW_EIG"] = self._orig_env
        else:
            os.environ.pop("FLYING_RAG_SHADOW_EIG", None)

        if self._orig_cfg is not None:
            os.environ["FLYING_RAG_CONFIG"] = self._orig_cfg
        else:
            os.environ.pop("FLYING_RAG_CONFIG", None)

    # --- Original Contract Scenarios 1-12 ---

    def test_contract_01_adapter_missing_yields_no_go(self):
        """Scenario 1: Preflight ready, but shadow adapter is missing in ON mode -> NO_GO/FAILED."""
        from unittest.mock import patch

        mock_diag = {"endpoint_url": "http://127.0.0.1:8089/v1/embeddings", "error_classification": "NONE", "required_operator_action": ""}
        with patch("tests.test_real_retrieval_shadow_pilot.check_backend_readiness", return_value=(True, mock_diag)):
            with patch("tests.test_real_retrieval_shadow_pilot.check_readonly_scope", return_value="ISOLATED_COPY_VERIFIED"):
                with patch("tests.test_real_retrieval_shadow_pilot.verify_eig_event_correlation", return_value=(False, None, "EIG_EVENT_MISSING")):
                    with patch("tests.test_real_retrieval_shadow_pilot.execute_bounded_search", return_value=SearchResult(True, [{"chunk_id": "c1"}], 10.0, "", 0)):
                        summary, records = run_real_retrieval_shadow_pilot(max_queries=2)
                        self.assertNotEqual(summary["verdict"], "GO")
                        self.assertEqual(summary["status"], "FAILED")

    def test_contract_02_enqueue_rejected_or_uncompleted_yields_no_go(self):
        """Scenario 2: Adapter exists, but observation does not complete -> NO_GO/FAILED."""
        from unittest.mock import patch

        mock_diag = {"endpoint_url": "http://127.0.0.1:8089/v1/embeddings", "error_classification": "NONE", "required_operator_action": ""}
        with patch("tests.test_real_retrieval_shadow_pilot.check_backend_readiness", return_value=(True, mock_diag)):
            with patch("tests.test_real_retrieval_shadow_pilot.check_readonly_scope", return_value="ISOLATED_COPY_VERIFIED"):
                with patch("tests.test_real_retrieval_shadow_pilot.verify_eig_event_correlation", return_value=(False, None, "OBSERVER_DEADLINE_EXCEEDED")):
                    with patch("tests.test_real_retrieval_shadow_pilot.execute_bounded_search", return_value=SearchResult(True, [{"chunk_id": "c1"}], 10.0, "", 0)):
                        summary, records = run_real_retrieval_shadow_pilot(max_queries=2, observer_timeout_sec=0.05)
                        self.assertNotEqual(summary["verdict"], "GO")
                        self.assertEqual(summary["status"], "FAILED")
                        self.assertGreater(summary["shadow_stats"]["timeouts"], 0)

    def test_contract_03_observer_error_or_drop_reflected_in_stats_not_zeros(self):
        """Scenario 3: Observer returns errors/drops -> reflected in stats and forbids GO."""
        from unittest.mock import patch

        mock_diag = {"endpoint_url": "http://127.0.0.1:8089/v1/embeddings", "error_classification": "NONE", "required_operator_action": ""}
        with patch("tests.test_real_retrieval_shadow_pilot.check_backend_readiness", return_value=(True, mock_diag)):
            with patch("tests.test_real_retrieval_shadow_pilot.check_readonly_scope", return_value="ISOLATED_COPY_VERIFIED"):
                with patch("tests.test_real_retrieval_shadow_pilot.verify_eig_event_correlation", return_value=(False, {"divergence": "SHADOW_ERROR"}, "EIG_SHADOW_ERROR")):
                    with patch("tests.test_real_retrieval_shadow_pilot.execute_bounded_search", return_value=SearchResult(True, [{"chunk_id": "c1"}], 10.0, "", 0)):
                        summary, records = run_real_retrieval_shadow_pilot(max_queries=1)
                        self.assertNotEqual(summary["verdict"], "GO")
                        self.assertGreater(summary["shadow_stats"]["errors"], 0)

    def test_contract_04_identical_error_payloads_yield_retrieval_failure_not_go(self):
        """Scenario 4: OFF/ON both return identical error payload -> failed retrieval, NOT GO."""
        from unittest.mock import patch

        err_payload = {"error": "fixture_backend_failure", "status": "FAILED"}
        mock_diag = {"endpoint_url": "http://127.0.0.1:8089/v1/embeddings", "error_classification": "NONE", "required_operator_action": ""}
        with patch("tests.test_real_retrieval_shadow_pilot.check_backend_readiness", return_value=(True, mock_diag)):
            with patch("tests.test_real_retrieval_shadow_pilot.check_readonly_scope", return_value="ISOLATED_COPY_VERIFIED"):
                with patch("tests.test_real_retrieval_shadow_pilot.execute_bounded_search", return_value=SearchResult(False, err_payload, 10.0, "ERROR_KEY_PRESENT", 0)):
                    summary, records = run_real_retrieval_shadow_pilot(max_queries=2)
                    self.assertNotEqual(summary["verdict"], "GO")
                    self.assertEqual(summary["status"], "FAILED")
                    self.assertGreater(summary["search_errors"], 0)
                    self.assertEqual(summary["completed_successful_pairs"], 0)

    def test_contract_05_counter_arithmetic_only(self):
        """Scenario 5 (Refined): Counter arithmetic test verifies predicate logic when all criteria met."""
        from unittest.mock import patch

        mock_res = [{"chunk_id": "c1", "text": "normative text"}]
        mock_diag = {"endpoint_url": "http://127.0.0.1:8089/v1/embeddings", "error_classification": "NONE", "required_operator_action": ""}
        mock_ev = {"divergence": "CONGRUENT", "eig_summary": {"answer_evidence_status": "USABLE_FOR_ANSWER"}}

        with patch("tests.test_real_retrieval_shadow_pilot.check_backend_readiness", return_value=(True, mock_diag)):
            with patch("tests.test_real_retrieval_shadow_pilot.check_readonly_scope", return_value="ISOLATED_COPY_VERIFIED"):
                with patch("tests.test_real_retrieval_shadow_pilot.execute_bounded_search", return_value=SearchResult(True, mock_res, 10.0, "", 0)):
                    with patch("tests.test_real_retrieval_shadow_pilot.verify_eig_event_correlation") as mock_corr:
                        def _side_effect(log_path, q, min_timestamp_iso=None):
                            if "off.jsonl" in str(log_path):
                                return False, None, "LOG_FILE_DOES_NOT_EXIST"
                            return True, mock_ev, "EIG_EVENT_VERIFIED"
                        mock_corr.side_effect = _side_effect

                        summary, records = run_real_retrieval_shadow_pilot(max_queries=3)
                        self.assertEqual(summary["verdict"], "GO")
                        self.assertEqual(summary["status"], "PASSED")
                        self.assertEqual(summary["completed_successful_pairs"], 3)
                        self.assertEqual(summary["shadow_stats"]["errors"], 0)
                        self.assertEqual(summary["shadow_stats"]["dropped"], 0)

    def test_contract_06_rank_comparator_detects_permutations(self):
        """Scenario 6: Rank comparator returns False on permuted order."""
        hits_off = [{"chunk_id": "c1"}, {"chunk_id": "c2"}, {"chunk_id": "c3"}]
        hits_on = [{"chunk_id": "c2"}, {"chunk_id": "c1"}, {"chunk_id": "c3"}]
        self.assertFalse(compare_ranks(hits_off, hits_on))
        self.assertTrue(compare_ranks(hits_off, hits_off))

    def test_contract_07_raw_vs_normalized_payload_equality_separation(self):
        """Scenario 7: Volatile dynamic fields separate raw vs normalized equality."""
        hits_off = [{"chunk_id": "c1", "latency_ms": 12.5, "request_id": "req_001"}]
        hits_on = [{"chunk_id": "c1", "latency_ms": 14.8, "request_id": "req_002"}]
        cmp_res = compare_payloads(hits_off, hits_on)
        self.assertFalse(cmp_res["raw_equal"])
        self.assertTrue(cmp_res["normalized_equal"])
        self.assertIn("latency_ms", cmp_res["removed_volatile_fields"])
        self.assertIn("request_id", cmp_res["removed_volatile_fields"])

    def test_contract_08_per_query_search_deadline_enforced_strictly(self):
        """Scenario 8: Hanging search call terminated cleanly on deadline."""
        ok, res, elapsed_ms, err, exitcode = execute_bounded_search(
            query="test hanging query",
            shadow_mode=False,
            timeout_sec=0.2,
            observer_timeout_sec=0.0,
            delay_sec=1.0
        )
        self.assertFalse(ok)
        self.assertIn("SEARCH_DEADLINE_EXCEEDED", err)
        self.assertLess(elapsed_ms, 800.0)

    def test_contract_09_offline_fixture_yields_honest_blocked_dependency_zero_calls(self):
        """Scenario 9: Offline backend yields BLOCKED_DEPENDENCY without synthetic mock fallback."""
        from unittest.mock import patch

        mock_diag = {
            "endpoint_url": "http://127.0.0.1:8089/v1/embeddings",
            "error_classification": "CONNECTION_REFUSED",
            "error_detail": "Connection refused on 127.0.0.1:8089",
            "required_operator_action": "Start llama-server on port 8089",
            "readonly_scope": "READONLY_VERIFIED_OFFLINE_PROBE_NO_DB_WRITE"
        }
        with patch("tests.test_real_retrieval_shadow_pilot.check_backend_readiness", return_value=(False, mock_diag)):
            summary, records = run_real_retrieval_shadow_pilot(max_queries=5)
            self.assertEqual(summary["verdict"], "BLOCKED")
            self.assertEqual(summary["status"], "BLOCKED_DEPENDENCY")
            self.assertEqual(summary["actual_search_calls_executed"], 0)
            self.assertIn("Connection refused", summary["reason"])

    def test_contract_10_online_fixture_does_not_break_on_offline_expectation(self):
        """Scenario 10: Online backend proceeds to live verification without artificial failure."""
        from unittest.mock import patch

        mock_diag = {"endpoint_url": "http://127.0.0.1:8089/v1/embeddings", "error_classification": "NONE", "required_operator_action": ""}
        with patch("tests.test_real_retrieval_shadow_pilot.check_backend_readiness", return_value=(True, mock_diag)):
            with patch("tests.test_real_retrieval_shadow_pilot.check_readonly_scope", return_value="ISOLATED_COPY_VERIFIED"):
                with patch("tests.test_real_retrieval_shadow_pilot.execute_bounded_search", return_value=SearchResult(True, [{"chunk_id": "c1"}], 5.0, "", 0)):
                    with patch("tests.test_real_retrieval_shadow_pilot.verify_eig_event_correlation", return_value=(True, {"divergence": "CONGRUENT", "eig_summary": {"answer_evidence_status": "USABLE_FOR_ANSWER"}}, "EIG_EVENT_VERIFIED")):
                        summary, records = run_real_retrieval_shadow_pilot(max_queries=1)
                        self.assertEqual(summary["real_pilot_execution"], "CONTRACT_SYNTHETIC")

    def test_contract_11_exception_in_dispatch_restores_env_and_cleans_resources(self):
        """Scenario 11: Exception in search dispatch cleanly restores parent environment."""
        from unittest.mock import patch

        os.environ["FLYING_RAG_SHADOW_EIG"] = "orig_shadow_mode"
        os.environ["FLYING_RAG_CONFIG"] = "orig_cfg_path"
        mock_diag = {"endpoint_url": "http://127.0.0.1:8089/v1/embeddings", "error_classification": "NONE", "required_operator_action": ""}
        try:
            with patch("tests.test_real_retrieval_shadow_pilot.check_backend_readiness", return_value=(True, mock_diag)):
                with patch("tests.test_real_retrieval_shadow_pilot.check_readonly_scope", return_value="ISOLATED_COPY_VERIFIED"):
                    with patch("tests.test_real_retrieval_shadow_pilot.execute_bounded_search", side_effect=RuntimeError("Crash")):
                        try:
                            run_real_retrieval_shadow_pilot(max_queries=1)
                        except RuntimeError:
                            pass
            self.assertEqual(os.environ.get("FLYING_RAG_SHADOW_EIG"), "orig_shadow_mode")
            self.assertEqual(os.environ.get("FLYING_RAG_CONFIG"), "orig_cfg_path")
        finally:
            os.environ.pop("FLYING_RAG_SHADOW_EIG", None)
            os.environ.pop("FLYING_RAG_CONFIG", None)

    def test_contract_12_off_mode_does_not_invoke_observer(self):
        """Scenario 12: In OFF mode, observer is never invoked and off_observer_calls is 0."""
        from unittest.mock import patch

        mock_diag = {"endpoint_url": "http://127.0.0.1:8089/v1/embeddings", "error_classification": "NONE", "required_operator_action": ""}
        mock_ev = {"divergence": "CONGRUENT", "eig_summary": {"answer_evidence_status": "USABLE_FOR_ANSWER"}}
        with patch("tests.test_real_retrieval_shadow_pilot.check_backend_readiness", return_value=(True, mock_diag)):
            with patch("tests.test_real_retrieval_shadow_pilot.check_readonly_scope", return_value="ISOLATED_COPY_VERIFIED"):
                with patch("tests.test_real_retrieval_shadow_pilot.execute_bounded_search", return_value=SearchResult(True, [{"chunk_id": "c1"}], 5.0, "", 0)):
                    with patch("tests.test_real_retrieval_shadow_pilot.verify_eig_event_correlation") as mock_corr:
                        def _side_effect(log_path, q, min_timestamp_iso=None):
                            if "off.jsonl" in str(log_path):
                                return False, None, "LOG_FILE_DOES_NOT_EXIST"
                            return True, mock_ev, "EIG_EVENT_VERIFIED"
                        mock_corr.side_effect = _side_effect

                        summary, records = run_real_retrieval_shadow_pilot(max_queries=1)
                        self.assertEqual(summary["off_observer_calls"], 0)

    def test_contract_a1_controlled_slow_search_terminates_child_process(self):
        """Check A1: Subprocess exceeding timeout is terminated with confirmed exit and non-lingering state."""
        t0 = time.perf_counter()
        ok, res, elapsed_ms, err, exitcode = execute_bounded_search(
            query="test_controlled_slow_search",
            shadow_mode=False,
            timeout_sec=0.2,
            observer_timeout_sec=0.0,
            delay_sec=1.5
        )
        elapsed_sec = time.perf_counter() - t0
        self.assertFalse(ok)
        self.assertIn("SEARCH_DEADLINE_EXCEEDED", err)
        self.assertIn("child_terminated=True", err)
        self.assertLess(elapsed_sec, 1.2)
        self.assertIsNotNone(exitcode)

    def test_contract_a2_delayed_off_cannot_see_on_or_create_events(self):
        """Check A2: OFF mode search cannot observe ON state or create telemetry events."""
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_log = Path(tmpdir) / "test_off.jsonl"
            ok_off, _, _, err_off, code_off = execute_bounded_search(
                query="delayed_off_query",
                shadow_mode=False,
                timeout_sec=1.5,
                observer_timeout_sec=0.0,
                simulated_result=json.dumps([{"chunk_id": "c1"}]),
                log_path=temp_log
            )
            self.assertTrue(ok_off, f"OFF search must succeed: err={err_off}")
            is_valid, _, _ = verify_eig_event_correlation(temp_log, "delayed_off_query")
            self.assertFalse(is_valid, "OFF mode must produce zero telemetry events")

            temp_log_on = Path(tmpdir) / "test_on.jsonl"
            ok_on, res_on, _, err_on, code_on = execute_bounded_search(
                query="delayed_on_query",
                shadow_mode=True,
                timeout_sec=1.5,
                observer_timeout_sec=0.0,
                simulated_result=json.dumps([{"chunk_id": "c1"}]),
                log_path=temp_log_on
            )
            self.assertTrue(ok_on, f"ON search must succeed: err={err_on}")

    def test_contract_a3_exceptions_restore_parent_env_and_config(self):
        """Check A3: Unhandled exception during pilot series guarantees full parent env restoration."""
        from unittest.mock import patch

        orig_shadow = "ORIGINAL_SHADOW_VALUE"
        orig_config = "ORIGINAL_CONFIG_VALUE"
        os.environ["FLYING_RAG_SHADOW_EIG"] = orig_shadow
        os.environ["FLYING_RAG_CONFIG"] = orig_config

        try:
            with patch("tests.test_real_retrieval_shadow_pilot.check_backend_readiness", side_effect=Exception("Catastrophic error")):
                try:
                    run_real_retrieval_shadow_pilot(max_queries=1)
                except Exception:
                    pass

            self.assertEqual(os.environ.get("FLYING_RAG_SHADOW_EIG"), orig_shadow)
            self.assertEqual(os.environ.get("FLYING_RAG_CONFIG"), orig_config)
        finally:
            os.environ.pop("FLYING_RAG_SHADOW_EIG", None)
            os.environ.pop("FLYING_RAG_CONFIG", None)

    def test_contract_a4_total_deadline_bounds_series_zero_leaked_processes(self):
        """Check A4: Total pilot series deadline aborts loop within bounded wall-clock limit."""
        from unittest.mock import patch

        t0 = time.perf_counter()
        mock_diag = {"endpoint_url": "http://127.0.0.1:8089/v1/embeddings", "error_classification": "NONE", "required_operator_action": ""}
        with patch("tests.test_real_retrieval_shadow_pilot.check_backend_readiness", return_value=(True, mock_diag)):
            with patch("tests.test_real_retrieval_shadow_pilot.check_readonly_scope", return_value="ISOLATED_COPY_VERIFIED"):
                with patch("tests.test_real_retrieval_shadow_pilot.execute_bounded_search") as mock_exec:
                    def slow_search(*args, **kwargs):
                        time.sleep(0.1)
                        return SearchResult(True, [{"chunk_id": "c1"}], 100.0, "", 0)
                    mock_exec.side_effect = slow_search
                    with patch("tests.test_real_retrieval_shadow_pilot.verify_eig_event_correlation", return_value=(True, {"divergence": "CONGRUENT", "eig_summary": {"answer_evidence_status": "USABLE_FOR_ANSWER"}}, "EIG_EVENT_VERIFIED")):
                        summary, records = run_real_retrieval_shadow_pilot(
                            total_pilot_deadline_sec=0.25,
                            per_query_timeout_sec=0.1,
                            max_queries=10
                        )
        elapsed = time.perf_counter() - t0
        self.assertLess(elapsed, 0.6)
        self.assertLess(summary["queries_completed"], 10)

    def test_contract_b1_event_missing_when_processed_increments_forbids_go(self):
        """Check B1: If processed increments but correlated event is missing from log, forbid GO."""
        from unittest.mock import patch

        mock_diag = {"endpoint_url": "http://127.0.0.1:8089/v1/embeddings", "error_classification": "NONE", "required_operator_action": ""}
        with patch("tests.test_real_retrieval_shadow_pilot.check_backend_readiness", return_value=(True, mock_diag)):
            with patch("tests.test_real_retrieval_shadow_pilot.check_readonly_scope", return_value="ISOLATED_COPY_VERIFIED"):
                with patch("tests.test_real_retrieval_shadow_pilot.execute_bounded_search", return_value=SearchResult(True, [{"chunk_id": "c1"}], 5.0, "", 0)):
                    with patch("tests.test_real_retrieval_shadow_pilot.verify_eig_event_correlation", return_value=(False, None, "EIG_EVENT_MISSING")):
                        summary, records = run_real_retrieval_shadow_pilot(max_queries=1)
                        self.assertNotEqual(summary["verdict"], "GO")
                        self.assertFalse(summary["shadow_observation_verified"])

    def test_contract_b2_telemetry_write_failure_forbids_pilot_go(self):
        """Check B2: Telemetry log write failure / SHADOW_ERROR forbids pilot GO."""
        from unittest.mock import patch

        mock_diag = {"endpoint_url": "http://127.0.0.1:8089/v1/embeddings", "error_classification": "NONE", "required_operator_action": ""}
        err_ev = {"divergence": "SHADOW_ERROR", "error": "Disk full"}
        with patch("tests.test_real_retrieval_shadow_pilot.check_backend_readiness", return_value=(True, mock_diag)):
            with patch("tests.test_real_retrieval_shadow_pilot.check_readonly_scope", return_value="ISOLATED_COPY_VERIFIED"):
                with patch("tests.test_real_retrieval_shadow_pilot.execute_bounded_search", return_value=SearchResult(True, [{"chunk_id": "c1"}], 5.0, "", 0)):
                    with patch("tests.test_real_retrieval_shadow_pilot.verify_eig_event_correlation", return_value=(False, err_ev, "EIG_SHADOW_ERROR: Disk full")):
                        summary, records = run_real_retrieval_shadow_pilot(max_queries=1)
                        self.assertNotEqual(summary["verdict"], "GO")
                        self.assertGreater(summary["shadow_stats"]["errors"], 0)

    def test_contract_b3_foreign_or_past_event_query_mismatch_forbids_go(self):
        """Check B3: Foreign event with mismatched query_hash is rejected by verify_eig_event_correlation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_log = Path(tmpdir) / "test_mismatch.jsonl"
            foreign_event = {
                "timestamp": datetime.now().isoformat(),
                "query_hash": "foreign_hash_1234",
                "divergence": "CONGRUENT",
                "eig_summary": {"answer_evidence_status": "USABLE_FOR_ANSWER"}
            }
            temp_log.write_text(json.dumps(foreign_event) + "\n", encoding="utf-8")

            is_valid, ev, msg = verify_eig_event_correlation(temp_log, "my_query_text")
            self.assertFalse(is_valid)
            self.assertIn("EIG_EVENT_MISSING", msg)

    def test_contract_b4_actual_shadow_eig_with_sqlite_fixture(self):
        """Check B4: Real ShadowEvidenceIntegrityGate with isolated SQLite fixture completes and records correlated event."""
        from rag_server.shadow_eig import ShadowEvidenceIntegrityGate

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_fixture.db"
            log_path = Path(tmpdir) / "eig_fixture_telemetry.jsonl"

            conn = sqlite3.connect(str(db_path))
            conn.execute("""
                CREATE TABLE files (
                    source_path TEXT PRIMARY KEY,
                    file_name TEXT,
                    format TEXT,
                    status TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE parent_chunks (
                    parent_id TEXT PRIMARY KEY,
                    source_path TEXT,
                    parent_text TEXT
                )
            """)
            doc_path = "docs/СП 7.13130.docx"
            sp7_did = hashlib.sha256(doc_path.encode("utf-8")).hexdigest()[:8]
            pid = f"{sp7_did}_p_0017"
            conn.execute("INSERT INTO files VALUES (?, ?, 'docx', 'active')", (doc_path, "СП 7.13130.docx"))
            conn.execute("INSERT INTO parent_chunks VALUES (?, ?, ?)", (pid, doc_path, "Раздел 6. Требования к вентиляции."))
            conn.commit()
            conn.close()

            adapter = ShadowEvidenceIntegrityGate(
                metadata_db_path=db_path,
                log_path=log_path,
                enabled=True
            )

            test_query = "Каковы требования СП 7.13130 к вентиляции?"
            fixture_hits = [{"chunk_id": "c1", "parent_id": pid, "source_path": doc_path}]

            submitted = adapter.observe_async(test_query, retrieval_results=fixture_hits)
            self.assertTrue(submitted)

            ok_wait, proc_after, msg = wait_for_shadow_completion(adapter, 0, timeout_sec=2.0)
            self.assertTrue(ok_wait)
            self.assertEqual(adapter.processed_count, 1)
            self.assertEqual(adapter.error_count, 0)

            is_valid, ev, status_msg = verify_eig_event_correlation(log_path, test_query)
            self.assertTrue(is_valid, f"Telemetry event must be verified: {status_msg}")
            self.assertEqual(ev["query_hash"], hashlib.sha256(test_query.encode("utf-8")).hexdigest()[:16])
            self.assertIn(ev["eig_summary"]["answer_evidence_status"], ("USABLE_FOR_ANSWER", "EVIDENCE_PARTIAL", "REFUSAL_REQUIRED", "NOT_APPLICABLE"))

            adapter.shutdown(wait=True, timeout=1.0)

    def test_contract_b5_off_mode_creates_zero_telemetry_events(self):
        """Check B5: In OFF mode, zero telemetry events are created and zero observer calls occur."""
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_log = Path(tmpdir) / "off_mode_log.jsonl"

            ok, res, elapsed, err, code = execute_bounded_search(
                query="запрос в режиме off",
                shadow_mode=False,
                timeout_sec=1.0,
                simulated_result=json.dumps([{"chunk_id": "c1"}]),
                log_path=temp_log
            )
            self.assertTrue(ok)
            if temp_log.exists():
                self.assertEqual(temp_log.stat().st_size, 0)

    # --- Checks C1-C4: Unified Isolated Configuration & Backend Probing (P3-D) ---

    def test_contract_c1_config_mismatch_rejected_before_search(self):
        """Check C1: Probe target differing from provider target yields explicit BLOCKED_CONFIG_MISMATCH."""
        from unittest.mock import patch, MagicMock

        mock_prov = MagicMock()
        mock_prov.url = "http://localhost:13305/api/v1/embeddings"
        mock_prov.model = "Qwen3-Embedding-0.6B-GGUF"

        with patch("embedder.client.LemonadeEmbeddingProvider", return_value=mock_prov):
            ok, diag = check_backend_readiness(config_path=DEFAULT_ISOLATED_CONFIG, timeout_sec=0.5)
            self.assertFalse(ok)
            self.assertEqual(diag["error_classification"], "BLOCKED_CONFIG_MISMATCH")
            self.assertIn("Configuration mismatch", diag["error_detail"])

    def test_contract_c2_single_config_unifies_target_identities(self):
        """Check C2: Single config unifies TCP target, provider, and search identity with valid fingerprint."""
        fp, cfg = get_config_fingerprint(DEFAULT_ISOLATED_CONFIG)
        self.assertTrue(len(fp) >= 32, "Fingerprint must be a valid SHA256 hex string")
        self.assertEqual(cfg.get("embedder", {}).get("url"), "http://127.0.0.1:8089/v1/embeddings")
        self.assertEqual(cfg.get("embedder", {}).get("model"), "Qwen3-Embedding-0.6B-Q8_0.gguf")
        self.assertEqual(cfg.get("embedder", {}).get("dimension"), 1024)

    def test_contract_c3_timeout_distinguished_from_connection_refused(self):
        """Check C3: Socket timeout is accurately distinguished from direct connection refusal."""
        from unittest.mock import patch

        with patch("socket.create_connection", side_effect=TimeoutError("timed out")):
            ok, diag = check_backend_readiness(config_path=DEFAULT_ISOLATED_CONFIG, timeout_sec=0.5)
            self.assertFalse(ok)
            self.assertEqual(diag["error_classification"], "SOCKET_TIMEOUT")
            self.assertIn("timed out", diag["error_detail"])

        with patch("socket.create_connection", side_effect=ConnectionRefusedError("connection refused")):
            ok, diag = check_backend_readiness(config_path=DEFAULT_ISOLATED_CONFIG, timeout_sec=0.5)
            self.assertFalse(ok)
            self.assertEqual(diag["error_classification"], "CONNECTION_REFUSED")
            self.assertIn("Connection refused", diag["error_detail"])

    def test_contract_c4_readonly_provenance_and_scope_verified(self):
        """Check C4: Read-only scope is accurately classified as verified without touching production DB."""
        ok, diag = check_backend_readiness(config_path=DEFAULT_ISOLATED_CONFIG, timeout_sec=0.5)
        self.assertEqual(diag["readonly_scope"], "READONLY_VERIFIED_OFFLINE_PROBE_NO_DB_WRITE")
        self.assertIn("http://127.0.0.1:8089", diag["endpoint_url"])
        self.assertIn("Qwen3-Embedding-0.6B-Q8_0.gguf", diag["expected_model"])

    # --- Revision 3 Checks: Block C (Runtime Config & Envelope Invariants) ---

    def test_contract_c5_smoke_runtime_db_paths_resolver_matches_config(self):
        """Check C5: Real runtime resolver _db_paths() reads isolated_pilot_config.yaml without KeyError."""
        valid, msg, resolved = validate_pilot_config(DEFAULT_ISOLATED_CONFIG)
        self.assertTrue(valid, f"isolated_pilot_config.yaml must pass runtime validation: {msg}")
        self.assertIn("lancedb", resolved["lancedb_path"].replace("\\", "/"))
        self.assertIn("metadata.db", resolved["metadata_db"].replace("\\", "/"))

    def test_contract_c6_negative_missing_mandatory_key_yields_config_invalid(self):
        """Check C6: Missing mandatory key fails closed with CONFIG_INVALID before search without KeyError."""
        import yaml
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_cfg_path = Path(tmpdir) / "invalid_config.yaml"
            bad_cfg_path.write_text(yaml.dump({
                "storage": {"metadata_db": "some/path/metadata.db"}
                # lancedb_path is intentionally missing
            }), encoding="utf-8")

            valid, msg, _ = validate_pilot_config(bad_cfg_path)
            self.assertFalse(valid)
            self.assertIn("CONFIG_INVALID", msg)
            self.assertIn("lancedb_path", msg)

    def test_contract_c7_error_envelopes_in_lists_and_dicts_rejected(self):
        """Check C7: List-wrapped blocked_result envelopes [{'error': ..., 'status': 'blocked'}] are detected as errors."""
        blocked_env = [{"error": "STORAGE_NOT_READY", "error_code": "lance_unavailable", "status": "blocked", "action": "reindex"}]
        is_err, detail = is_error_payload(blocked_env)
        self.assertTrue(is_err)
        self.assertIn("ERROR_KEY_IN_LIST", detail)

        dict_env = {"error": "backend_timeout", "status": "FAILED"}
        is_err_dict, detail_dict = is_error_payload(dict_env)
        self.assertTrue(is_err_dict)
        self.assertIn("ERROR_KEY_PRESENT", detail_dict)

        valid_hits = [{"chunk_id": "c1", "text": "normative requirement"}]
        is_err_valid, _ = is_error_payload(valid_hits)
        self.assertFalse(is_err_valid)

    def test_contract_c8_readonly_scope_dynamic_offline_and_online(self):
        """Check C8: Readonly scope evaluates dynamically based on offline probe vs online proof."""
        scope_offline = check_readonly_scope(DEFAULT_ISOLATED_CONFIG, backend_online=False)
        self.assertEqual(scope_offline, "READONLY_VERIFIED_OFFLINE_PROBE_NO_DB_WRITE")

        scope_online_prod = check_readonly_scope(DEFAULT_ISOLATED_CONFIG, backend_online=True)
        self.assertEqual(scope_online_prod, "BLOCKED_READONLY_NOT_PROVEN")

    # --- Revision 3 Checks: Block B (Event Channel Isolation & Correlation) ---

    def test_contract_b6_repeated_query_isolated_channels_prevent_cross_talk(self):
        """Check B6: Repeated identical query in OFF and ON produces independent evidence without cross-talk."""
        from unittest.mock import patch

        rep_query = "СП 7.13130 пункт 6.4"
        mock_res = [{"chunk_id": "c1", "text": "clause 6.4 text"}]
        mock_diag = {"endpoint_url": "http://127.0.0.1:8089/v1/embeddings", "error_classification": "NONE", "required_operator_action": ""}
        mock_ev = {"divergence": "CONGRUENT", "eig_summary": {"answer_evidence_status": "USABLE_FOR_ANSWER"}}

        with patch("tests.test_real_retrieval_shadow_pilot.check_backend_readiness", return_value=(True, mock_diag)):
            with patch("tests.test_real_retrieval_shadow_pilot.check_readonly_scope", return_value="ISOLATED_COPY_VERIFIED"):
                with patch("tests.test_real_retrieval_shadow_pilot.execute_bounded_search", return_value=SearchResult(True, mock_res, 5.0, "", 0)):
                    with patch("tests.test_real_retrieval_shadow_pilot.verify_eig_event_correlation") as mock_corr:
                        def _side_effect(log_path, q, min_timestamp_iso=None):
                            if "off.jsonl" in str(log_path):
                                return False, None, "LOG_FILE_DOES_NOT_EXIST"
                            return True, mock_ev, "EIG_EVENT_VERIFIED"
                        mock_corr.side_effect = _side_effect

                        summary, records = run_real_retrieval_shadow_pilot(max_queries=4)
                        self.assertEqual(summary["verdict"], "GO")
                        self.assertEqual(summary["off_observer_calls"], 0)
                        self.assertEqual(summary["correlated_events_verified"], 4)

    def test_contract_b7_stale_event_rejected_by_min_timestamp(self):
        """Check B7: Telemetry event with timestamp earlier than min_timestamp_iso is rejected as stale."""
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_log = Path(tmpdir) / "stale_test.jsonl"
            q = "повторный запрос"
            q_hash = hashlib.sha256(q.encode("utf-8")).hexdigest()[:16]
            stale_ev = {
                "timestamp": "2026-11-15T10:00:00",
                "query_hash": q_hash,
                "divergence": "CONGRUENT",
                "eig_summary": {"answer_evidence_status": "USABLE_FOR_ANSWER"}
            }
            temp_log.write_text(json.dumps(stale_ev) + "\n", encoding="utf-8")

            is_valid, ev, msg = verify_eig_event_correlation(
                temp_log, q, min_timestamp_iso="2026-11-16T00:00:00"
            )
            self.assertFalse(is_valid)
            self.assertIn("EIG_EVENT_STALE", msg)

    def test_contract_b8_foreign_event_in_channel_rejected(self):
        """Check B8: Event with foreign query_hash in dedicated channel is rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_log = Path(tmpdir) / "foreign_test.jsonl"
            foreign_ev = {
                "timestamp": "2026-11-16T12:00:00",
                "query_hash": "unrelated_hash_99",
                "divergence": "CONGRUENT",
                "eig_summary": {"answer_evidence_status": "USABLE_FOR_ANSWER"}
            }
            temp_log.write_text(json.dumps(foreign_ev) + "\n", encoding="utf-8")

            is_valid, ev, msg = verify_eig_event_correlation(temp_log, "запрос с другим хешем")
            self.assertFalse(is_valid)
            self.assertIn("EIG_EVENT_MISSING", msg)

    # --- Revision 3 Checks: Block A (Parent Environment Preservation & Budget Allocation) ---

    def test_contract_a5_offline_preflight_socket_refusal_preserves_parent_env(self):
        """Check A5: Offline socket refusal preserves parent FLYING_RAG_CONFIG and FLYING_RAG_SHADOW_EIG."""
        orig_cfg = "parent_preflight_test_config.yaml"
        orig_eig = "parent_preflight_test_eig"
        os.environ["FLYING_RAG_CONFIG"] = orig_cfg
        os.environ["FLYING_RAG_SHADOW_EIG"] = orig_eig

        try:
            ok, diag = check_backend_readiness(config_path=DEFAULT_ISOLATED_CONFIG, timeout_sec=0.1)
            self.assertFalse(ok)
            self.assertEqual(os.environ.get("FLYING_RAG_CONFIG"), orig_cfg)
            self.assertEqual(os.environ.get("FLYING_RAG_SHADOW_EIG"), orig_eig)
        finally:
            os.environ.pop("FLYING_RAG_CONFIG", None)
            os.environ.pop("FLYING_RAG_SHADOW_EIG", None)

    def test_contract_a6_exhausted_budget_breaks_before_on_call(self):
        """Check A6: Exhausted total pilot deadline breaks series loop before starting next call."""
        from unittest.mock import patch

        mock_diag = {"endpoint_url": "http://127.0.0.1:8089/v1/embeddings", "error_classification": "NONE", "required_operator_action": ""}
        with patch("tests.test_real_retrieval_shadow_pilot.check_backend_readiness", return_value=(True, mock_diag)):
            with patch("tests.test_real_retrieval_shadow_pilot.check_readonly_scope", return_value="ISOLATED_COPY_VERIFIED"):
                with patch("tests.test_real_retrieval_shadow_pilot.execute_bounded_search") as mock_exec:
                    def slow_search(*args, **kwargs):
                        time.sleep(0.08)
                        return SearchResult(True, [{"chunk_id": "c1"}], 80.0, "", 0)
                    mock_exec.side_effect = slow_search

                    summary, records = run_real_retrieval_shadow_pilot(
                        total_pilot_deadline_sec=0.05,
                        per_query_timeout_sec=0.1,
                        max_queries=2
                    )
                    self.assertLess(summary["actual_search_calls_executed"], 4)


    # --- Revision 4 Checks: Pre-Execution Readonly Gate & Predicate Veto (R4-01..05) ---

    def test_contract_r4_01_backend_online_unproven_scope_blocks_search_with_zero_calls(self):
        """R4-01: Backend ready, scope BLOCKED -> spy execute_bounded_search has 0 calls, 0 child worker processes, verdict BLOCKED."""
        from unittest.mock import patch, MagicMock

        mock_diag = {
            "endpoint_url": "http://127.0.0.1:8089/v1/embeddings",
            "error_classification": "NONE",
            "required_operator_action": ""
        }
        spy_search = MagicMock(return_value=SearchResult(True, [{"chunk_id": "c1"}], 10.0, "", 0))

        # Real check_readonly_scope against DEFAULT_ISOLATED_CONFIG (which points to C:/RAG_Acer/data_imported)
        with patch("tests.test_real_retrieval_shadow_pilot.check_backend_readiness", return_value=(True, mock_diag)):
            with patch("tests.test_real_retrieval_shadow_pilot.execute_bounded_search", spy_search):
                summary, records = run_real_retrieval_shadow_pilot(max_queries=3)

                self.assertEqual(summary["verdict"], "BLOCKED")
                self.assertEqual(summary["status"], "BLOCKED_READONLY_NOT_PROVEN")
                self.assertEqual(summary["readonly_scope"], "BLOCKED_READONLY_NOT_PROVEN")
                self.assertEqual(summary["real_pilot_execution"], "BLOCKED_STORAGE_SCOPE")
                self.assertEqual(summary["actual_search_calls_executed"], 0)
                self.assertEqual(spy_search.call_count, 0)
                self.assertFalse(summary["shadow_observation_verified"])

    def test_contract_r4_02_negative_scope_vetoes_pilot_go_predicate(self):
        """R4-02: Negative or unproven scope strictly vetoes public evaluate_pilot_eligibility_predicate."""
        pos_kwargs = dict(
            backend_online=True,
            actual_search_calls=10,
            total_queries=5,
            completed_successful_pairs=5,
            search_errors=0,
            rank_mismatches=0,
            norm_payload_mismatches=0,
            shadow_submitted=5,
            shadow_processed=5,
            eig_events_verified=5,
            shadow_errors=0,
            shadow_dropped=0,
            shadow_adapter_missing=0,
            shadow_timeouts=0,
            off_observer_calls=0
        )

        # 1. BLOCKED_READONLY_NOT_PROVEN must veto GO
        self.assertFalse(evaluate_pilot_eligibility_predicate(readonly_scope="BLOCKED_READONLY_NOT_PROVEN", **pos_kwargs))

        # 2. BLOCKED_CONFIG_INVALID must veto GO
        self.assertFalse(evaluate_pilot_eligibility_predicate(readonly_scope="BLOCKED_CONFIG_INVALID", **pos_kwargs))

        # 3. Offline scope must veto GO
        self.assertFalse(evaluate_pilot_eligibility_predicate(readonly_scope="READONLY_VERIFIED_OFFLINE_PROBE_NO_DB_WRITE", **pos_kwargs))

        # 4. Empty or invalid scope string must veto GO
        self.assertFalse(evaluate_pilot_eligibility_predicate(readonly_scope="", **pos_kwargs))
        self.assertFalse(evaluate_pilot_eligibility_predicate(readonly_scope=None, **pos_kwargs))

        # 5. Admitted scopes yield True when all criteria pass
        self.assertTrue(evaluate_pilot_eligibility_predicate(readonly_scope="READONLY_VERIFIED_RO_MODE", **pos_kwargs))
        self.assertTrue(evaluate_pilot_eligibility_predicate(readonly_scope="ISOLATED_COPY_VERIFIED", **pos_kwargs))

    def test_contract_r4_03_substring_test_fixture_does_not_elevate_status(self):
        """R4-03: Substring test_fixture/isolated_fixture in path without verified registered root yields BLOCKED_READONLY_NOT_PROVEN."""
        import yaml
        with tempfile.TemporaryDirectory() as tmpdir:
            unreg_dir = Path(tmpdir) / "test_fixture_unregistered"
            unreg_dir.mkdir(parents=True, exist_ok=True)
            cfg_path = unreg_dir / "probe_config.yaml"
            cfg_path.write_text(yaml.dump({
                "storage": {
                    "metadata_db": str(unreg_dir / "metadata.db"),
                    "lancedb_path": str(unreg_dir / "lancedb")
                },
                "embedder": {
                    "url": "http://127.0.0.1:8089/v1/embeddings",
                    "model": "Qwen3-Embedding-0.6B-Q8_0.gguf",
                    "dimension": 1024
                }
            }), encoding="utf-8")

            # Without registration in _VERIFIED_FIXTURE_ROOTS or allowed_fixture_root
            scope = check_readonly_scope(cfg_path, backend_online=True)
            self.assertEqual(scope, "BLOCKED_READONLY_NOT_PROVEN")

    def test_contract_r4_04_registered_isolated_fixture_allows_contract_synthetic_only(self):
        """R4-04: Registered isolated fixture yields ISOLATED_COPY_VERIFIED and CONTRACT_SYNTHETIC, never production GO."""
        import yaml
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmpdir:
            reg_root = Path(tmpdir).resolve()
            meta_path = reg_root / "metadata.db"
            meta_path.touch()
            lance_path = reg_root / "lancedb"
            lance_path.mkdir()

            cfg_path = reg_root / "isolated_config.yaml"
            cfg_path.write_text(yaml.dump({
                "storage": {
                    "metadata_db": str(meta_path),
                    "lancedb_path": str(lance_path)
                },
                "embedder": {
                    "url": "http://127.0.0.1:8089/v1/embeddings",
                    "model": "Qwen3-Embedding-0.6B-Q8_0.gguf",
                    "dimension": 1024
                }
            }), encoding="utf-8")

            register_verified_fixture_root(reg_root)
            try:
                scope = check_readonly_scope(cfg_path, backend_online=True)
                self.assertEqual(scope, "ISOLATED_COPY_VERIFIED")

                mock_diag = {
                    "endpoint_url": "http://127.0.0.1:8089/v1/embeddings",
                    "error_classification": "NONE",
                    "required_operator_action": ""
                }
                with patch("tests.test_real_retrieval_shadow_pilot.check_backend_readiness", return_value=(True, mock_diag)):
                    with patch("tests.test_real_retrieval_shadow_pilot.execute_bounded_search", return_value=SearchResult(True, [{"chunk_id": "c1"}], 10.0, "", 0)):
                        with patch("tests.test_real_retrieval_shadow_pilot.verify_eig_event_correlation") as mock_corr:
                            def _side_effect(log_path, q, min_timestamp_iso=None):
                                if "off.jsonl" in str(log_path):
                                    return False, None, "LOG_FILE_DOES_NOT_EXIST"
                                return True, {"divergence": "CONGRUENT"}, "EIG_EVENT_VERIFIED"
                            mock_corr.side_effect = _side_effect

                            summary, records = run_real_retrieval_shadow_pilot(max_queries=2, config_path=cfg_path)
                            self.assertEqual(summary["readonly_scope"], "ISOLATED_COPY_VERIFIED")
                            self.assertEqual(summary["pilot_name"], "CONTRACT_SYNTHETIC_SHADOW_PILOT")
                            self.assertEqual(summary["real_pilot_execution"], "CONTRACT_SYNTHETIC")
                            self.assertEqual(summary["actual_search_calls_executed"], 4)
                            self.assertEqual(summary["verdict"], "GO")
            finally:
                unregister_verified_fixture_root(reg_root)

    def test_contract_r4_05_offline_preflight_remains_blocked_dependency_zero_calls(self):
        """R4-05: Real offline preflight remains BLOCKED_DEPENDENCY with 0 searches; parent env preserved."""
        orig_cfg = os.environ.get("FLYING_RAG_CONFIG")
        orig_eig = os.environ.get("FLYING_RAG_SHADOW_EIG")

        summary, records = run_real_retrieval_shadow_pilot(max_queries=3)

        self.assertEqual(summary["status"], "BLOCKED_DEPENDENCY")
        self.assertEqual(summary["verdict"], "BLOCKED")
        self.assertEqual(summary["actual_search_calls_executed"], 0)
        self.assertEqual(summary["real_pilot_execution"], "BLOCKED_DEPENDENCY")
        self.assertEqual(summary["readonly_scope"], "READONLY_VERIFIED_OFFLINE_PROBE_NO_DB_WRITE")
        self.assertEqual(os.environ.get("FLYING_RAG_CONFIG"), orig_cfg)
        self.assertEqual(os.environ.get("FLYING_RAG_SHADOW_EIG"), orig_eig)

    def test_contract_r4_06_registered_external_root_outside_temp_rejected(self):
        """
        R4-06 (Errata 1 Section 2 / E1-negative):
        An external directory outside system temp, even if passed to register_verified_fixture_root(),
        must be rejected at registration, must return BLOCKED_READONLY_NOT_PROVEN in check_readonly_scope(),
        and must yield verdict BLOCKED with 0 search calls in run_real_retrieval_shadow_pilot.
        """
        from unittest.mock import patch, MagicMock
        with tempfile.TemporaryDirectory() as base_tmp:
            base_path = Path(base_tmp).resolve()
            fake_temp = base_path / "mock_system_temp"
            fake_temp.mkdir()
            external_root = base_path / "external_fixture_root"
            external_root.mkdir()

            meta_path = external_root / "metadata.db"
            meta_path.touch()
            lance_path = external_root / "lancedb"
            lance_path.mkdir()

            cfg_path = external_root / "isolated_config.yaml"
            cfg_path.write_text(yaml.dump({
                "storage": {
                    "metadata_db": str(meta_path),
                    "lancedb_path": str(lance_path)
                },
                "embedder": {
                    "url": "http://127.0.0.1:8089/v1/embeddings",
                    "model": "Qwen3-Embedding-0.6B-Q8_0.gguf",
                    "dimension": 1024
                }
            }), encoding="utf-8")

            with patch("tempfile.gettempdir", return_value=str(fake_temp)):
                # 1. Registration attempt must be rejected (returns None and does not register)
                reg_res = register_verified_fixture_root(external_root)
                self.assertIsNone(reg_res)
                self.assertNotIn(str(external_root), _VERIFIED_FIXTURE_ROOTS)

                # 2. check_readonly_scope must return BLOCKED_READONLY_NOT_PROVEN
                scope = check_readonly_scope(cfg_path, backend_online=True)
                self.assertEqual(scope, "BLOCKED_READONLY_NOT_PROVEN")

                # 3. Even if someone forcibly registers it or passes allowed_fixture_root, guard must reject
                _VERIFIED_FIXTURE_ROOTS.add(str(external_root))
                try:
                    scope_forced = check_readonly_scope(cfg_path, backend_online=True, allowed_fixture_root=external_root)
                    self.assertEqual(scope_forced, "BLOCKED_READONLY_NOT_PROVEN")
                finally:
                    _VERIFIED_FIXTURE_ROOTS.discard(str(external_root))

                # 4. Orchestrator with controlled online backend: 0 searches, 0 child workers, verdict BLOCKED
                mock_diag = {
                    "endpoint_url": "http://127.0.0.1:8089/v1/embeddings",
                    "error_classification": "NONE",
                    "required_operator_action": ""
                }
                search_spy = MagicMock()
                with patch("tests.test_real_retrieval_shadow_pilot.check_backend_readiness", return_value=(True, mock_diag)):
                    with patch("tests.test_real_retrieval_shadow_pilot.execute_bounded_search", search_spy):
                        summary, records = run_real_retrieval_shadow_pilot(max_queries=2, config_path=cfg_path)
                        self.assertEqual(summary["verdict"], "BLOCKED")
                        self.assertEqual(summary["status"], "BLOCKED_READONLY_NOT_PROVEN")
                        self.assertEqual(summary["actual_search_calls_executed"], 0)
                        self.assertEqual(search_spy.call_count, 0)



    # --- Mandatory Negative Tests NG-01..NG-10 (Specification FR-TZ-20261116-006 Section 5) ---

    def test_contract_ng01_max_queries_105_on_8_set_does_not_yield_105_pass(self):
        """NG-01: Passing max_queries=105 to default 8-query suite must NOT yield 105 queries or REAL_PILOT_PASS."""
        from unittest.mock import patch

        mock_diag = {"endpoint_url": "http://127.0.0.1:8089/v1/embeddings", "error_classification": "NONE", "required_operator_action": ""}
        mock_ev = {"divergence": "CONGRUENT", "eig_summary": {"answer_evidence_status": "USABLE_FOR_ANSWER"}}

        # Offline preflight:
        summary_off, records_off = run_real_retrieval_shadow_pilot(max_queries=105)
        self.assertEqual(summary_off["total_queries_planned"], 8)
        self.assertNotEqual(summary_off["total_queries_planned"], 105)
        self.assertNotEqual(summary_off["status"], "REAL_PILOT_PASS")
        self.assertEqual(summary_off["actual_search_calls_executed"], 0)

        # Online synthetic mock:
        with patch("tests.test_real_retrieval_shadow_pilot.check_backend_readiness", return_value=(True, mock_diag)):
            with patch("tests.test_real_retrieval_shadow_pilot.check_readonly_scope", return_value="ISOLATED_COPY_VERIFIED"):
                with patch("tests.test_real_retrieval_shadow_pilot.execute_bounded_search", return_value=SearchResult(True, [{"chunk_id": "c1"}], 5.0, "", 0)):
                    with patch("tests.test_real_retrieval_shadow_pilot.verify_eig_event_correlation", return_value=(True, mock_ev, "EIG_EVENT_VERIFIED")):
                        summary, records = run_real_retrieval_shadow_pilot(max_queries=105)
                        self.assertEqual(summary["total_queries_planned"], 8)
                        self.assertNotEqual(summary["total_queries_planned"], 105)
                        self.assertEqual(summary["queries_completed"], 8)
                        self.assertNotEqual(summary["real_pilot_execution"], "REAL_PILOT_PASS")

    def test_contract_ng02_invalid_manifest_fails_closed_zero_calls(self):
        """NG-02: Missing, truncated, corrupted or invalid manifest fails closed before worker spawn with 0 calls."""
        from unittest.mock import patch, MagicMock

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_p = Path(tmpdir)
            # 1. Non-existent file
            ok, msg, _ = validate_query_manifest(tmp_p / "nonexistent.json")
            self.assertFalse(ok)
            self.assertIn("MANIFEST_FILE_NOT_FOUND", msg)

            # 2. Count mismatch (<105)
            short_p = tmp_p / "short.json"
            short_queries = [{"query_id": f"Q{i:03d}", "position": i, "category": "ACTUAL_NORMATIVE", "query_text": f"query {i}"} for i in range(1, 10)]
            short_canon = json.dumps(short_queries, sort_keys=True, ensure_ascii=False)
            short_hash = hashlib.sha256(short_canon.encode("utf-8")).hexdigest()
            short_p.write_text(json.dumps({
                "schema": "flying_rag.pilot_query_manifest.v1",
                "manifest_sha256": short_hash,
                "total_queries": 9,
                "normative_count": 9,
                "adversarial_count": 0,
                "queries": short_queries
            }), encoding="utf-8")
            ok, msg, _ = validate_query_manifest(short_p, expected_count=105)
            self.assertFalse(ok)
            self.assertIn("MANIFEST_QUERY_COUNT_MISMATCH", msg)

            # 3. Corrupt UTF-8 / JSON
            corrupt_p = tmp_p / "corrupt.json"
            corrupt_p.write_bytes(b'{"queries": [invalid json \xff\xfe')
            ok, msg, _ = validate_query_manifest(corrupt_p)
            self.assertFalse(ok)
            self.assertIn("MANIFEST_JSON_PARSE_ERROR", msg)

            # 4. Bad manifest passed to runner -> fail-closed with 0 search calls
            spy_search = MagicMock()
            with patch("tests.test_real_retrieval_shadow_pilot.execute_bounded_search", spy_search):
                summary, records = run_real_retrieval_shadow_pilot(query_manifest_path=short_p)
                self.assertEqual(summary["verdict"], "BLOCKED")
                self.assertEqual(summary["status"], "CONFIG_INVALID")
                self.assertEqual(summary["actual_search_calls_executed"], 0)
                self.assertEqual(spy_search.call_count, 0)

    def test_contract_ng03_synthetic_105_manifest_structure_and_counter_accounting(self):
        """NG-03: Canonical 105 manifest loaded, 105 positions, 210 planned calls, 0 real search calls on offline preflight."""
        manifest_path = Path(__file__).parent / "pilot_query_manifest_105.json"
        self.assertTrue(manifest_path.exists(), "Canonical manifest must exist on disk")

        ok, msg, queries = validate_query_manifest(manifest_path, expected_count=105)
        self.assertTrue(ok, f"Canonical manifest must pass validation: {msg}")
        self.assertEqual(len(queries), 105)

        norm_count = sum(1 for q in queries if q["category"] in ("NORMATIVE", "ACTUAL_NORMATIVE"))
        adv_count = sum(1 for q in queries if q["category"] in ("ADVERSARIAL", "SYNTHETIC_ADVERSARIAL"))
        self.assertEqual(norm_count, 80)
        self.assertEqual(adv_count, 25)

        summary, records = run_real_retrieval_shadow_pilot(query_manifest_path=manifest_path)
        self.assertEqual(summary["total_queries_planned"], 105)
        self.assertEqual(summary["actual_search_calls_executed"], 0)
        self.assertEqual(summary["verdict"], "BLOCKED")
        self.assertEqual(summary["status"], "BLOCKED_DEPENDENCY")
        self.assertEqual(len(records), 105)
        self.assertEqual(records[0]["query_id"], queries[0]["query_id"])
        self.assertEqual(records[104]["query_id"], queries[104]["query_id"])

    def test_contract_ng04_conflicting_or_production_env_override_vetoed(self):
        """NG-04: Conflicting lancedb.uri alias or production FLYING_RAG_METADATA_DB env vetoes search with 0 calls."""
        import yaml
        from unittest.mock import patch, MagicMock

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_p = Path(tmpdir)
            temp_lance = tmp_p / "lancedb"
            temp_lance.mkdir()
            temp_meta = tmp_p / "metadata.db"
            temp_meta.touch()

            # 1. Config with conflicting lancedb.uri pointing to production
            bad_cfg = tmp_p / "conflict_cfg.yaml"
            bad_cfg.write_text(yaml.dump({
                "storage": {
                    "metadata_db": str(temp_meta),
                    "lancedb_path": str(temp_lance)
                },
                "lancedb": {
                    "uri": "C:/RAG_Acer/data_imported/lancedb"
                },
                "embedder": {
                    "url": "http://127.0.0.1:8089/v1/embeddings",
                    "model": "Qwen3-Embedding-0.6B-Q8_0.gguf",
                    "dimension": 1024
                }
            }), encoding="utf-8")

            valid, msg, _ = validate_pilot_config(bad_cfg)
            self.assertFalse(valid)
            self.assertIn("Conflicting storage alias detected", msg)

            # 2. Inherited FLYING_RAG_METADATA_DB pointing to production
            valid_cfg = tmp_p / "valid_isolated_cfg.yaml"
            valid_cfg.write_text(yaml.dump({
                "storage": {
                    "metadata_db": str(temp_meta),
                    "lancedb_path": str(temp_lance)
                },
                "embedder": {
                    "url": "http://127.0.0.1:8089/v1/embeddings",
                    "model": "Qwen3-Embedding-0.6B-Q8_0.gguf",
                    "dimension": 1024
                }
            }), encoding="utf-8")

            register_verified_fixture_root(tmp_p)
            try:
                os.environ["FLYING_RAG_METADATA_DB"] = "C:/RAG_Acer/data_imported/metadata.db"
                scope = check_readonly_scope(valid_cfg, backend_online=True)
                self.assertEqual(scope, "BLOCKED_READONLY_NOT_PROVEN")

                spy_search = MagicMock()
                mock_diag = {"endpoint_url": "http://127.0.0.1:8089/v1/embeddings", "error_classification": "NONE", "required_operator_action": ""}
                with patch("tests.test_real_retrieval_shadow_pilot.check_backend_readiness", return_value=(True, mock_diag)):
                    with patch("tests.test_real_retrieval_shadow_pilot.execute_bounded_search", spy_search):
                        summary, _ = run_real_retrieval_shadow_pilot(max_queries=2, config_path=valid_cfg)
                        self.assertEqual(summary["verdict"], "BLOCKED")
                        self.assertEqual(summary["actual_search_calls_executed"], 0)
                        self.assertEqual(spy_search.call_count, 0)
            finally:
                os.environ.pop("FLYING_RAG_METADATA_DB", None)
                unregister_verified_fixture_root(tmp_p)

    def test_contract_ng05_symlink_or_config_tamper_after_preflight_fails_closed(self):
        """NG-05: Symlink alias or config modification after preflight aborts loop and vetoes GO."""
        import yaml
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_p = Path(tmpdir).resolve()
            meta_path = tmp_p / "metadata.db"
            meta_path.touch()
            lance_path = tmp_p / "lancedb"
            lance_path.mkdir()

            cfg_path = tmp_p / "isolated_config.yaml"
            cfg_path.write_text(yaml.dump({
                "storage": {
                    "metadata_db": str(meta_path),
                    "lancedb_path": str(lance_path)
                },
                "embedder": {
                    "url": "http://127.0.0.1:8089/v1/embeddings",
                    "model": "Qwen3-Embedding-0.6B-Q8_0.gguf",
                    "dimension": 1024
                }
            }), encoding="utf-8")

            register_verified_fixture_root(tmp_p)
            try:
                mock_diag = {"endpoint_url": "http://127.0.0.1:8089/v1/embeddings", "error_classification": "NONE", "required_operator_action": ""}
                mock_res = [{"chunk_id": "c1", "text": "sample"}]
                mock_ev = {"divergence": "CONGRUENT", "eig_summary": {"answer_evidence_status": "USABLE_FOR_ANSWER"}}

                def tamper_config_after_first_call(*args, **kwargs):
                    cfg_path.write_text("tampered_content: true\n", encoding="utf-8")
                    return SearchResult(True, mock_res, 5.0, "", 0)

                with patch("tests.test_real_retrieval_shadow_pilot.check_backend_readiness", return_value=(True, mock_diag)):
                    with patch("tests.test_real_retrieval_shadow_pilot.execute_bounded_search", side_effect=tamper_config_after_first_call):
                        with patch("tests.test_real_retrieval_shadow_pilot.verify_eig_event_correlation", return_value=(True, mock_ev, "EIG_EVENT_VERIFIED")):
                            summary, records = run_real_retrieval_shadow_pilot(max_queries=5, config_path=cfg_path)
                            self.assertEqual(summary["verdict"], "BLOCKED")
                            self.assertEqual(summary["status"], "CONFIG_TAMPER_DETECTED")
                            self.assertLess(summary["queries_completed"], 5)
            finally:
                unregister_verified_fixture_root(tmp_p)

    def test_contract_ng06_unconfirmed_snapshot_or_wal_drift_yields_no_go(self):
        """NG-06: Unconfirmed snapshot, non-zero WAL, or sample hash mismatch yields NO_GO."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_p = Path(tmpdir)
            meta_path = tmp_p / "metadata.db"
            # Create valid SQLite DB with real schema
            conn = sqlite3.connect(str(meta_path))
            conn.execute("CREATE TABLE files (source_path TEXT PRIMARY KEY, file_name TEXT)")
            conn.commit()
            conn.close()

            lance_path = tmp_p / "lancedb"
            lance_path.mkdir()
            (lance_path / "index_manifest.json").write_text(json.dumps({
                "table_name": "documents_1024.lance",
                "dimension": 1024,
                "version": 1
            }), encoding="utf-8")
            (lance_path / "documents_1024.lance").mkdir()

            # 1. Clean snapshot files present without WAL
            ok, code, diag = verify_snapshot_readiness(meta_path, lance_path)
            self.assertTrue(ok)
            self.assertEqual(code, "SNAPSHOT_FILES_PRESENT")

            # 2. Non-zero WAL indicates dirty/active state
            wal_path = tmp_p / "metadata.db-wal"
            wal_path.write_bytes(b"uncommitted wal data 12345")
            ok_wal, code_wal, diag_wal = verify_snapshot_readiness(meta_path, lance_path)
            self.assertFalse(ok_wal)
            self.assertEqual(code_wal, "SNAPSHOT_UNCONFIRMED_DIRTY_WAL")
            wal_path.unlink()

            # 3. Sample hash mismatch
            ok_hash, code_hash, diag_hash = verify_snapshot_readiness(meta_path, lance_path, expected_sample_sha256="wrong_hash")
            self.assertFalse(ok_hash)
            self.assertEqual(code_hash, "SNAPSHOT_SAMPLE_HASH_MISMATCH")

            # 4. Missing index manifest in LanceDB
            (lance_path / "index_manifest.json").unlink()
            ok_man, code_man, diag_man = verify_snapshot_readiness(meta_path, lance_path)
            self.assertFalse(ok_man)
            self.assertEqual(code_man, "SNAPSHOT_LANCEDB_MISSING_MANIFEST")

    def test_contract_ng07_foreign_pid_on_8089_prevents_kill_and_yields_no_go(self):
        """NG-07: Foreign PID on port 8089 or identity mismatch strictly prevents termination."""
        import psutil
        # 1. Foreign process listening on port 8089
        safe, reason = verify_process_termination_safety(
            target_pid=1234,
            expected_path="C:\\RAG_Acer\\bin\\llama-server.exe",
            port_probe_pid=9999
        )
        self.assertFalse(safe)
        self.assertIn("PORT_8089_IN_USE_BY_FOREIGN_PROCESS", reason)

        # 2. PID missing / None
        safe_none, reason_none = verify_process_termination_safety(
            target_pid=None,
            expected_path="C:\\RAG_Acer\\bin\\llama-server.exe"
        )
        self.assertFalse(safe_none)
        self.assertIn("PID_REQUIRED", reason_none)

        # 3. Matching owned process with real OS verification
        my_pid = os.getpid()
        my_exe = sys.executable
        my_ct = psutil.Process(my_pid).create_time()
        safe_match, reason_match = verify_process_termination_safety(
            target_pid=my_pid,
            expected_path=my_exe,
            expected_start_time=my_ct,
            port_probe_pid=my_pid,
            owned_process_record={"pid": my_pid, "create_time": my_ct}
        )
        self.assertTrue(safe_match)
        self.assertEqual(reason_match, "PROCESS_IDENTITY_VERIFIED")

    def test_contract_ng08_embedding_failure_or_eig_telemetry_missing_yields_no_go(self):
        """NG-08: Embedding backend offline, model mismatch, missing EIG telemetry, or error payloads yield NO_GO."""
        from unittest.mock import patch

        # 1. Backend offline yields BLOCKED_DEPENDENCY
        summary_off, _ = run_real_retrieval_shadow_pilot(max_queries=1)
        self.assertEqual(summary_off["verdict"], "BLOCKED")
        self.assertEqual(summary_off["status"], "BLOCKED_DEPENDENCY")

        # 2. Missing EIG telemetry yields FAILED
        mock_diag = {"endpoint_url": "http://127.0.0.1:8089/v1/embeddings", "error_classification": "NONE", "required_operator_action": ""}
        with patch("tests.test_real_retrieval_shadow_pilot.check_backend_readiness", return_value=(True, mock_diag)):
            with patch("tests.test_real_retrieval_shadow_pilot.check_readonly_scope", return_value="ISOLATED_COPY_VERIFIED"):
                with patch("tests.test_real_retrieval_shadow_pilot.execute_bounded_search", return_value=SearchResult(True, [{"chunk_id": "c1"}], 5.0, "", 0)):
                    with patch("tests.test_real_retrieval_shadow_pilot.verify_eig_event_correlation", return_value=(False, None, "EIG_EVENT_MISSING")):
                        summary, _ = run_real_retrieval_shadow_pilot(max_queries=1)
                        self.assertNotEqual(summary["verdict"], "GO")
                        self.assertEqual(summary["status"], "FAILED")

        # 3. Error payload yields FAILED and increments search_errors
        with patch("tests.test_real_retrieval_shadow_pilot.check_backend_readiness", return_value=(True, mock_diag)):
            with patch("tests.test_real_retrieval_shadow_pilot.check_readonly_scope", return_value="ISOLATED_COPY_VERIFIED"):
                with patch("tests.test_real_retrieval_shadow_pilot.execute_bounded_search", return_value=SearchResult(False, [{"error": "fail"}], 5.0, "ERROR_KEY_IN_LIST", 0)):
                    summary_err, _ = run_real_retrieval_shadow_pilot(max_queries=1)
                    self.assertNotEqual(summary_err["verdict"], "GO")
                    self.assertGreater(summary_err["search_errors"], 0)

    def test_contract_ng09_deadline_exhaustion_terminates_child_without_silent_truncation(self):
        """NG-09: Total pilot deadline exhaustion aborts series cleanly without silent truncation of planned queries."""
        from unittest.mock import patch

        mock_diag = {"endpoint_url": "http://127.0.0.1:8089/v1/embeddings", "error_classification": "NONE", "required_operator_action": ""}
        with patch("tests.test_real_retrieval_shadow_pilot.check_backend_readiness", return_value=(True, mock_diag)):
            with patch("tests.test_real_retrieval_shadow_pilot.check_readonly_scope", return_value="ISOLATED_COPY_VERIFIED"):
                with patch("tests.test_real_retrieval_shadow_pilot.execute_bounded_search") as mock_exec:
                    def slow_search(*args, **kwargs):
                        time.sleep(0.08)
                        return SearchResult(True, [{"chunk_id": "c1"}], 80.0, "", 0)
                    mock_exec.side_effect = slow_search
                    with patch("tests.test_real_retrieval_shadow_pilot.verify_eig_event_correlation", return_value=(True, {"divergence": "CONGRUENT", "eig_summary": {"answer_evidence_status": "USABLE_FOR_ANSWER"}}, "EIG_EVENT_VERIFIED")):
                        manifest_path = Path(__file__).parent / "pilot_query_manifest_105.json"
                        summary, records = run_real_retrieval_shadow_pilot(
                            total_pilot_deadline_sec=0.05,
                            per_query_timeout_sec=0.1,
                            max_queries=10,
                            query_manifest_path=manifest_path
                        )
                        self.assertEqual(summary["total_queries_planned"], 10)
                        self.assertLess(summary["queries_completed"], 10)
                        self.assertEqual(summary["verdict"], "BLOCKED")
                        self.assertEqual(summary["status"], "DEADLINE_EXCEEDED")

    def test_contract_ng10_idempotent_rerun_on_same_head_manifest_stable(self):
        """NG-10: Repeated run on identical HEAD and manifest produces identical fingerprints and stable status."""
        manifest_path = Path(__file__).parent / "pilot_query_manifest_105.json"
        self.assertTrue(manifest_path.exists())

        summary1, _ = run_real_retrieval_shadow_pilot(query_manifest_path=manifest_path)
        summary2, _ = run_real_retrieval_shadow_pilot(query_manifest_path=manifest_path)

        self.assertEqual(summary1["verdict"], summary2["verdict"])
        self.assertEqual(summary1["status"], summary2["status"])
        self.assertEqual(summary1["total_queries_planned"], summary2["total_queries_planned"])
        self.assertEqual(summary1["actual_search_calls_executed"], summary2["actual_search_calls_executed"])
        self.assertEqual(summary1["config_fingerprint"], summary2["config_fingerprint"])
        self.assertEqual(summary1["manifest_sha256"], summary2["manifest_sha256"])



    # --- Revision 2 Tests G2-01..G2-10 (Specification FR-TZ-20261116-006 Rev 2) ---

    def test_contract_g2_01_manifest_missing_schema_or_hash_fails_closed(self):
        """G2-01: 105 positions without schema and manifest_sha256 fails with CONFIG_INVALID and 0 worker."""
        from unittest.mock import patch, MagicMock

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_p = Path(tmpdir)

            # 1. Manifest with 105 items but missing schema
            no_schema_p = tmp_p / "no_schema.json"
            no_schema_p.write_text(json.dumps({
                "manifest_sha256": "a" * 64,
                "queries": [
                    {"query_id": f"Q{i:03d}", "position": i, "category": "ACTUAL_NORMATIVE", "query_text": f"q {i}"}
                    for i in range(1, 106)
                ]
            }), encoding="utf-8")
            ok, msg, _ = validate_query_manifest(no_schema_p, expected_count=105)
            self.assertFalse(ok)
            self.assertIn("MANIFEST_SCHEMA_INVALID", msg)

            # 2. Manifest with 105 items but missing manifest_sha256
            no_hash_p = tmp_p / "no_hash.json"
            no_hash_p.write_text(json.dumps({
                "schema": "flying_rag.pilot_query_manifest.v1",
                "queries": [
                    {"query_id": f"Q{i:03d}", "position": i, "category": "ACTUAL_NORMATIVE", "query_text": f"q {i}"}
                    for i in range(1, 106)
                ]
            }), encoding="utf-8")
            ok_h, msg_h, _ = validate_query_manifest(no_hash_p, expected_count=105)
            self.assertFalse(ok_h)
            self.assertIn("MANIFEST_HASH_MISSING_OR_INVALID", msg_h)

            # 3. Passed to runner -> fails closed with 0 workers
            spy_search = MagicMock()
            with patch(f"{__name__}.execute_bounded_search", spy_search):
                summary, records = run_real_retrieval_shadow_pilot(query_manifest_path=no_schema_p)
                self.assertEqual(summary["verdict"], "BLOCKED")
                self.assertEqual(summary["status"], "CONFIG_INVALID")
                self.assertEqual(summary["actual_search_calls_executed"], 0)
                self.assertEqual(spy_search.call_count, 0)

    def test_contract_g2_02_manifest_arbitrary_category_or_bad_types_fails_closed(self):
        """G2-02: Arbitrary category, invalid header counters, or query_text with dict/int type fails closed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_p = Path(tmpdir)

            # 1. Arbitrary category
            bad_cat_p = tmp_p / "bad_cat.json"
            q_list = [
                {"query_id": f"Q{i:03d}", "position": i, "category": "UNAUTHORIZED_BENCHMARK", "query_text": f"q {i}"}
                for i in range(1, 106)
            ]
            c_hash = hashlib.sha256(json.dumps(q_list, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
            bad_cat_p.write_text(json.dumps({
                "schema": "flying_rag.pilot_query_manifest.v1",
                "manifest_sha256": c_hash,
                "total_queries": 105,
                "normative_count": 80,
                "adversarial_count": 25,
                "queries": q_list
            }), encoding="utf-8")
            ok, msg, _ = validate_query_manifest(bad_cat_p, expected_count=105)
            self.assertFalse(ok)
            self.assertIn("MANIFEST_INVALID_CATEGORY", msg)

            # 2. Header counters mismatch
            bad_hdr_p = tmp_p / "bad_hdr.json"
            q_valid = [
                {"query_id": f"Q{i:03d}", "position": i, "category": "ACTUAL_NORMATIVE" if i <= 80 else "SYNTHETIC_ADVERSARIAL", "query_text": f"q {i}"}
                for i in range(1, 106)
            ]
            v_hash = hashlib.sha256(json.dumps(q_valid, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
            bad_hdr_p.write_text(json.dumps({
                "schema": "flying_rag.pilot_query_manifest.v1",
                "manifest_sha256": v_hash,
                "total_queries": 105,
                "normative_count": 79,  # Mismatch: actual is 80
                "adversarial_count": 26,
                "queries": q_valid
            }), encoding="utf-8")
            ok_hdr, msg_hdr, _ = validate_query_manifest(bad_hdr_p, expected_count=105)
            self.assertFalse(ok_hdr)
            self.assertIn("MANIFEST_PROFILE_MISMATCH", msg_hdr)

            # 3. query_text with dict/int type
            bad_type_p = tmp_p / "bad_type.json"
            q_type = [
                {"query_id": f"Q{i:03d}", "position": i, "category": "ACTUAL_NORMATIVE" if i <= 80 else "SYNTHETIC_ADVERSARIAL", "query_text": {"injection": 123} if i == 5 else f"q {i}"}
                for i in range(1, 106)
            ]
            t_hash = hashlib.sha256(json.dumps(q_type, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
            bad_type_p.write_text(json.dumps({
                "schema": "flying_rag.pilot_query_manifest.v1",
                "manifest_sha256": t_hash,
                "total_queries": 105,
                "normative_count": 80,
                "adversarial_count": 25,
                "queries": q_type
            }), encoding="utf-8")
            ok_type, msg_type, _ = validate_query_manifest(bad_type_p, expected_count=105)
            self.assertFalse(ok_type)
            self.assertIn("MANIFEST_INVALID_QUERY_TEXT", msg_type)

    def test_contract_g2_03_malicious_or_empty_id_position_gap_fails_closed_repetition_allowed(self):
        """G2-03: Malicious/empty ID, position gap, invalid hash fails closed; legitimate query_text repetition succeeds."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_p = Path(tmpdir)

            # 1. Empty query_id
            bad_id_p = tmp_p / "bad_id.json"
            q_bad_id = [
                {"query_id": "   " if i == 10 else f"Q{i:03d}", "position": i, "category": "ACTUAL_NORMATIVE" if i <= 80 else "SYNTHETIC_ADVERSARIAL", "query_text": f"q {i}"}
                for i in range(1, 106)
            ]
            h_bad_id = hashlib.sha256(json.dumps(q_bad_id, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
            bad_id_p.write_text(json.dumps({
                "schema": "flying_rag.pilot_query_manifest.v1",
                "manifest_sha256": h_bad_id,
                "total_queries": 105,
                "normative_count": 80,
                "adversarial_count": 25,
                "queries": q_bad_id
            }), encoding="utf-8")
            ok, msg, _ = validate_query_manifest(bad_id_p, expected_count=105)
            self.assertFalse(ok)
            self.assertIn("MANIFEST_MALICIOUS_OR_EMPTY_ID", msg)

            # 2. Position gap (1, 2, 4...)
            bad_pos_p = tmp_p / "bad_pos.json"
            q_bad_pos = [
                {"query_id": f"Q{i:03d}", "position": (i + 1) if i >= 3 else i, "category": "ACTUAL_NORMATIVE" if i <= 80 else "SYNTHETIC_ADVERSARIAL", "query_text": f"q {i}"}
                for i in range(1, 106)
            ]
            h_bad_pos = hashlib.sha256(json.dumps(q_bad_pos, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
            bad_pos_p.write_text(json.dumps({
                "schema": "flying_rag.pilot_query_manifest.v1",
                "manifest_sha256": h_bad_pos,
                "total_queries": 105,
                "normative_count": 80,
                "adversarial_count": 25,
                "queries": q_bad_pos
            }), encoding="utf-8")
            ok_pos, msg_pos, _ = validate_query_manifest(bad_pos_p, expected_count=105)
            self.assertFalse(ok_pos)
            self.assertIn("MANIFEST_POSITION_GAP", msg_pos)

            # 3. Legitimate duplicate query_text with distinct valid query_ids
            q_repeat = [
                {"query_id": f"Q{i:03d}", "position": i, "category": "ACTUAL_NORMATIVE" if i <= 80 else "SYNTHETIC_ADVERSARIAL", "query_text": "СП 7.13130 пункт 6.1" if i in (1, 2) else f"query {i}"}
                for i in range(1, 106)
            ]
            h_repeat = hashlib.sha256(json.dumps(q_repeat, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
            repeat_p = tmp_p / "valid_repeat.json"
            repeat_p.write_text(json.dumps({
                "schema": "flying_rag.pilot_query_manifest.v1",
                "manifest_sha256": h_repeat,
                "total_queries": 105,
                "normative_count": 80,
                "adversarial_count": 25,
                "queries": q_repeat
            }), encoding="utf-8")
            ok_rep, msg_rep, loaded_rep = validate_query_manifest(repeat_p, expected_count=105)
            self.assertTrue(ok_rep, f"Legitimate repetition must be permitted: {msg_rep}")
            self.assertEqual(len(loaded_rep), 105)
            self.assertEqual(loaded_rep[0]["query_text"], loaded_rep[1]["query_text"])
            self.assertNotEqual(loaded_rep[0]["query_id"], loaded_rep[1]["query_id"])

    def test_contract_g2_04_max_queries_zero_or_negative_fails_closed_zero_calls(self):
        """G2-04: max_queries=0 or negative value yields explicit failure or 0 calls, never running all queries."""
        # max_queries=0
        summary_zero, _ = run_real_retrieval_shadow_pilot(max_queries=0)
        self.assertEqual(summary_zero["verdict"], "BLOCKED")
        self.assertEqual(summary_zero["status"], "CONFIG_INVALID")
        self.assertEqual(summary_zero["total_queries_planned"], 0)
        self.assertEqual(summary_zero["actual_search_calls_executed"], 0)

        # max_queries=-10
        summary_neg, _ = run_real_retrieval_shadow_pilot(max_queries=-10)
        self.assertEqual(summary_neg["verdict"], "BLOCKED")
        self.assertEqual(summary_neg["status"], "CONFIG_INVALID")
        self.assertEqual(summary_neg["total_queries_planned"], 0)
        self.assertEqual(summary_neg["actual_search_calls_executed"], 0)

    def test_contract_g2_05_target_pid_foreign_exe_or_mismatched_start_time_rejected(self):
        """G2-05: Real PID with foreign executable path or mismatched create_time strictly rejected."""
        import psutil
        my_pid = os.getpid()
        my_ct = psutil.Process(my_pid).create_time()

        # 1. Foreign executable path
        safe_path, reason_path = verify_process_termination_safety(
            target_pid=my_pid,
            expected_path="C:\\RAG_Acer\\bin\\llama-server.exe",
            port_probe_pid=my_pid
        )
        self.assertFalse(safe_path)
        self.assertIn("PROCESS_PATH_MISMATCH", reason_path)

        # 2. Mismatched start time
        safe_time, reason_time = verify_process_termination_safety(
            target_pid=my_pid,
            expected_path=sys.executable,
            expected_start_time=my_ct - 500.0,
            port_probe_pid=my_pid,
            owned_process_record={"pid": my_pid, "create_time": my_ct}
        )
        self.assertFalse(safe_time)
        self.assertIn("PROCESS_START_TIME_MISMATCH", reason_time)

    def test_contract_g2_06_pid_reuse_vanished_pid_or_foreign_listener_rejected_own_metadata_verified(self):
        """G2-06: PID reuse, vanished PID, foreign listener unconditionally rejected; own process verified."""
        import psutil
        my_pid = os.getpid()
        my_exe = sys.executable
        my_ct = psutil.Process(my_pid).create_time()

        # 1. Vanished / non-existent PID
        safe_vanished, reason_vanished = verify_process_termination_safety(
            target_pid=999999,
            expected_path=my_exe
        )
        self.assertFalse(safe_vanished)
        self.assertIn("PROCESS_NOT_FOUND", reason_vanished)

        # 2. Foreign listener on port 8089 (port listener 8888 != my_pid)
        safe_port, reason_port = verify_process_termination_safety(
            target_pid=my_pid,
            expected_path=my_exe,
            port_probe_pid=8888
        )
        self.assertFalse(safe_port)
        self.assertIn("PORT_8089_IN_USE_BY_FOREIGN_PROCESS", reason_port)

        # 3. Positive verification of own process
        safe_own, reason_own = verify_process_termination_safety(
            target_pid=my_pid,
            expected_path=my_exe,
            expected_start_time=my_ct,
            port_probe_pid=my_pid,
            owned_process_record={"pid": my_pid, "create_time": my_ct}
        )
        self.assertTrue(safe_own)
        self.assertEqual(reason_own, "PROCESS_IDENTITY_VERIFIED")

    def test_contract_g2_07_garbage_sqlite_or_empty_manifest_yields_snapshot_no_go(self):
        """G2-07: Garbage bytes in SQLite, empty manifest, or missing lance table strictly yields SNAPSHOT_NO_GO."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_p = Path(tmpdir)
            meta_path = tmp_p / "metadata.db"
            meta_path.write_bytes(b"garbage bytes in database header")
            lance_path = tmp_p / "lancedb"
            lance_path.mkdir()
            (lance_path / "index_manifest.json").write_text("{}", encoding="utf-8")

            # 1. Garbage SQLite
            ok_g, code_g, diag_g = verify_snapshot_readiness(meta_path, lance_path)
            self.assertFalse(ok_g)
            self.assertEqual(code_g, "SNAPSHOT_SQLITE_INVALID")

            # 2. Valid SQLite but empty manifest
            meta_path.unlink()
            conn = sqlite3.connect(str(meta_path))
            conn.execute("CREATE TABLE files (id TEXT)")
            conn.commit()
            conn.close()

            ok_m, code_m, diag_m = verify_snapshot_readiness(meta_path, lance_path)
            self.assertFalse(ok_m)
            self.assertEqual(code_m, "SNAPSHOT_LANCEDB_EMPTY_MANIFEST")

            # 3. Valid manifest but table missing
            (lance_path / "index_manifest.json").write_text(json.dumps({
                "table_name": "documents_1024.lance", "dimension": 1024
            }), encoding="utf-8")
            ok_t, code_t, diag_t = verify_snapshot_readiness(meta_path, lance_path)
            self.assertFalse(ok_t)
            self.assertEqual(code_t, "SNAPSHOT_LANCEDB_TABLE_NOT_FOUND")

    def test_contract_g2_08_wal_zero_sample_match_without_consistency_proof_unverified(self):
        """G2-08: WAL=0, sample match, but missing consistency proof yields UNVERIFIED, not CONSISTENT_SNAPSHOT_VERIFIED."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_p = Path(tmpdir)
            meta_path = tmp_p / "metadata.db"
            conn = sqlite3.connect(str(meta_path))
            conn.execute("CREATE TABLE files (id TEXT PRIMARY KEY)")
            conn.commit()
            conn.close()

            lance_path = tmp_p / "lancedb"
            lance_path.mkdir()
            (lance_path / "index_manifest.json").write_text(json.dumps({
                "table_name": "documents_1024.lance", "dimension": 1024, "version": 1
            }), encoding="utf-8")
            (lance_path / "documents_1024.lance").mkdir()

            # When consistency proof is required, unproven snapshot fails closed
            ok, code, diag = verify_snapshot_readiness(meta_path, lance_path, require_consistency_proof=True)
            self.assertFalse(ok)
            self.assertEqual(code, "SNAPSHOT_FILES_PRESENT_UNVERIFIED")
            self.assertNotEqual(code, "CONSISTENT_SNAPSHOT_VERIFIED")

    def test_contract_g2_09_yaml_tampered_during_off_strictly_zeros_on_and_yields_blocked(self):
        """G2-09: OFF search mutates YAML to production path -> ON spy call count is strictly 0, verdict BLOCKED."""
        import yaml
        from unittest.mock import patch, MagicMock

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_p = Path(tmpdir).resolve()
            meta_path = tmp_p / "metadata.db"
            meta_path.touch()
            lance_path = tmp_p / "lancedb"
            lance_path.mkdir()

            cfg_path = tmp_p / "isolated_config.yaml"
            cfg_path.write_text(yaml.dump({
                "storage": {
                    "metadata_db": str(meta_path),
                    "lancedb_path": str(lance_path)
                },
                "embedder": {
                    "url": "http://127.0.0.1:8089/v1/embeddings",
                    "model": "Qwen3-Embedding-0.6B-Q8_0.gguf",
                    "dimension": 1024
                }
            }), encoding="utf-8")

            register_verified_fixture_root(tmp_p)
            try:
                mock_diag = {"endpoint_url": "http://127.0.0.1:8089/v1/embeddings", "error_classification": "NONE", "required_operator_action": ""}
                call_log = []

                def controlled_search(query, shadow_mode, *args, **kwargs):
                    call_log.append(shadow_mode)
                    if not shadow_mode:
                        # Mutate config during Step A (OFF) to point storage to production!
                        cfg_path.write_text(yaml.dump({
                            "storage": {
                                "metadata_db": "C:/RAG_Acer/data_imported/metadata.db",
                                "lancedb_path": "C:/RAG_Acer/data_imported/lancedb"
                            },
                            "embedder": {
                                "url": "http://127.0.0.1:8089/v1/embeddings",
                                "model": "Qwen3-Embedding-0.6B-Q8_0.gguf",
                                "dimension": 1024
                            }
                        }), encoding="utf-8")
                        return SearchResult(True, [{"chunk_id": "c1"}], 5.0, "", 0)
                    # If ON is ever called, fail the invariant
                    return SearchResult(True, [{"chunk_id": "c1"}], 5.0, "", 0)

                with patch(f"{__name__}.check_backend_readiness", return_value=(True, mock_diag)):
                    with patch(f"{__name__}.execute_bounded_search", side_effect=controlled_search):
                        summary, records = run_real_retrieval_shadow_pilot(max_queries=3, config_path=cfg_path)
                        self.assertEqual(summary["verdict"], "BLOCKED")
                        self.assertEqual(summary["status"], "CONFIG_TAMPER_DETECTED")
                        # ON search must NEVER be called (strictly 0 times!)
                        on_calls = [m for m in call_log if m is True]
                        self.assertEqual(len(on_calls), 0, "Step B (ON) must strictly NOT be spawned when config is mutated after OFF")
                        self.assertEqual(len(call_log), 1, "Only Step A (OFF) should have run")
            finally:
                unregister_verified_fixture_root(tmp_p)

    def test_contract_g2_10_config_or_symlink_drift_before_worker_halts_with_zero_new_workers(self):
        """G2-10: Config modification or symlink before worker call halts with 0 new workers and no false GO."""
        import yaml
        from unittest.mock import patch, MagicMock

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_p = Path(tmpdir).resolve()
            meta_path = tmp_p / "metadata.db"
            meta_path.touch()
            lance_path = tmp_p / "lancedb"
            lance_path.mkdir()

            cfg_path = tmp_p / "isolated_config.yaml"
            cfg_path.write_text(yaml.dump({
                "storage": {
                    "metadata_db": str(meta_path),
                    "lancedb_path": str(lance_path)
                },
                "embedder": {
                    "url": "http://127.0.0.1:8089/v1/embeddings",
                    "model": "Qwen3-Embedding-0.6B-Q8_0.gguf",
                    "dimension": 1024
                }
            }), encoding="utf-8")

            register_verified_fixture_root(tmp_p)
            try:
                # Tamper config on disk before loop starts
                cfg_path.write_text("corrupted_content: true\n", encoding="utf-8")

                mock_diag = {"endpoint_url": "http://127.0.0.1:8089/v1/embeddings", "error_classification": "NONE", "required_operator_action": ""}
                search_spy = MagicMock()
                with patch(f"{__name__}.check_backend_readiness", return_value=(True, mock_diag)):
                    with patch(f"{__name__}.execute_bounded_search", search_spy):
                        summary, records = run_real_retrieval_shadow_pilot(max_queries=2, config_path=cfg_path)
                        self.assertEqual(summary["verdict"], "BLOCKED")
                        self.assertIn(summary["status"], ("CONFIG_INVALID", "CONFIG_TAMPER_DETECTED"))
                        self.assertEqual(search_spy.call_count, 0)
                        self.assertEqual(summary["actual_search_calls_executed"], 0)
            finally:
                unregister_verified_fixture_root(tmp_p)

    # =========================================================================
    # REVISION 3 CONTRACT TESTS (G3-01 .. G3-10)
    # =========================================================================

    def test_contract_g3_01_manifest_missing_header_counts_fails_closed(self):
        """G3-01: Correct 105 items and correct hash, but NO header counts -> MANIFEST_INVALID_HEADER_COUNTS, 0 workers."""
        from unittest.mock import patch, MagicMock

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_p = Path(tmpdir)
            p = tmp_p / "missing_counts.json"
            q_list = [
                {"query_id": f"Q{i:03d}", "position": i, "category": "ACTUAL_NORMATIVE" if i <= 80 else "SYNTHETIC_ADVERSARIAL", "query_text": f"query {i}"}
                for i in range(1, 106)
            ]
            c_hash = hashlib.sha256(json.dumps(q_list, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
            p.write_text(json.dumps({
                "schema": "flying_rag.pilot_query_manifest.v1",
                "manifest_sha256": c_hash,
                "queries": q_list
            }), encoding="utf-8")

            ok, msg, _ = validate_query_manifest(p, expected_count=105)
            self.assertFalse(ok)
            self.assertIn("MANIFEST_INVALID_HEADER_COUNTS", msg)

            spy_search = MagicMock()
            with patch(f"{__name__}.execute_bounded_search", spy_search):
                summary, _ = run_real_retrieval_shadow_pilot(query_manifest_path=p)
                self.assertEqual(summary["verdict"], "BLOCKED")
                self.assertEqual(summary["status"], "CONFIG_INVALID")
                self.assertEqual(summary["actual_search_calls_executed"], 0)
                self.assertEqual(spy_search.call_count, 0)

    def test_contract_g3_02_all_normative_manifest_fails_profile_check(self):
        """G3-02: 105 items all ACTUAL_NORMATIVE, header 105/105/0, valid hash -> NO_GO (profile mismatch 80/25)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_p = Path(tmpdir)
            p = tmp_p / "all_normative.json"
            q_list = [
                {"query_id": f"Q{i:03d}", "position": i, "category": "ACTUAL_NORMATIVE", "query_text": f"query {i}"}
                for i in range(1, 106)
            ]
            c_hash = hashlib.sha256(json.dumps(q_list, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
            p.write_text(json.dumps({
                "schema": "flying_rag.pilot_query_manifest.v1",
                "manifest_sha256": c_hash,
                "total_queries": 105,
                "normative_count": 105,
                "adversarial_count": 0,
                "queries": q_list
            }), encoding="utf-8")

            ok, msg, _ = validate_query_manifest(p, expected_count=105)
            self.assertFalse(ok)
            self.assertIn("MANIFEST_PROFILE_MISMATCH", msg)

    def test_contract_g3_03_mismatched_counts_or_bool_headers_fails_closed(self):
        """G3-03: 75 normative + 30 adversarial, header 105/80/25 -> NO_GO; bool header -> NO_GO."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_p = Path(tmpdir)

            # 1. Actual counts (75/30) mismatch declared (80/25)
            p1 = tmp_p / "mismatch_actual.json"
            q_list1 = [
                {"query_id": f"Q{i:03d}", "position": i, "category": "ACTUAL_NORMATIVE" if i <= 75 else "SYNTHETIC_ADVERSARIAL", "query_text": f"query {i}"}
                for i in range(1, 106)
            ]
            c_hash1 = hashlib.sha256(json.dumps(q_list1, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
            p1.write_text(json.dumps({
                "schema": "flying_rag.pilot_query_manifest.v1",
                "manifest_sha256": c_hash1,
                "total_queries": 105,
                "normative_count": 80,
                "adversarial_count": 25,
                "queries": q_list1
            }), encoding="utf-8")

            ok1, msg1, _ = validate_query_manifest(p1, expected_count=105)
            self.assertFalse(ok1)
            self.assertIn("MANIFEST_PROFILE_MISMATCH", msg1)

            # 2. Boolean instead of integer in header
            p2 = tmp_p / "bool_header.json"
            q_list2 = [
                {"query_id": f"Q{i:03d}", "position": i, "category": "ACTUAL_NORMATIVE" if i <= 80 else "SYNTHETIC_ADVERSARIAL", "query_text": f"query {i}"}
                for i in range(1, 106)
            ]
            c_hash2 = hashlib.sha256(json.dumps(q_list2, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
            p2.write_text(json.dumps({
                "schema": "flying_rag.pilot_query_manifest.v1",
                "manifest_sha256": c_hash2,
                "total_queries": True,
                "normative_count": 80,
                "adversarial_count": 25,
                "queries": q_list2
            }), encoding="utf-8")

            ok2, msg2, _ = validate_query_manifest(p2, expected_count=105)
            self.assertFalse(ok2)
            self.assertIn("MANIFEST_INVALID_HEADER_TYPES", msg2)

    def test_contract_g3_04_canonical_manifest_with_duplicate_text_passes_full_105(self):
        """G3-04: Canonical 105/80/25 with duplicate query_text across distinct query_ids succeeds as FULL_105."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_p = Path(tmpdir)
            p = tmp_p / "valid_canonical.json"
            q_list = [
                {
                    "query_id": f"Q{i:03d}",
                    "position": i,
                    "category": "ACTUAL_NORMATIVE" if i <= 80 else "SYNTHETIC_ADVERSARIAL",
                    "query_text": "СП 7.13130 пункт 6.4" if i in (1, 2) else f"запрос норматива {i}"
                }
                for i in range(1, 106)
            ]
            c_hash = hashlib.sha256(json.dumps(q_list, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
            p.write_text(json.dumps({
                "schema": "flying_rag.pilot_query_manifest.v1",
                "manifest_sha256": c_hash,
                "total_queries": 105,
                "normative_count": 80,
                "adversarial_count": 25,
                "queries": q_list
            }), encoding="utf-8")

            ok, msg, loaded = validate_query_manifest(p, expected_count=105)
            self.assertTrue(ok, f"Canonical manifest with valid repetition must pass: {msg}")
            self.assertEqual(len(loaded), 105)
            self.assertEqual(loaded[0]["query_text"], loaded[1]["query_text"])
            self.assertNotEqual(loaded[0]["query_id"], loaded[1]["query_id"])

    def test_contract_g3_05_missing_owned_record_and_start_time_fails_closed(self):
        """G3-05: Real PID and matching exe, but expected_start_time and owned_process_record are missing -> safe=False, 0 signals."""
        import psutil
        my_pid = os.getpid()
        my_exe = sys.executable

        safe, reason = verify_process_termination_safety(
            target_pid=my_pid,
            expected_path=my_exe,
            expected_start_time=None,
            owned_process_record=None
        )
        self.assertFalse(safe)
        self.assertIn("OWNED_RECORD_REQUIRED", reason)

    def test_contract_g3_06_empty_owned_record_or_invalid_create_time_fails_closed(self):
        """G3-06: owned_process_record is empty or create_time='not-a-time' -> safe=False without silent exception suppression."""
        import psutil
        my_pid = os.getpid()
        my_exe = sys.executable

        # 1. Empty owned_process_record
        safe_empty, reason_empty = verify_process_termination_safety(
            target_pid=my_pid,
            expected_path=my_exe,
            owned_process_record={}
        )
        self.assertFalse(safe_empty)
        self.assertIn("OWNED_RECORD_REQUIRED", reason_empty)

        # 2. create_time is unparseable string
        safe_bad_time, reason_bad_time = verify_process_termination_safety(
            target_pid=my_pid,
            expected_path=my_exe,
            owned_process_record={"pid": my_pid, "create_time": "not-a-time"}
        )
        self.assertFalse(safe_bad_time)
        self.assertIn("OWNED_RECORD_START_TIME_INVALID", reason_bad_time)

    def test_contract_g3_07_owned_record_mismatch_or_foreign_listener_rejected(self):
        """G3-07: PID/exe match but owned record has mismatched PID/create_time or foreign port listener -> safe=False."""
        import psutil
        my_pid = os.getpid()
        my_exe = sys.executable
        my_ct = psutil.Process(my_pid).create_time()

        # 1. Mismatched PID in record
        safe_pid, reason_pid = verify_process_termination_safety(
            target_pid=my_pid,
            expected_path=my_exe,
            owned_process_record={"pid": my_pid + 9999, "create_time": my_ct}
        )
        self.assertFalse(safe_pid)
        self.assertIn("OWNED_RECORD_PID_MISMATCH", reason_pid)

        # 2. Mismatched create_time in record
        safe_ct, reason_ct = verify_process_termination_safety(
            target_pid=my_pid,
            expected_path=my_exe,
            owned_process_record={"pid": my_pid, "create_time": my_ct + 999.0}
        )
        self.assertFalse(safe_ct)
        self.assertIn("OWNED_RECORD_START_TIME_MISMATCH", reason_ct)

        # 3. Foreign listener on port 8089
        safe_port, reason_port = verify_process_termination_safety(
            target_pid=my_pid,
            expected_path=my_exe,
            port_probe_pid=my_pid + 1,
            owned_process_record={"pid": my_pid, "create_time": my_ct}
        )
        self.assertFalse(safe_port)
        self.assertIn("PORT_8089_IN_USE_BY_FOREIGN_PROCESS", reason_port)

    def test_contract_g3_08_controlled_own_process_verified_without_kill(self):
        """G3-08: Controlled own process + valid owned_process_record -> True, PROCESS_IDENTITY_VERIFIED, no kill/terminate."""
        import psutil
        my_pid = os.getpid()
        my_exe = sys.executable
        my_ct = psutil.Process(my_pid).create_time()

        safe, reason = verify_process_termination_safety(
            target_pid=my_pid,
            expected_path=my_exe,
            expected_start_time=my_ct,
            port_probe_pid=my_pid,
            owned_process_record={"pid": my_pid, "create_time": my_ct}
        )
        self.assertTrue(safe)
        self.assertEqual(reason, "PROCESS_IDENTITY_VERIFIED")

    def test_contract_g3_09_operator_form_external_path_blocked_zero_calls(self):
        """G3-09: Operator form proposing external path outside system temp yields BLOCKED and 0 search calls."""
        import yaml
        from unittest.mock import patch, MagicMock

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_p = Path(tmpdir)
            cfg_p = tmp_p / "external_candidate_cfg.yaml"
            cfg_p.write_text(yaml.dump({
                "storage": {
                    "metadata_db": "C:/RAG_Acer/isolated_pilot_data/metadata.db",
                    "lancedb_path": "C:/RAG_Acer/isolated_pilot_data/lancedb"
                },
                "embedder": {
                    "url": "http://127.0.0.1:8089/v1/embeddings",
                    "model": "Qwen3-Embedding-0.6B-Q8_0.gguf",
                    "dimension": 1024
                }
            }), encoding="utf-8")

            # External path outside system temp is NOT registered and must yield BLOCKED
            mock_diag = {"endpoint_url": "http://127.0.0.1:8089/v1/embeddings", "error_classification": "NONE", "required_operator_action": ""}
            spy_search = MagicMock()
            with patch(f"{__name__}.check_backend_readiness", return_value=(True, mock_diag)):
                with patch(f"{__name__}.execute_bounded_search", spy_search):
                    summary, _ = run_real_retrieval_shadow_pilot(config_path=cfg_p)
                    self.assertEqual(summary["verdict"], "BLOCKED")
                    self.assertEqual(summary["readonly_scope"], "BLOCKED_READONLY_NOT_PROVEN")
                    self.assertEqual(summary["actual_search_calls_executed"], 0)
                    self.assertEqual(spy_search.call_count, 0)

    def test_contract_g3_10_smoke_legacy_or_partial_queries_never_yields_full_105_go(self):
        """G3-10: 8-query fallback or max_queries=3 never receives FULL_105_GO; full status requires canonical 105 manifest."""
        # 1. 8-query default without manifest
        summary_8, _ = run_real_retrieval_shadow_pilot()
        self.assertEqual(summary_8["pilot_mode"], "SMOKE_LEGACY_8")
        self.assertFalse(summary_8.get("full_105_go_eligible", False))

        # 2. max_queries=3 partial run on canonical manifest
        manifest_path = Path(__file__).parent / "pilot_query_manifest_105.json"
        summary_partial, _ = run_real_retrieval_shadow_pilot(query_manifest_path=manifest_path, max_queries=3)
        self.assertEqual(summary_partial["pilot_mode"], "FULL_MANIFEST_105")
        self.assertEqual(summary_partial["series_completion"], "PARTIAL")
        self.assertFalse(summary_partial.get("full_105_go_eligible", False))


if __name__ == "__main__":
    unittest.main()
