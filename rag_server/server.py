from __future__ import annotations
import asyncio
import json
import logging
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from rag_server.tools import (
    get_tool_definitions, search_documents, list_indexed, reindex_path,
    graph_neighbors, search_rules, reindex_status, extract_structured_values,
    locate_quote,
    search_drawings, sum_table_values, get_table
)

# Eagerly import retrieval dependencies to avoid import locks in asyncio worker threads
import embedder.client
import storage.vector_store
import storage.semantic_cache
import storage.metadata_db
import rag_server.query_planner
import rag_server.retrieval_quality
import rag_server.rerank_policy
import rag_server.named_norms
import rag_server.query_router
import storage.source_focus
import rag_server.norm_resolver

app = Server("flying-rag")
logger = logging.getLogger(__name__)
_ABS_PATH_RE = re.compile(
    r"(?:(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\"'\r\n,}\]]*?\.[A-Za-z0-9]{1,12}"
    r"|(?<![:/])/(?:[^/\"'\r\n,}\]]+/)+[^/\"'\r\n,}\]]*?\.[A-Za-z0-9]{1,12})"
)
_URL_RE = re.compile(r"https?://[^\s\"']+", re.IGNORECASE)
_LOCAL_PATH_PREFIX_RE = re.compile(
    r"(?:(?<![A-Za-z0-9])[A-Za-z]:[\\/]|\\\\|(?:^|\s)/(?!/))"
)
_DIAGNOSTIC_KEYS = {"message", "error", "detail", "debug"}


def _contains_local_path(value: str) -> bool:
    without_urls = _URL_RE.sub("", value)
    return bool(_LOCAL_PATH_PREFIX_RE.search(without_urls))


def _safe_result(value, key: str | None = None, diagnostic: bool = False):
    """Remove filesystem details and raw exception text from MCP payloads."""
    if isinstance(value, list):
        return [_safe_result(item, key=key, diagnostic=diagnostic) for item in value]
    if isinstance(value, str):
        if key and key.endswith("path"):
            return Path(value).name if diagnostic else value
        if diagnostic and key in _DIAGNOSTIC_KEYS and _contains_local_path(value):
            return "internal_error"
        value = _ABS_PATH_RE.sub("[redacted-path]", value)
        return value
    if not isinstance(value, dict):
        return value
    local_diagnostic = diagnostic or bool(value.get("error")) or value.get("status") in {
        "error", "failed", "partial"
    }
    safe = {}
    for key, item in value.items():
        if key in {"error", "exception", "traceback"}:
            # Only an actual diagnostic gets replaced. Rewriting an empty value
            # invents a failure: the retrieval trace carries `error: ""` on a
            # healthy search, and every one of them reached the client as
            # `internal_error`.
            safe[key] = "internal_error" if item else item
        else:
            safe[key] = _safe_result(item, key=key, diagnostic=local_diagnostic)
    return safe


_shadow_adapter = None
_shadow_initialized = False


def reset_shadow_adapter():
    """Reset shadow adapter state (for configuration reloading and testing) (S1)."""
    global _shadow_adapter, _shadow_initialized
    if _shadow_adapter is not None:
        adapter = _shadow_adapter
        _shadow_adapter = None
        _shadow_initialized = False
        if hasattr(adapter, "shutdown"):
            try:
                adapter.shutdown(wait=False)
            except Exception:
                pass
    else:
        _shadow_initialized = False


def shutdown_shadow_adapter(timeout: float = 5.0):
    """Gracefully shutdown shadow background thread pool and clear state (S1 / Blocker B8)."""
    global _shadow_adapter, _shadow_initialized
    if _shadow_adapter is not None:
        adapter = _shadow_adapter
        _shadow_adapter = None
        _shadow_initialized = False
        if hasattr(adapter, "shutdown"):
            try:
                adapter.shutdown(wait=True, timeout=timeout)
            except Exception as e:
                logger.warning(f"Error shutting down shadow adapter: {e}")


def _get_shadow_adapter(force_reload: bool = False):
    global _shadow_adapter, _shadow_initialized
    if force_reload:
        reset_shadow_adapter()

    # Dynamic check for runtime disable without restart (Blocker B8)
    env_val = os.environ.get("FLYING_RAG_SHADOW_EIG", "").strip().lower()
    if env_val in ("0", "false", "no", "off", "disable", "disabled"):
        return None

    if not _shadow_initialized:
        _shadow_initialized = True
        try:
            from config_loader import load_config, ROOT
            cfg = load_config()

            ctrl_file_raw = os.environ.get("FLYING_RAG_SHADOW_CONTROL_FILE", "").strip()
            if not ctrl_file_raw:
                ctrl_file_raw = (cfg.get("evidence_gate") or {}).get("shadow_control_file", "")
            ctrl_file_path = Path(ctrl_file_raw) if ctrl_file_raw else None

            # Strict environment variable precedence (P1-09)
            if env_val in ("1", "true", "yes", "on", "enable", "enabled"):
                shadow_enabled = True
            else:
                shadow_enabled = bool((cfg.get("evidence_gate") or {}).get("shadow_enabled", False))

            if shadow_enabled:
                from rag_server.shadow_eig import ShadowEvidenceIntegrityGate
                meta_raw = os.environ.get("FLYING_RAG_METADATA_DB", "").strip()
                if not meta_raw:
                    meta_raw = (cfg.get("storage") or {}).get("metadata_db", "data/metadata.db")
                meta_path = Path(meta_raw)
                if not meta_path.is_absolute():
                    meta_path = (ROOT / meta_path).resolve()

                if not meta_path.exists():
                    logger.warning(
                        f"[SHADOW_EIG_INIT_WARNING] Metadata database not found at {meta_path}. Shadow EIG disabled."
                    )
                    _shadow_adapter = None
                else:
                    _shadow_adapter = ShadowEvidenceIntegrityGate(
                        metadata_db_path=meta_path,
                        enabled=True,
                        control_file_path=ctrl_file_path
                    )
        except Exception as e:
            logger.warning(f"[SHADOW_EIG_INIT_WARNING] Failed to initialize shadow EIG adapter: {e}")
            _shadow_adapter = None

    if _shadow_adapter is not None and hasattr(_shadow_adapter, "is_active") and not _shadow_adapter.is_active():
        return None

    return _shadow_adapter


def _dispatch(name: str, arguments: dict):
    if name == "search_documents":
        # rerank: pass None through (auto mode); coerce only explicit bools
        rerank = arguments.get("rerank")
        if rerank is not None:
            rerank = bool(rerank)
        results = search_documents(
            query=arguments["query"],
            folder_filter=arguments.get("folder_filter"),
            top_k=int(arguments.get("top_k", 5)),
            dataset=arguments.get("dataset"),
            rerank=rerank,
            alpha=float(arguments.get("alpha", 0.7)),
            use_cache=bool(arguments.get("use_cache", True)),
            debug=bool(arguments.get("debug", False)),
            include_visual=bool(arguments.get("include_visual", False)),
        )
        shadow = _get_shadow_adapter()
        if shadow and getattr(shadow, "is_active", lambda: True)():
            try:
                ret_list = results if isinstance(results, list) else (results.get("results") if isinstance(results, dict) else None)
                # Non-blocking async fire-and-forget submission with snapshot (Blocker B1)
                shadow.observe_async(arguments["query"], retrieval_results=ret_list)
            except Exception as e:
                logger.warning(f"Shadow EIG observation error: {e}")
        return results
    elif name == "extract_structured_values":
        return extract_structured_values(
            label=arguments["label"],
            source_like=arguments.get("source_like"),
            limit=int(arguments.get("limit", 500)),
            max_rows=int(arguments.get("max_rows", 50)),
        )
    elif name == "search_drawings":
        return search_drawings(
            query=arguments["query"],
            top_k=int(arguments.get("top_k", 5)),
            folder_filter=arguments.get("folder_filter"),
            dataset=arguments.get("dataset"),
        )
    elif name == "sum_table_values":
        return sum_table_values(
            subject=arguments["subject"],
            source_like=arguments.get("source_like"),
            field=arguments.get("field"),
            op=arguments.get("op", "sum"),
            dataset=arguments.get("dataset"),
        )
    elif name == "get_table":
        return get_table(
            source_like=arguments["source_like"],
            section=arguments.get("section"),
            subject=arguments.get("subject"),
            group_by=arguments.get("group_by"),
            max_rows=int(arguments.get("max_rows", 200)),
            dataset=arguments.get("dataset"),
        )
    elif name == "search_rules":
        return search_rules(
            query=arguments["query"],
            subject=arguments.get("subject"),
            parameter=arguments.get("parameter"),
            limit=int(arguments.get("limit", 10)),
        )
    elif name == "list_indexed":
        return list_indexed(
            folder_filter=arguments.get("folder_filter"),
            limit=int(arguments.get("limit", 50)),
            dataset=arguments.get("dataset"),
        )
    elif name == "locate_quote":
        return locate_quote(
            quote=arguments.get("quote", ""),
            source_path=arguments.get("source_path", "") or "",
            file_name=arguments.get("file_name", "") or "",
        )
    elif name == "graph_neighbors":
        return graph_neighbors(
            doc_id=arguments["doc_id"],
            top_k=int(arguments.get("top_k", 5)),
        )
    elif name == "reindex_path":
        return reindex_path(
            path=arguments["path"],
            force=bool(arguments.get("force", False)),
            use_cache=bool(arguments.get("use_cache", True)),
        )
    elif name == "reindex_status":
        return reindex_status(
            job_id=arguments.get("job_id"),
            limit=int(arguments.get("limit", 20)),
        )
    else:
        return {"error": f"Unknown tool: {name}"}


@app.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name=d["name"],
            description=d["description"],
            inputSchema=d["inputSchema"],
        )
        for d in get_tool_definitions()
    ]


@app.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    try:
        result = await asyncio.to_thread(_dispatch, name, arguments)
    except Exception:
        logger.exception("MCP tool failed: %s", name)
        result = {"error": "internal_error"}

    result = _safe_result(result)

    return [
        types.TextContent(
            type="text",
            text=json.dumps(result, ensure_ascii=False, indent=2),
        )
    ]


async def run():
    try:
        async with stdio_server() as (read_stream, write_stream):
            await app.run(read_stream, write_stream, app.create_initialization_options())
    finally:
        shutdown_shadow_adapter(timeout=3.0)


if __name__ == "__main__":
    asyncio.run(run())
