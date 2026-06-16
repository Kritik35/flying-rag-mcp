"""Offline retrieval-quality eval for flying-rag (RAGAS-style, no LLM judge).

Runs a gold set of queries through search_documents and reports Hit@k / MRR /
Precision@k. With --ab it compares reranker OFF vs ON to quantify its effect.

Usage:
    python scripts/eval_retrieval.py            # baseline metrics
    python scripts/eval_retrieval.py --ab       # rerank OFF vs ON comparison
    python scripts/eval_retrieval.py --k 8 --gold my_gold.json

Gold file (optional) is JSON: [{"query","dataset","expected_any":[...]}, ...].
Results are also written to scratch/eval/ (gitignored).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from evaluation.metrics import aggregate, evaluate_case  # noqa: E402

# Gold set — expected sources verified retrievable in the live index (2026-06).
GOLD = [
    {"query": "противодымная вентиляция ОВ2", "dataset": None, "expected_any": ["ов2"]},
    {"query": "Где нужна противодымная вентиляция?", "dataset": "normative", "expected_any": ["7.13130", "противодым"]},
    {"query": "кратность воздухообмена в помещениях", "dataset": "normative", "expected_any": ["воздухообмен", "вентиляц"]},
    {"query": "температура теплоносителя в системе отопления", "dataset": "normative", "expected_any": ["отоплен", "теплоносител"]},
    {"query": "доступность зданий для маломобильных групп населения", "dataset": "normative", "expected_any": ["59.13330", "маломобильн", "доступност"]},
    {"query": "класс бетона по прочности на сжатие", "dataset": "normative", "expected_any": ["бетон", "63.13330", "41.13330"]},
    {"query": "автоматическая пожарная сигнализация и оповещение", "dataset": "normative", "expected_any": ["пожарн", "сигнализац", "оповещен"]},
    {"query": "ширина эвакуационных путей и выходов", "dataset": "normative", "expected_any": ["1.13130", "эвакуац", "выход"]},
    {"query": "дымоудаление из подземной автостоянки", "dataset": "normative", "expected_any": ["7.13130", "дымоудал", "автостоянк"]},
    {"query": "рекуперация теплоты вентиляции", "dataset": "normative", "expected_any": ["рекупер", "утилизац", "60.13330"]},
]


def load_gold(path: str | None) -> list[dict]:
    if not path:
        return GOLD
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def run_arm(gold: list[dict], k: int, rerank) -> tuple[dict, list[dict]]:
    from rag_server.tools import search_documents

    per_case = []
    rows = []
    for case in gold:
        out = search_documents(
            case["query"], top_k=k, dataset=case.get("dataset"),
            rerank=rerank, use_cache=False,
        )
        results = out if isinstance(out, list) else out.get("results", [])
        m = evaluate_case(results, case["expected_any"], k)
        per_case.append(m)
        rows.append({"query": case["query"], **m,
                     "top": (results[0].get("file_name", "") if results else "")[:45]})
    return aggregate(per_case, k), rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--ab", action="store_true", help="compare rerank OFF vs ON")
    ap.add_argument("--gold", default=None)
    args = ap.parse_args(argv)

    gold = load_gold(args.gold)
    out_dir = ROOT / "scratch" / "eval"
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {"k": args.k, "n": len(gold), "arms": {}}

    arms = [("rerank_off", False), ("rerank_on", True)] if args.ab else [("default", None)]
    for name, rerank in arms:
        t0 = time.time()
        agg, rows = run_arm(gold, args.k, rerank)
        agg["wall_sec"] = round(time.time() - t0, 1)
        report["arms"][name] = {"aggregate": agg, "rows": rows}
        print(f"\n=== {name} (k={args.k}) ===")
        for key, val in agg.items():
            print(f"  {key}: {val}")

    if args.ab:
        off = report["arms"]["rerank_off"]["aggregate"]
        on = report["arms"]["rerank_on"]["aggregate"]
        print("\n=== DELTA (on - off) ===")
        for key in (f"hit_rate@{args.k}", "mrr", f"mean_precision@{args.k}"):
            print(f"  {key}: {on[key] - off[key]:+.4f}")

    out_path = out_dir / f"eval_{int(time.time())}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\nReport saved: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
