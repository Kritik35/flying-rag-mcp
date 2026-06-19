from __future__ import annotations
import asyncio
import json
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
    except Exception as e:
        result = {"error": str(e)}

    return [
        types.TextContent(
            type="text",
            text=json.dumps(result, ensure_ascii=False, indent=2),
        )
    ]


async def run():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())
