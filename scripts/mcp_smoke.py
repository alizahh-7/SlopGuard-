import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER = str(Path(__file__).resolve().parent.parent / "mcp_server" / "server.py")


async def main():
    params = StdioServerParameters(command=sys.executable, args=[SERVER])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("TOOLS:", [t.name for t in tools.tools])
            res = await session.call_tool(
                "check_packages",
                {"packages": ["requests", "slopguard-demo-phantom-pkg-93817"], "ecosystem": "pypi"},
            )
            print(res.content[0].text)
            res = await session.call_tool(
                "check_install_command", {"command": "pip install requests slopguard-demo-phantom-pkg-93817"}
            )
            print(res.content[0].text)


asyncio.run(main())
