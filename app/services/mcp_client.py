"""Long-lived MCP client session (streamable HTTP) used by the mentor engine."""

import json
from contextlib import AsyncExitStack

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


class MCPClient:
    def __init__(self, url):
        self.url = url
        self.session = None
        self.tools = []  # tool declarations in the format expected by Gemini
        self._stack = AsyncExitStack()

    async def connect(self):
        read_stream, write_stream = await self._stack.enter_async_context(streamable_http_client(self.url))
        self.session = await self._stack.enter_async_context(ClientSession(read_stream, write_stream))
        await self.session.initialize()

        listing = await self.session.list_tools()
        self.tools = [
            {"type": "function", "name": t.name, "description": t.description, "parameters": t.input_schema}
            for t in listing.tools
        ]

    async def close(self):
        await self._stack.aclose()

    async def call_raw(self, name, arguments):
        """Calls a tool and returns its result as text (what is sent back to the LLM)."""
        result = await self.session.call_tool(name, arguments=arguments)

        if result.structured_content:
            return json.dumps(result.structured_content, ensure_ascii=False)

        return "\n".join(c.text if hasattr(c, "text") else str(c) for c in result.content)

    async def call(self, name, arguments=None):
        """Calls a tool and returns its result as Python data."""
        text = await self.call_raw(name, arguments or {})

        try:
            return json.loads(text)
        except ValueError:
            return text
