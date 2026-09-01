"""One command that checks the whole local install.

    python scripts\\verify_local.py            # offline: everything that needs no server
    python scripts\\verify_local.py --live     # additionally probe the live Lemonade + index

Phases
------
1. environment   — Python, dependencies, config file
2. unit suite    — every test_*.py module
3. round trip    — the real indexer.py and the real search path against a local
                   stub embedding server, in a temp store (never touches yours)
4. contract      — the indexer must refuse a second embedding model
5. live          — (--live) embedding contract, index manifest, preflight probe

Phase 3 runs indexer.py as an actual subprocess with FLYING_RAG_CONFIG pointing
at a throwaway config, so it exercises the production path end to end without
going near your real config.yaml, index or metadata DB.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DIM = 1024
MODEL = "Qwen3-Embedding-0.6B-GGUF"


# ── reporting ─────────────────────────────────────────────────────────────────

class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str]] = []

    def add(self, phase: str, name: str, ok: bool | None, detail: str = "") -> None:
        state = "PASS" if ok else ("SKIP" if ok is None else "FAIL")
        self.rows.append((phase, name, state))
        mark = {"PASS": "  ok  ", "FAIL": " FAIL ", "SKIP": " skip "}[state]
        line = f"[{mark}] {name}"
        print(line + (f"  — {detail}" if detail else ""))

    @property
    def failed(self) -> int:
        return sum(1 for _p, _n, s in self.rows if s == "FAIL")

    def summary(self) -> None:
        passed = sum(1 for _p, _n, s in self.rows if s == "PASS")
        skipped = sum(1 for _p, _n, s in self.rows if s == "SKIP")
        print("\n" + "=" * 60)
        print(f"passed {passed}   failed {self.failed}   skipped {skipped}")
        if self.failed:
            print("\nfailed checks:")
            for phase, name, state in self.rows:
                if state == "FAIL":
                    print(f"  - [{phase}] {name}")


# ── stub embedding server ─────────────────────────────────────────────────────

def _vector(text: str) -> list[float]:
    import hashlib
    import math

    vec = [0.0] * DIM
    for token in str(text or "").casefold().split():
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        vec[int.from_bytes(digest[:4], "big") % DIM] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class _Handler(BaseHTTPRequestHandler):
    served_model = MODEL

    def log_message(self, *_args):
        pass

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.path.endswith("/embeddings"):
            payload = {
                "model": type(self).served_model,
                "data": [
                    {"index": i, "embedding": _vector(t)}
                    for i, t in enumerate(body.get("input") or [])
                ],
            }
        elif self.path.endswith("/reranking"):
            payload = {"results": [
                {"index": i, "relevance_score": float(i)}
                for i in range(len(body.get("documents") or []))
            ]}
        else:
            self.send_response(404)
            self.end_headers()
            return
        data = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class StubServer:
    def __init__(self):
        self.httpd = HTTPServer(("127.0.0.1", 0), _Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}/api/v1"

    def serve_model(self, name: str) -> None:
        _Handler.served_model = name

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


# ── phases ────────────────────────────────────────────────────────────────────

def phase_environment(report: Report) -> None:
    print("\n=== 1. environment ===")
    report.add("env", f"python {sys.version.split()[0]}", sys.version_info >= (3, 10),
               "3.10+ required" if sys.version_info < (3, 10) else "")

    required = ["lancedb", "pyarrow", "httpx", "yaml", "tiktoken", "numpy"]
    optional = ["fitz", "mcp", "openpyxl", "docx", "watchdog"]
    for name in required:
        try:
            __import__(name)
            report.add("env", f"dependency {name}", True)
        except Exception as e:
            report.add("env", f"dependency {name}", False, str(e))
    for name in optional:
        try:
            __import__(name)
            report.add("env", f"optional {name}", True)
        except Exception:
            report.add("env", f"optional {name}", None, "not installed")

    from config_loader import config_path

    path = config_path()
    report.add("env", f"config {path.name}", path.exists(), str(path))


_SCRIPT_RESULT_RE = None


def _run_script_test(module: str) -> tuple[bool, str]:
    """Some suites are standalone scripts that self-skip under unittest."""
    import re

    global _SCRIPT_RESULT_RE
    if _SCRIPT_RESULT_RE is None:
        _SCRIPT_RESULT_RE = re.compile(
            r"(?:RESULTS:\s*)?(\d+)\s+passed,\s*(\d+)\s+failed", re.IGNORECASE
        )
    proc = subprocess.run(
        [sys.executable, f"{module}.py"],
        cwd=ROOT, capture_output=True, text=True, timeout=900,
    )
    text = (proc.stdout or "") + (proc.stderr or "")
    matches = _SCRIPT_RESULT_RE.findall(text)
    if not matches:
        return proc.returncode == 0, "no result line"
    passed, failed = matches[-1]
    return int(failed) == 0, f"{passed} passed, {failed} failed"


def phase_unit_suite(report: Report) -> None:
    print("\n=== 2. unit suite ===")
    modules = sorted(p.stem for p in ROOT.glob("test_*.py"))
    for module in modules:
        proc = subprocess.run(
            [sys.executable, "-m", "unittest", module],
            cwd=ROOT, capture_output=True, text=True, timeout=900,
        )
        stderr = proc.stderr or ""
        tail = stderr.strip().splitlines()
        verdict = tail[-1] if tail else ""
        if "SkipTest" in stderr and "run with python" in stderr:
            ok, detail = _run_script_test(module)
            report.add("unit", f"{module} (script)", ok, detail)
        elif verdict.startswith("OK"):
            report.add("unit", module, True)
        elif verdict.startswith("FAILED") or proc.returncode != 0:
            report.add("unit", module, False, verdict[:80])
        else:
            report.add("unit", module, None, "no unittest result")


def _temp_config(root: Path, base_url: str) -> Path:
    cfg = {
        "datasets": {"default": "normative", "normative": {"paths": ["corpus"]}},
        "lemonade": {"base_url": base_url, "model": MODEL, "batch_size": 8,
                     "timeout_sec": 30},
        "retrieval": {"auto_rerank": False,
                      "rerank_endpoint": f"{base_url}/reranking",
                      "rerank_model": "stub-reranker"},
        "rules_extraction": {"enabled": False},
        "storage": {"lancedb_path": str(root / "lancedb"),
                    "metadata_db": str(root / "metadata.db")},
        "indexing": {"file_cooldown_sec": 0.0, "batch_cooldown_sec": 0.0,
                     "thermal_control": {"enabled": False}},
        "mcp": {"server_name": "flying-rag", "server_version": "verify"},
    }
    import yaml

    path = root / "verify_config.yaml"
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return path


CORPUS = {
    "sp_dym.txt": "Системы вытяжной противодымной вентиляции предусматриваются "
                  "для удаления продуктов горения из коридоров и холлов зданий.\n",
    "sp_vent.txt": "Расход приточного воздуха определяется расчетом воздухообмена "
                   "помещения с учетом кратности и назначения помещения.\n",
}


def phase_round_trip(report: Report, server: StubServer) -> None:
    print("\n=== 3. indexer + search round trip (temp store, stub server) ===")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        corpus = root / "corpus"
        corpus.mkdir()
        for name, text in CORPUS.items():
            (corpus / name).write_text(text, encoding="utf-8")
        cfg_path = _temp_config(root, server.base)

        env = dict(os.environ, FLYING_RAG_CONFIG=str(cfg_path))
        proc = subprocess.run(
            [sys.executable, str(ROOT / "indexer.py"), str(corpus)],
            cwd=ROOT, capture_output=True, text=True, timeout=600, env=env,
        )
        indexed = proc.returncode == 0 and "DONE chunks=" in (proc.stderr or "")
        report.add("round-trip", "indexer.py completes", indexed,
                   "" if indexed else (proc.stderr or "")[-200:])

        manifest_file = root / "lancedb" / "index_manifest.json"
        ok = manifest_file.exists()
        report.add("round-trip", "index manifest written", ok)
        if ok:
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            report.add("round-trip", "manifest records the model",
                       manifest.get("model") == MODEL, manifest.get("model", ""))
            report.add("round-trip", "manifest records the chunker",
                       bool(manifest.get("chunker")), manifest.get("chunker", ""))

        # Search through the real tools path against the store just built.
        probe = subprocess.run(
            [sys.executable, "-c", _SEARCH_PROBE],
            cwd=ROOT, capture_output=True, text=True, timeout=600, env=env,
        )
        try:
            result = json.loads((probe.stdout or "").strip().splitlines()[-1])
        except Exception:
            result = {}
            report.add("round-trip", "search returns results", False,
                       (probe.stderr or "")[-200:])
        if result:
            report.add("round-trip", "search returns results",
                       result.get("count", 0) > 0, f"count={result.get('count')}")
            report.add("round-trip", "trace status ok",
                       result.get("status") == "ok", str(result.get("status")))
            report.add("round-trip", "hybrid channels present",
                       "fts" in (result.get("channels") or []),
                       str(result.get("channels")))
            report.add("round-trip", "parent context hydrated",
                       (result.get("parent_hydrated") or 0) > 0,
                       f"hydrated={result.get('parent_hydrated')}")
            report.add("round-trip", "embedding contract verified",
                       result.get("contract") == "ok", str(result.get("contract")))

        # The indexer must refuse a store built by another model.
        server.serve_model("bge-m3")
        try:
            blocked = subprocess.run(
                [sys.executable, str(ROOT / "indexer.py"), str(corpus), "--force"],
                cwd=ROOT, capture_output=True, text=True, timeout=600, env=env,
            )
            refused = blocked.returncode == 2 and "BLOCKED" in (blocked.stderr or "")
            report.add("contract", "indexer refuses a second model", refused,
                       "" if refused else f"rc={blocked.returncode}")
        finally:
            server.serve_model(MODEL)


_SEARCH_PROBE = """
import json, sys
sys.path.insert(0, ".")
from rag_server.tools import search_documents
out = search_documents("удаление дыма из коридоров", top_k=3, use_cache=False, debug=True)
debug = out.get("debug", {}) if isinstance(out, dict) else {}
retrieval = debug.get("retrieval", {})
print(json.dumps({
    "count": len(out.get("results", []) if isinstance(out, dict) else out),
    "status": debug.get("status"),
    "channels": retrieval.get("channels"),
    "parent_hydrated": retrieval.get("parent_hydration", {}).get("hydrated"),
    "contract": debug.get("embedding_contract", {}).get("status"),
}))
"""


def phase_live(report: Report) -> None:
    print("\n=== 5. live server and index ===")
    from embedder.client import _DEFAULT_PROVIDER, check_connection
    from embedder.contract import EmbeddingContractError

    if not check_connection():
        report.add("live", "embedding server reachable", None, "offline — skipping live checks")
        return
    report.add("live", "embedding server reachable", True)

    try:
        state = _DEFAULT_PROVIDER.verify_contract()
        report.add("live", "embedding contract", state["status"] != "unchecked",
                   f"{state['status']}: served {state['actual_model'] or '?'}")
    except EmbeddingContractError as ce:
        report.add("live", "embedding contract", False, f"{ce.code}: {ce.detail}")
        return

    from rag_server.tools import _db_paths
    from storage.index_manifest import load_manifest, verify_manifest
    from storage.vector_store import count_chunks

    lance_path, meta_path = _db_paths()
    manifest = load_manifest(lance_path)
    if manifest is None:
        report.add("live", "index manifest", None,
                   "absent — will be written on the next index run")
    else:
        _s, code, detail = verify_manifest(
            manifest, model=_DEFAULT_PROVIDER.get_model_name(),
            dimension=int(manifest.get("dimension") or 0),
        )
        report.add("live", "index manifest", not code, detail or code)

    chunks = count_chunks(lance_path)
    report.add("live", "index is populated", chunks > 0, f"{chunks} chunks")
    report.add("live", "metadata db present", Path(meta_path).exists(), str(meta_path))

    from rag_server.tools import search_documents

    out = search_documents("требования к вентиляции", top_k=5, use_cache=False, debug=True)
    debug = out.get("debug", {}) if isinstance(out, dict) else {}
    retrieval = debug.get("retrieval", {})
    hydrated = (retrieval.get("parent_hydration") or {}).get("hydrated")
    report.add("live", "live search runs", debug.get("status") in {"ok", "degraded"},
               str(debug.get("status")))
    report.add("live", "live search is not degraded",
               not retrieval.get("degraded"),
               str(retrieval.get("degraded_reason") or ""))
    report.add("live", "parent context hydrated on the live index",
               bool(hydrated), f"hydrated={hydrated}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true",
                    help="also probe the running Lemonade server and the real index")
    ap.add_argument("--skip-unit", action="store_true", help="skip the unit suite")
    args = ap.parse_args(argv)

    started = time.time()
    report = Report()
    phase_environment(report)
    if not args.skip_unit:
        phase_unit_suite(report)
    else:
        print("\n=== 2. unit suite === (skipped)")

    server = StubServer()
    try:
        phase_round_trip(report, server)
    finally:
        server.stop()

    if args.live:
        phase_live(report)
    else:
        print("\n=== 5. live server and index === (skipped; pass --live)")

    report.summary()
    print(f"took {time.time() - started:.0f}s")
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
