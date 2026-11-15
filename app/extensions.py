"""Creates the mentor engine and its dependencies once, when the app starts."""

from flask import current_app

from app.services import llm
from app.services.async_runner import AsyncRunner
from app.services.mcp_client import MCPClient
from app.services.mentor import MentorEngine
from app.services.semantic_cache import SemanticCache


class _DisabledCache:
    enabled = False

    def get(self, *args):
        return None

    def put(self, *args):
        pass


def init_mentor(app):
    config = app.config
    runner = AsyncRunner()

    mcp_client = MCPClient(config["MCP_SERVER_URL"])
    try:
        runner.run(mcp_client.connect(), timeout=30)
    except Exception as error:
        raise RuntimeError(
            f"Could not connect to the MCP server at {config['MCP_SERVER_URL']}. "
            "Start it first with: python -m mcp_server.server"
        ) from error

    app.logger.info("MCP tools: %s", [t["name"] for t in mcp_client.tools])

    if config["CACHE_ENABLED"]:
        cache = SemanticCache(
            config["CACHE_EMBEDDING_MODEL"],
            config["CACHE_PATH"],
            config["CACHE_COLLECTION"],
            config["CACHE_DISTANCE_THRESHOLD"],
        )
    else:
        cache = _DisabledCache()

    engine = MentorEngine(llm.create_client(config["GOOGLE_API_KEY"]), mcp_client, cache, config["MENTOR_MODEL"])

    app.extensions["async_runner"] = runner
    app.extensions["mentor"] = engine


def get_mentor():
    return current_app.extensions["mentor"]


def run_async(coroutine):
    return current_app.extensions["async_runner"].run(coroutine)
