"""Validate the server against the official MCP Python SDK client (stdio).

Not one of the offline suites: it needs the `mcp` SDK (`pip install mcp`) and the network, since it
reads a live page (the default, or the URL given).

    python -X utf8 tests/mcp_sdk_client.py [URL]
"""
import asyncio
import os
import re
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(os.path.dirname(HERE), "scripts", "mcp_server.py")
URL = sys.argv[1] if len(sys.argv) > 1 else "https://developers.cloudflare.com/workers/"


def get(obj, *names, default=None):
    for n in names:
        v = getattr(obj, n, None)
        if v is not None:
            return v
    return default


async def main():
    params = StdioServerParameters(command=sys.executable,
                                   args=["-X", "utf8", SERVER],
                                   env=dict(os.environ))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            info = await session.initialize()
            print("initialize   protocol=%s server=%s v%s" % (
                get(info, "protocol_version", "protocolVersion"),
                get(get(info, "server_info", "serverInfo"), "name"),
                get(get(info, "server_info", "serverInfo"), "version")))
            tools = await session.list_tools()
            print("tools        %s" % [t.name for t in tools.tools])
            res = await session.call_tool("read_url", {"url": URL})
            # the answer's text says what a caller needs - its status, its folder (files:), the next line; the
            # result has no structured part (KNOWN-ISSUES 275)
            text = "".join(getattr(b, "text", "") or "" for b in res.content)
            folder = next((ln[len("files: "):ln.rindex(" (")] for ln in text.split("\n")
                           if ln.startswith("files: ") and " (" in ln), "")
            nxt = re.search(r"── next: line (\d+) of (\d+)", text)
            print("read_url     isError=%s structured=%s first line %r" % (
                get(res, "is_error", "isError"), get(res, "structured_content", "structuredContent"),
                text.split("\n")[0][:80]))
            print("blocks       %s" % [get(b, "type") for b in res.content])
            if nxt:
                more = await session.call_tool("read", {"dir": folder, "file": "content.md",
                                                        "from": int(nxt.group(1))})
                said = "".join(getattr(b, "text", "") or "" for b in more.content)
                print("read         %r" % (re.findall(r"── content\.md: lines \S+ of \d+", said) or [said[:60]])[0])
            else:
                print("read         (the page fit in one answer; reading from line 1)")
                more = await session.call_tool("read", {"dir": folder})
                said = "".join(getattr(b, "text", "") or "" for b in more.content)
                print("read         %r" % said.split("\n")[0][:80])


asyncio.run(main())
