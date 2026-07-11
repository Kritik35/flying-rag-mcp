from __future__ import annotations
import asyncio
import json
import logging
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
    search_drawings, sum_table_values
)

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
            safe[key] = "internal_error"
        else:
            safe[key] = _safe_result(item, key=key, diagnostic=local_diagnostic)
    return safe


def _dispatch(name: str, arguments: dict):
    if name == "search_documents":
        # rerank: pass None through (auto mode); coerce only explicit bools
        rerank = arguments.get("rerank")
        if rerank is not None:
            rerank = bool(rerank)
        return search_documents(
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
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())
