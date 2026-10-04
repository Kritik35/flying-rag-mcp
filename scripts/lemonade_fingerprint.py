# -*- coding: utf-8 -*-
"""Отпечаток Lemonade до обновления и сверка с ним после.

Индекс — это 1.4 млн векторов, посчитанных одной моделью в одной сборке
llama.cpp. Сверка контракта на старте сравнивает только имя модели и нарочно
не различает квантизации: Q8_0 и Q4_K_M одной модели для неё одно и то же. А
обновление Lemonade может принести и новую сборку llama.cpp, и другой файл
под тем же встроенным именем — запросы начнут кодироваться не так, как
документы, и поиск тихо испортится.

    python scripts\\lemonade_fingerprint.py save      # до обновления
    python scripts\\lemonade_fingerprint.py compare   # после

`save` записывает в data/lemonade_fingerprint.json версию Lemonade, контрольные
точки моделей, версию llama.cpp, векторы набора проб (документы и запросы —
через тот же клиент, что у сервера), оценки реранкера, и копирует конфиги
Lemonade (~/.cache/lemonade/*.json) в data/backups/lemonade-<время>.

`compare` повторяет пробы и сверяет; дополнительно пересчитывает 200 случайных
строк индекса и сравнивает с хранимыми векторами. Код выхода: 0 — совпадает,
1 — сдвиг в пределах шума квантизации, стоит посмотреть, 2 — векторы другие,
поиск по старому индексу будет неверным.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import random
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DOCS = [
    "Системы противодымной вентиляции следует предусматривать для удаления продуктов горения из коридоров.",
    "Кратность воздухообмена в помещениях уборочного инвентаря принимается не менее 1,5 ч-1.",
    "Воздуховоды систем общеобменной вентиляции выполняются из тонколистовой оцинкованной стали.",
    "Огнезадерживающие клапаны устанавливаются в местах пересечения воздуховодами противопожарных преград.",
    "Расчётная температура наружного воздуха для проектирования отопления принимается по СП 131.13330.",
    "Тепловой пункт оборудуется узлом учёта тепловой энергии и автоматикой погодного регулирования.",
    "Ширина эвакуационного выхода из коридора наружу принимается не менее 0,8 м.",
    "Спецификация оборудования, изделий и материалов. Поз. 1. Вентилятор радиальный, 1 шт.",
    "Duct sizing shall follow the equal friction method with velocities below 6 m/s in occupied zones.",
    "Насосная станция пожаротушения размещается в отдельном помещении первого или подвального этажа.",
]
QUERIES = [
    "кратность воздухообмена электрощитовой",
    "когда можно не делать систему дымоудаления",
    "огнезадерживающий клапан предел огнестойкости",
]
RERANK_QUERY = "предел огнестойкости огнезадерживающих клапанов"
INDEX_SAMPLE = 200

PASS_COS, WARN_COS = 0.999, 0.99
INDEX_PASS_COS = 0.998


def _out() -> Path:
    from config_loader import data_dir
    return data_dir() / "lemonade_fingerprint.json"


def _base_url() -> str:
    from config_loader import load_config
    return ((load_config() or {}).get("lemonade") or {}).get(
        "base_url", "http://localhost:13305/api/v1").rstrip("/")


def _get(path: str) -> dict:
    import urllib.request
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(_base_url() + path, timeout=30) as resp:
        return json.loads(resp.read())


def _post(path: str, body: dict) -> dict:
    import urllib.request
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(_base_url() + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with opener.open(req, timeout=120) as resp:
        return json.loads(resp.read())


def _models() -> tuple[str, str]:
    from config_loader import load_config
    from embedder.client import _DEFAULT_PROVIDER
    cfg = load_config() or {}
    rr = (cfg.get("retrieval") or {}).get("rerank_model", "bge-reranker-v2-m3-GGUF")
    return _DEFAULT_PROVIDER.get_model_name(), rr


def _server_state() -> dict:
    health = _get("/health")
    models = {m["id"]: m for m in _get("/models").get("data", [])}
    emb, rr = _models()
    cpu = Path.home() / ".cache" / "lemonade" / "bin" / "llamacpp" / "cpu" / "version.txt"
    return {
        "lemonade_version": health.get("version"),
        "llamacpp_cpu": cpu.read_text(encoding="utf-8").strip() if cpu.exists() else None,
        "embedding_model": emb,
        "embedding_checkpoint": (models.get(emb) or {}).get("checkpoint"),
        "embedding_options": (models.get(emb) or {}).get("recipe_options"),
        "rerank_model": rr,
        "rerank_checkpoint": (models.get(rr) or {}).get("checkpoint"),
    }


def _embed(texts: list[str], is_query: bool) -> list[list[float]]:
    from embedder.client import get_embeddings
    return get_embeddings(texts, is_query=is_query)


def _rerank() -> list[float]:
    from rag_server.reranker import build_rerank_payload
    _emb, rr = _models()
    payload = build_rerank_payload(RERANK_QUERY, [{"text": t} for t in DOCS], rr)
    results = _post("/reranking", payload).get("results", [])
    by_index = {int(r["index"]): float(r["relevance_score"]) for r in results}
    return [by_index.get(i, float("nan")) for i in range(len(DOCS))]


def _cos(a, b) -> float:
    import numpy as np
    a, b = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    if a.shape != b.shape:
        return float("-inf")
    return float(a @ b / ((np.linalg.norm(a) or 1.0) * (np.linalg.norm(b) or 1.0)))


def _backup_lemonade_config() -> Path | None:
    from config_loader import data_dir
    src = Path.home() / ".cache" / "lemonade"
    if not src.exists():
        return None
    dest = data_dir() / "backups" / f"lemonade-{dt.datetime.now():%Y%m%d-%H%M%S}"
    dest.mkdir(parents=True)
    for f in src.glob("*.json"):
        shutil.copy2(f, dest / f.name)
    resources = Path(os.path.expandvars(r"%LOCALAPPDATA%\lemonade_server\bin\resources"))
    for name in ("server_models.json", "backend_versions.json"):
        if (resources / name).exists():
            shutil.copy2(resources / name, dest / name)
    return dest


def save() -> int:
    state = _server_state()
    record = {
        "taken": dt.datetime.now().isoformat(timespec="seconds"),
        "state": state,
        "docs": _embed(DOCS, False),
        "queries": _embed(QUERIES, True),
        "rerank": _rerank(),
    }
    out = _out()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    backup = _backup_lemonade_config()
    print(json.dumps(state, ensure_ascii=False, indent=1))
    print(f"отпечаток: {out}")
    print(f"конфиги Lemonade: {backup}")
    return 0


def _index_sample() -> tuple[float, float, int]:
    import lancedb
    import numpy as np
    from config_loader import load_config, resolve
    cfg = load_config() or {}
    store = resolve(cfg.get("storage", {}).get("lancedb_path", "data/lancedb"))
    db = lancedb.connect(str(store))
    names = list(db.list_tables().tables) if hasattr(db, "list_tables") else db.table_names()
    table = db.open_table(next(n for n in names if n.startswith("documents_")))
    n = table.count_rows()
    rng = random.Random(20261004)
    offsets = sorted(rng.sample(range(n), min(INDEX_SAMPLE, n)))
    rows = [r for r in table.take_offsets(offsets).select(["text", "vector"]).to_list()
            if str(r.get("text") or "").strip()]
    fresh = []
    for i in range(0, len(rows), 8):
        fresh.extend(_embed([r["text"][:6000] for r in rows[i:i + 8]], False))
    cos = [_cos(r["vector"], v) for r, v in zip(rows, fresh)]
    return min(cos), float(np.median(cos)), len(cos)


def compare() -> int:
    saved = json.loads(_out().read_text(encoding="utf-8"))
    before, now = saved["state"], _server_state()
    worst = 0
    print(f"отпечаток от {saved['taken']}")
    for key in before:
        mark = "  " if before[key] == now.get(key) else "≠ "
        print(f"{mark}{key}: {before[key]}  →  {now.get(key)}")

    def grade(c: float) -> int:
        return 0 if c >= PASS_COS else (1 if c >= WARN_COS else 2)

    docs = [_cos(a, b) for a, b in zip(saved["docs"], _embed(DOCS, False))]
    queries = [_cos(a, b) for a, b in zip(saved["queries"], _embed(QUERIES, True))]
    for label, values in (("документы", docs), ("запросы", queries)):
        level = max(grade(c) for c in values)
        worst = max(worst, level)
        print(f"{['OK  ', 'WARN', 'FAIL'][level]} {label}: косинус min {min(values):.5f}")

    import math
    old_r, new_r = saved["rerank"], _rerank()
    same_order = sorted(range(len(old_r)), key=lambda i: -old_r[i]) == \
        sorted(range(len(new_r)), key=lambda i: -new_r[i])
    sig = lambda x: 1 / (1 + math.exp(-x))  # noqa: E731
    delta = max(abs(sig(a) - sig(b)) for a, b in zip(old_r, new_r))
    level = 0 if same_order and delta < 0.02 else (1 if same_order else 2)
    worst = max(worst, level)
    print(f"{['OK  ', 'WARN', 'FAIL'][level]} реранкер: порядок {'тот же' if same_order else 'ДРУГОЙ'}, "
          f"сдвиг оценок до {delta:.3f}")

    lo, med, count = _index_sample()
    level = 0 if lo >= INDEX_PASS_COS else (1 if lo >= WARN_COS else 2)
    worst = max(worst, level)
    print(f"{['OK  ', 'WARN', 'FAIL'][level]} индекс: {count} строк, косинус с пересчётом "
          f"min {lo:.5f}, медиана {med:.5f}")
    print(["совпадает с отпечатком", "небольшой сдвиг — проверьте эталон (rag_eval)",
           "векторы другие — поиск по старому индексу неверен; откатите Lemonade "
           "или переиндексируйте"][worst])
    return worst


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("cmd", choices=["save", "compare"])
    args = parser.parse_args(argv)
    return save() if args.cmd == "save" else compare()


if __name__ == "__main__":
    raise SystemExit(main())
