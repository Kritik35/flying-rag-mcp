# -*- coding: utf-8 -*-
"""HyDE (Hypothetical Document Embeddings) — pre-retrieval query expansion.

DORMANT BY DEFAULT. Controlled entirely by config.yaml -> hyde.enabled (false).
When disabled (or on ANY error) generate_hypothetical() returns None and the
caller transparently falls back to the raw query, so behaviour is unchanged and
the live index / MCP server are never at risk.

Idea: instead of embedding the user's short question, ask an LLM to write a
short *hypothetical answer passage* in the language of the corpus (normative
Russian) and embed THAT. The hypothetical passage lives much closer to the real
document chunks in embedding space, which lifts recall on paraphrased / lay
queries (e.g. "роторный рекуператор" -> "утилизация теплоты вытяжного воздуха").

Backends (config hyde.backend):
  * "off"  — disabled (default).
  * "npu"  — local lemonade LLM on the NPU (no network, no rate limit).
             Reuses the rules model (qwen3.5-9b-FLM) already loaded on backend.
  * "api"  — external OpenAI-compatible provider (OpenRouter etc.), key from
             env HYDE_API_KEY or OPENROUTER_API_KEY.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

_PROMPT = (
    "Ты — инженер-нормоконтролёр. Напиши один короткий абзац (3–5 предложений) "
    "так, как он мог бы выглядеть в тексте российского нормативного или проектного "
    "документа (СП, ГОСТ, рабочая документация), отвечающего на запрос ниже. "
    "Пиши терминами норматива, без вводных слов и без ссылок на источник.\n\n"
    "Запрос: {q}\n\nФрагмент:"
)


def _hyde_cfg() -> dict:
    try:
        import yaml
        with open(ROOT / "config.yaml", encoding="utf-8") as f:
            return (yaml.safe_load(f) or {}).get("hyde", {}) or {}
    except Exception:
        return {}


def is_enabled() -> bool:
    cfg = _hyde_cfg()
    return bool(cfg.get("enabled", False)) and cfg.get("backend", "off") != "off"


def _chat(url: str, model: str, prompt: str, api_key: str | None,
          max_tokens: int, timeout: float) -> str | None:
    import json
    import urllib.request

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.3,
        "stream": False,
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(
        url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"].strip() or None


def generate_hypothetical(query: str) -> str | None:
    """Return a hypothetical passage for `query`, or None if disabled/failed."""
    cfg = _hyde_cfg()
    if not cfg.get("enabled", False):
        return None
    backend = cfg.get("backend", "off")
    if backend == "off":
        return None

    query = (query or "").strip()
    if not query:
        return None

    prompt = _PROMPT.format(q=query)
    max_tokens = int(cfg.get("max_tokens", 200))
    timeout = float(cfg.get("timeout_sec", 20))

    try:
        if backend == "npu":
            url = cfg.get("base_url") or "http://localhost:13305/api/v1"
            model = cfg.get("model") or "qwen3.5-9b-FLM"
            return _chat(url, model, prompt, api_key=None,
                         max_tokens=max_tokens, timeout=timeout)
        if backend == "api":
            url = cfg.get("base_url") or "https://openrouter.ai/api/v1"
            model = cfg.get("model") or "google/gemma-4-31b-it:free"
            key = (cfg.get("api_key") or os.getenv("HYDE_API_KEY")
                   or os.getenv("OPENROUTER_API_KEY"))
            if not key:
                print("[hyde] api backend has no API key; skipping", file=sys.stderr)
                return None
            return _chat(url, model, prompt, api_key=key,
                         max_tokens=max_tokens, timeout=timeout)
    except Exception as e:  # network / model / timeout — never break search
        print(f"[hyde] generation skipped: {e}", file=sys.stderr)
        return None
    return None
