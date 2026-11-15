"""Runs an asyncio event loop in a background thread.

Flask views are synchronous, while the MCP client and the Gemini client are
asynchronous and must keep living on the same event loop between requests.
"""

import asyncio
import threading


class AsyncRunner:
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self._thread.start()

    def run(self, coroutine, timeout=180):
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop).result(timeout)
