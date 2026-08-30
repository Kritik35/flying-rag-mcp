"""Embedding-model contract for flying-rag.

Why this exists
---------------
The vector table is named ``documents_{dim}``, so before this module the only
compatibility check between the indexed corpus and a live query was the vector
*dimension*. Qwen3-Embedding-0.6B and bge-m3 both emit 1024 floats. If the
embedding server is restarted with a different model loaded, queries get
embedded by one model against a corpus built by another — retrieval quality
collapses and nothing in the system says why.

So: the model the client *asks* for does not select the model on the server.
The server reports what it actually ran, and we compare that against the
configured model before trusting a vector. A real mismatch fails closed.

Comparison is normalized (case, path prefix, quantization/format suffix) and
bidirectional, because the same weights are legitimately named
``Qwen/Qwen3-Embedding-0.6B``, ``Qwen3-Embedding-0.6B-GGUF`` and
``qwen3-embedding-0.6b`` by different servers.
"""
from __future__ import annotations

import re

# Format / quantization tails that name the *packaging*, not the weights.
_PACKAGING_SUFFIXES = (
    "gguf", "ggml", "safetensors", "bin", "onnx", "mlx",
    "f16", "fp16", "f32", "fp32", "bf16",
    "int4", "int8", "4bit", "8bit",
)
_QUANT_TAIL_RE = re.compile(r"q\d(?:[_-][a-z0-9]+)*$")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


class EmbeddingContractError(RuntimeError):
    """The embedding server did not run the model this index was built with.

    Carries a stable machine-readable ``code`` so callers can surface a
    recovery action instead of a raw exception string.
    """

    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


def normalize_model_name(value: object) -> str:
    """Reduce a model identifier to comparable weights identity.

    ``Qwen/Qwen3-Embedding-0.6B-GGUF`` and ``qwen3_embedding_0.6b`` both
    normalize to ``qwen3embedding06b``.
    """
    text = str(value or "").strip().casefold()
    if not text:
        return ""
    # Repository / filesystem prefix: keep the leaf only.
    text = re.split(r"[\\/]", text)[-1]
    # Drop packaging and quantization tails, repeatedly (``-q4_k_m.gguf``).
    changed = True
    while changed:
        changed = False
        for suffix in _PACKAGING_SUFFIXES:
            for sep in (".", "-", "_"):
                tail = f"{sep}{suffix}"
                if text.endswith(tail) and len(text) > len(tail):
                    text = text[: -len(tail)]
                    changed = True
        stripped = _QUANT_TAIL_RE.sub("", text).rstrip("._-")
        if stripped and stripped != text:
            text = stripped
            changed = True
    return _NON_ALNUM_RE.sub("", text)


def models_compatible(expected: object, actual: object) -> bool:
    """True when two identifiers plausibly name the same weights.

    Bidirectional containment, so a server that reports a longer or shorter
    variant of the configured name still matches, while two genuinely different
    models (``qwen3embedding06b`` vs ``bgem3``) do not.
    """
    left = normalize_model_name(expected)
    right = normalize_model_name(actual)
    if not left or not right:
        return False
    return left in right or right in left


def check_response_model(
    expected: str,
    reported: object,
    *,
    require_report: bool = False,
) -> tuple[str, str]:
    """Grade one embedding response against the configured model.

    Returns ``(status, detail)`` where status is:

    - ``ok``          — server reported a compatible model;
    - ``unverified``  — server reported nothing (allowed unless
      ``require_report``); the caller records this in the trace;
    - and raises :class:`EmbeddingContractError` on an actual mismatch, or on a
      missing report when ``require_report`` is set.
    """
    reported_text = str(reported or "").strip()
    if not reported_text:
        if require_report:
            raise EmbeddingContractError(
                "embedding_model_unreported",
                f"server did not report a model; expected {expected!r}",
            )
        return "unverified", "server did not report a model"
    if not models_compatible(expected, reported_text):
        raise EmbeddingContractError(
            "embedding_contract_mismatch",
            f"expected {expected!r}, server ran {reported_text!r}",
        )
    return "ok", reported_text
