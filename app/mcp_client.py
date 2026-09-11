"""
Thin MCP client wrapper — same pattern as job-intel-agent/app/mcp_client.py,
generalized here since DataPilot will have multiple MCP servers
(sql_tool now, python_tool + chart_tool in later steps).
"""

import asyncio
import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def _call_tool_async(server_script: str, tool_name: str, arguments: dict):
    server_params = StdioServerParameters(command=sys.executable, args=[server_script])
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments=arguments)
            texts = []
            for block in result.content:
                if hasattr(block, "text"):
                    try:
                        texts.append(json.loads(block.text))
                    except (json.JSONDecodeError, TypeError):
                        texts.append(block.text)
            return texts


def call_mcp_tool(server_script: str, tool_name: str, arguments: dict):
    """Returns the first parsed content block from the tool result, or an
    error dict if the call itself failed (server crash, connection issue)."""
    try:
        results = asyncio.run(_call_tool_async(server_script, tool_name, arguments))
        return results[0] if results else {"error": "[MCP_EMPTY_RESULT]"}
    except Exception as e:
        return {"error": f"[MCP_CLIENT_ERROR] {type(e).__name__}: {e}"}
