"""Source-verified retrieval measurement for flying-rag.

Why this replaces the old eval
------------------------------
`scripts/eval_retrieval.py` scored a case by looking for expected terms anywhere
in the retrieved blob — while `query_planner` was writing those same terms into
the query ("СП 7.13130 противодымная вентиляция ..." expanded a smoke-control
question, and the gold case then expected "7.13130"). A green run therefore
proved that the injected string came back, not that retrieval found the right
document. LES audited the identical pattern in their own harness and rated the
test programme 4/10 because of it.

This harness measures the thing that cannot be inflated that way:

- relevance is judged on the **source document**, never on a term in the text;
- `must_find` terms are searched in the retrieved **content only**, never in the
  file name, and by default must occur inside a single chunk;
- a case only counts when the contour actually ran: a `blocked` or `degraded`
  retrieval fails instead of quietly scoring;
- every case must be marked `verified` by a human who opened the source.

Modes
-----
    preflight   is this contour fit to measure at all?
    bootstrap   run the questions, dump candidates to verify by hand
    run         strict scoring against a verified golden set
    ab          two arms over the same index, same questions

Typical first use on a live machine:

    python scripts/rag_eval.py preflight
    python scripts/rag_eval.py bootstrap --questions golden/questions.json
    #  ... open the candidate file, keep the true sources, set verified: true
    python scripts/rag_eval.py run --gold golden/flying_rag_golden.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from evaluation.metrics import (  # noqa: E402
    aggregate,
    content_contains,
    evaluate_case,
    source_is_relevant,
)

GOLD_SCHEMA = "flying_rag.golden.v1"
DEFAULT_GOLD = ROOT / "golden" / "flying_rag_golden.json"
DEFAULT_QUESTIONS = ROOT / "golden" / "questions.json"


# ── case model ────────────────────────────────────────────────────────────────

def _case_field(raw: dict, key: str, default):
    value = raw.get(key, default)
    return default if value is None else value


def normalize_case(raw: dict) -> dict:
    return {
        "id": str(raw.get("id") or raw.get("query", "")[:40]),
        "query": str(raw["query"]),
        "dataset": raw.get("dataset") or None,
        "folder_filter": raw.get("folder_filter") or None,
        "verified": bool(raw.get("verified", False)),
        "source_any": [str(s) for s in _case_field(raw, "source_any", [])],
        "source_top_any": [str(s) for s in _case_field(raw, "source_top_any", [])],
        "source_top_k": int(_case_field(raw, "source_top_k", 3)),
        "forbid_sources": [str(s) for s in _case_field(raw, "forbid_sources", [])],
        "must_find": [str(s) for s in _case_field(raw, "must_find", [])],
        "must_find_same_chunk": bool(_case_field(raw, "must_find_same_chunk", True)),
        "min_top_score": float(_case_field(raw, "min_top_score", 0.0)),
        "note": str(raw.get("note") or ""),
    }


def load_gold(path: Path) -> list[dict]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = payload["cases"] if isinstance(payload, dict) else payload
    return [normalize_case(c) for c in cases]


def load_questions(path: Path) -> list[dict]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    items = payload["questions"] if isinstance(payload, dict) else payload
    out = []
    for item in items:
        if isinstance(item, str):
            out.append({"query": item})
        else:
            out.append(dict(item))
    return out


# ── search plumbing ───────────────────────────────────────────────────────────

def _search(query: str, *, top_k: int, dataset, folder_filter, rerank):
    from rag_server.tools import search_documents

    out = search_documents(
        query, top_k=top_k, dataset=dataset, folder_filter=folder_filter,
        rerank=rerank, use_cache=False, debug=True,
    )
    if isinstance(out, dict):
        return out.get("results", []) or [], out.get("debug", {}) or {}
    return out or [], {}


def _excerpt(result: dict, limit: int = 220) -> str:
    text = " ".join(str(result.get("child_text") or result.get("text") or "").split())
    return text[:limit]


# ── gates ─────────────────────────────────────────────────────────────────────

def check_case(case: dict, results: list[dict], trace: dict, k: int, gates: dict) -> list[str]:
    """Return the list of failure reasons; empty means the case passed."""
    failures: list[str] = []

    if gates.get("require_trace_ok"):
        status = trace.get("status", "unknown")
        if status != "ok":
            reason = trace.get("error_code") or trace.get("retrieval", {}).get(
                "degraded_reason", ""
            )
            failures.append(f"trace_status={status}" + (f" ({reason})" if reason else ""))

    if gates.get("require_parent_context") and results:
        if not any(str(r.get("context_source", "")).startswith("parent") for r in results):
            failures.append("no_parent_context")

    if not results:
        failures.append("no_results")
        return failures

    if case["source_any"] and not any(
        source_is_relevant(r, case["source_any"]) for r in results[:k]
    ):
        failures.append(f"source_any missing in top-{k}")

    if case["source_top_any"]:
        window = results[: max(1, case["source_top_k"])]
        if not any(source_is_relevant(r, case["source_top_any"]) for r in window):
            failures.append(f"source_top_any missing in top-{case['source_top_k']}")

    if case["forbid_sources"]:
        leaked = [
            r.get("file_name", "")
            for r in results[:k]
            if source_is_relevant(r, case["forbid_sources"])
        ]
        if leaked:
            failures.append(f"forbidden source retrieved: {sorted(set(leaked))[:3]}")

    if case["must_find"]:
        if case["must_find_same_chunk"]:
            ok = any(
                all(content_contains(r, term) for term in case["must_find"])
                for r in results[:k]
            )
            if not ok:
                failures.append("must_find not satisfied within one chunk")
        else:
            missing = [
                term
                for term in case["must_find"]
                if not any(content_contains(r, term) for r in results[:k])
            ]
            if missing:
                failures.append(f"must_find missing: {missing}")

    top_score = float(results[0].get("score") or 0.0)
    if case["min_top_score"] and top_score < case["min_top_score"]:
        failures.append(f"top_score {top_score:.3f} < {case['min_top_score']}")

    return failures


def _trace_digest(trace: dict) -> dict:
    retrieval = trace.get("retrieval", {}) or {}
    rerank = trace.get("rerank", {}) or {}
    return {
        "status": trace.get("status", ""),
        "route": trace.get("route", ""),
        "channels": retrieval.get("channels", []),
        "fusion": retrieval.get("fusion", ""),
        "score_kind": retrieval.get("score_kind", ""),
        "degraded": retrieval.get("degraded", False),
        "parent_hydrated": retrieval.get("parent_hydration", {}).get("hydrated"),
        "parent_fell_back": retrieval.get("parent_hydration", {}).get("fell_back_to_child"),
        "rerank_status": rerank.get("status", ""),
        "rerank_head_changed": rerank.get("head_changed"),
        "subqueries": trace.get("subqueries", []),
    }


# ── modes ─────────────────────────────────────────────────────────────────────

def cmd_preflight(args) -> int:
    """Refuse to measure a contour that is not in a measurable state."""
    from embedder.client import _DEFAULT_PROVIDER
    from embedder.contract import EmbeddingContractError
    from rag_server.tools import _db_paths
    from storage.index_manifest import load_manifest, verify_manifest
    from storage.vector_store import count_chunks

    lance_path, meta_path = _db_paths()
    problems: list[str] = []
    print("=== preflight ===")

    try:
        state = _DEFAULT_PROVIDER.verify_contract()
        print(f"  embedding server : {state['status']} "
              f"(expected {state['expected_model']}, served {state['actual_model'] or '?'})")
        if state["status"] == "unverified":
            print("    note: server does not report a model; contract cannot be proven")
    except EmbeddingContractError as ce:
        problems.append(f"embedding contract: {ce.code} — {ce.detail}")
        print(f"  embedding server : BLOCKED {ce.code}")
    except Exception as e:
        problems.append(f"embedding server unreachable: {e}")
        print(f"  embedding server : UNREACHABLE {e}")

    manifest = load_manifest(lance_path)
    if manifest is None:
        print("  index manifest   : absent (store predates the contract; will be "
              "written on the next index run)")
    else:
        _status, code, detail = verify_manifest(
            manifest, model=_DEFAULT_PROVIDER.get_model_name(),
            dimension=int(manifest.get("dimension") or 0),
        )
        if code:
            problems.append(f"index manifest: {code} — {detail}")
            print(f"  index manifest   : MISMATCH {code}")
        else:
            print(f"  index manifest   : ok ({manifest.get('model')}, "
                  f"dim={manifest.get('dimension')}, chunker={manifest.get('chunker')})")

    try:
        chunks = count_chunks(lance_path)
        print(f"  indexed chunks   : {chunks}")
        if chunks == 0:
            problems.append("store is empty")
    except Exception as e:
        problems.append(f"store unreadable: {e}")
        print(f"  indexed chunks   : ERROR {e}")

    print(f"  metadata db      : {meta_path} "
          f"({'present' if Path(meta_path).exists() else 'MISSING'})")
    if not Path(meta_path).exists():
        problems.append(f"metadata db missing at {meta_path}")

    # One live probe: does the contour return parent context and a healthy trace?
    probe = args.probe_query
    try:
        results, trace = _search(probe, top_k=5, dataset=None, folder_filter=None, rerank=None)
        digest = _trace_digest(trace)
        print(f"  probe query      : {probe!r} -> {len(results)} results")
        print(f"    status={digest['status']} channels={digest['channels']} "
              f"fusion={digest['fusion']} score_kind={digest['score_kind']}")
        # Counted over the whole candidate pool (all subqueries), not just the
        # returned top-k, so it can legitimately exceed the result count.
        print(f"    parent context in pool: hydrated={digest['parent_hydrated']} "
              f"fell_back_to_child={digest['parent_fell_back']}")
        if digest["status"] == "blocked":
            problems.append(f"probe blocked: {trace.get('error_code')}")
        if digest["degraded"]:
            problems.append(
                f"retrieval degraded: {trace.get('retrieval', {}).get('degraded_reason')}"
            )
        if results and not digest.get("parent_hydrated"):
            problems.append(
                "no result carried parent context — parent_chunks lookup is not working, "
                "answers are built from 150-token child chunks"
            )
    except Exception as e:
        problems.append(f"probe failed: {type(e).__name__}: {e}")
        print(f"  probe query      : ERROR {e}")

    print()
    if problems:
        print("NOT READY TO MEASURE:")
        for item in problems:
            print(f"  - {item}")
        return 1
    print("READY TO MEASURE")
    return 0


def cmd_bootstrap(args) -> int:
    """Run the questions and dump candidates for a human to verify."""
    questions = load_questions(Path(args.questions))
    out_cases = []
    print(f"=== bootstrap: {len(questions)} questions, top-{args.k} ===\n")

    for item in questions:
        query = item["query"]
        results, trace = _search(
            query, top_k=args.k, dataset=item.get("dataset"),
            folder_filter=item.get("folder_filter"), rerank=None,
        )
        print(f"--- {query}")
        if not results:
            status = trace.get("status", "")
            print(f"   (no results{f'; trace status={status}' if status else ''}) "
                  "— either the corpus lacks this, or retrieval missed it; "
                  "decide which before writing a case")
        candidates = []
        for i, r in enumerate(results, 1):
            name = r.get("file_name", "")
            print(f"   {i}. [{r.get('score')}] {name}")
            print(f"      {_excerpt(r)}")
            candidates.append({
                "rank": i,
                "file_name": name,
                "source_path": r.get("source_path", ""),
                "section": r.get("section", ""),
                "score": r.get("score"),
                "context_source": r.get("context_source", ""),
                "excerpt": _excerpt(r, 400),
            })
        print()
        out_cases.append({
            "id": item.get("id") or query[:40],
            "query": query,
            "dataset": item.get("dataset"),
            "folder_filter": item.get("folder_filter"),
            "verified": False,
            "_candidates": candidates,
            "_trace": _trace_digest(trace),
            "source_any": [],
            "source_top_any": [],
            "source_top_k": 3,
            "must_find": [],
            "must_find_same_chunk": True,
            "forbid_sources": [],
            "min_top_score": 0.0,
            "note": "fill source_any/source_top_any from the candidates you confirmed "
                    "by opening the file, then set verified: true and drop _candidates",
        })

    payload = {
        "schema": GOLD_SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "verified": False,
        "cases": out_cases,
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Candidates written: {out_path}")
    print("Verify each case by opening the source, then run `rag_eval.py run`.")
    return 0


def run_arm(cases: list[dict], k: int, rerank, gates: dict) -> tuple[dict, list[dict]]:
    per_case, rows = [], []
    for case in cases:
        started = time.time()
        results, trace = _search(
            case["query"], top_k=k, dataset=case["dataset"],
            folder_filter=case["folder_filter"], rerank=rerank,
        )
        expected = case["source_any"] or case["source_top_any"]
        metrics = evaluate_case(results, expected, k, relevance=source_is_relevant)
        failures = check_case(case, results, trace, k, gates)
        per_case.append(metrics)
        rows.append({
            "id": case["id"],
            "query": case["query"],
            "passed": not failures,
            "failures": failures,
            **metrics,
            "top_source": (results[0].get("file_name", "") if results else ""),
            "trace": _trace_digest(trace),
            "ms": int((time.time() - started) * 1000),
        })
    agg = aggregate(per_case, k)
    agg["passed"] = sum(1 for r in rows if r["passed"])
    agg["failed"] = sum(1 for r in rows if not r["passed"])
    return agg, rows


def _prepare_cases(args) -> list[dict] | None:
    cases = load_gold(Path(args.gold))
    if args.require_source_verification:
        unverified = [c["id"] for c in cases if not c["verified"]]
        no_source = [
            c["id"] for c in cases if not (c["source_any"] or c["source_top_any"])
        ]
        if unverified or no_source:
            print("REFUSING TO SCORE — the golden set is not source-verified:")
            if unverified:
                print(f"  unverified cases      : {unverified}")
            if no_source:
                print(f"  cases with no source  : {no_source}")
            print("\nA number produced from unverified cases is not a measurement.")
            print("Run `bootstrap`, confirm each source by opening the file, then retry.")
            return None
    return cases


def _print_arm(name: str, agg: dict, rows: list[dict], k: int) -> None:
    print(f"\n=== {name} (k={k}) ===")
    print(f"  passed: {agg['passed']}/{agg['passed'] + agg['failed']}")
    for key in (f"hit_rate@{k}", "mrr", f"mean_precision@{k}"):
        print(f"  {key}: {agg[key]:.4f}")
    failed = [r for r in rows if not r["passed"]]
    if failed:
        print("  failures:")
        for row in failed:
            print(f"    - {row['id']}: {'; '.join(row['failures'])}")
    degraded = [r for r in rows if r["trace"].get("degraded")]
    if degraded:
        print(f"  degraded retrievals: {len(degraded)}")


def cmd_run(args) -> int:
    cases = _prepare_cases(args)
    if cases is None:
        return 2
    gates = {
        "require_trace_ok": args.require_trace_ok,
        "require_parent_context": args.require_parent_context,
    }
    agg, rows = run_arm(cases, args.k, None, gates)
    _print_arm(args.label, agg, rows, args.k)
    _save({"k": args.k, "gates": gates, "arms": {args.label: {"aggregate": agg, "rows": rows}}},
          args.out)
    return 0 if agg["failed"] == 0 else 1


def cmd_ab(args) -> int:
    cases = _prepare_cases(args)
    if cases is None:
        return 2
    gates = {
        "require_trace_ok": args.require_trace_ok,
        "require_parent_context": args.require_parent_context,
    }
    report = {"k": args.k, "gates": gates, "arms": {}}
    arms = [("rerank_off", False), ("rerank_on", True)]
    for name, rerank in arms:
        agg, rows = run_arm(cases, args.k, rerank, gates)
        report["arms"][name] = {"aggregate": agg, "rows": rows}
        _print_arm(name, agg, rows, args.k)

    off = report["arms"]["rerank_off"]["aggregate"]
    on = report["arms"]["rerank_on"]["aggregate"]
    print("\n=== delta (on - off) ===")
    for key in (f"hit_rate@{args.k}", "mrr", f"mean_precision@{args.k}"):
        print(f"  {key}: {on[key] - off[key]:+.4f}")
    print(f"  passed: {on['passed'] - off['passed']:+d}")
    _save(report, args.out)
    return 0


def _save(report: dict, out: str | None) -> None:
    out_path = Path(out) if out else ROOT / "scratch" / "eval" / f"eval_{int(time.time())}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nReport saved: {out_path}")


# ── cli ───────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)

    pre = sub.add_parser("preflight", help="is this contour fit to measure?")
    pre.add_argument("--probe-query", default="требования к вентиляции")
    pre.set_defaults(func=cmd_preflight)

    boot = sub.add_parser("bootstrap", help="dump candidates to verify by hand")
    boot.add_argument("--questions", default=str(DEFAULT_QUESTIONS))
    boot.add_argument("--out", default=str(ROOT / "golden" / "candidates.json"))
    boot.add_argument("--k", type=int, default=8)
    boot.set_defaults(func=cmd_bootstrap)

    for name, func in (("run", cmd_run), ("ab", cmd_ab)):
        p = sub.add_parser(name, help="score against a verified golden set")
        p.add_argument("--gold", default=str(DEFAULT_GOLD))
        p.add_argument("--k", type=int, default=5)
        p.add_argument("--out", default=None)
        p.add_argument("--label", default=name)
        p.add_argument("--require-source-verification", action="store_true", default=True)
        p.add_argument("--allow-unverified", dest="require_source_verification",
                       action="store_false",
                       help="score anyway (the number is then not a measurement)")
        p.add_argument("--require-trace-ok", action="store_true", default=True)
        p.add_argument("--allow-degraded", dest="require_trace_ok", action="store_false")
        p.add_argument("--require-parent-context", action="store_true", default=True)
        p.add_argument("--allow-child-only", dest="require_parent_context",
                       action="store_false")
        p.set_defaults(func=func)

    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
