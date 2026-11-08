import asyncio
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_mcp_client_lists_tools_and_gets_a_verdict():
    async def go():
        params = StdioServerParameters(command=sys.executable, args=["-m", "warrant.mcp_server"],
                                        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")})
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                names = {t.name for t in (await s.list_tools()).tools}
                res = await s.call_tool("decide_dispute", {"dispute_id": "PP-R-DEMO-103"})
                return names, res.structuredContent or res.content[0].text
    names, out = asyncio.run(go())
    assert names == {"decide_dispute", "get_receipt", "explain_dispute"}
    assert "OVERSTEPPED" in str(out)
