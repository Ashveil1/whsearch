"""Opt-in live MCP stdio smoke check. Makes public network requests."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def run() -> None:
    parameters = StdioServerParameters(
        command=sys.executable, args=["-m", "whsearch.mcp.server"], env=dict(os.environ)
    )
    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            calls: list[tuple[str, dict[str, Any]]] = [
                ("read_page", {"url": "https://github.com/psf/requests"}),
                ("search", {"query": "Python programming language", "limit": 3}),
                ("search_and_read", {"query": "Python programming language", "limit": 2}),
                (
                    "research",
                    {
                        "question": "Python programming language",
                        "max_queries": 1,
                        "max_pages": 2,
                        "max_rounds": 1,
                    },
                ),
            ]
            for name, arguments in calls:
                start = time.monotonic()
                try:
                    response = await session.call_tool(name, arguments)
                    content = response.structuredContent or {}
                    row: dict[str, Any] = {
                        "tool": name,
                        "seconds": round(time.monotonic() - start, 2),
                        "is_error": bool(response.isError),
                    }
                    if response.isError:
                        row["error"] = " ".join(
                            getattr(item, "text", "") for item in response.content
                        )[:300]
                    elif name == "read_page":
                        row.update(
                            url=content.get("url"),
                            title=content.get("title"),
                            characters=content.get("total_chars"),
                        )
                    elif name == "research":
                        row.update(
                            search_errors=content.get("search_errors"),
                            read_errors=content.get("read_errors"),
                            pages_attempted=content.get("pages_attempted"),
                            answer_present=bool(content.get("answer")),
                            sources=len(content.get("sources", [])),
                        )
                    else:
                        row["result_count"] = len(content.get("result", []))
                    print(json.dumps(row, ensure_ascii=False), flush=True)
                except Exception as exc:
                    print(
                        json.dumps(
                            {
                                "tool": name,
                                "seconds": round(time.monotonic() - start, 2),
                                "exception": type(exc).__name__,
                            }
                        ),
                        flush=True,
                    )


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
