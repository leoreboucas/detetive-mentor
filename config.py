import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key")

    # LLM (Google Gemini, same provider used in the course examples)
    GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
    MENTOR_MODEL = os.environ.get("MENTOR_MODEL", "gemini-3.5-flash-lite")
    JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "gemini-3.1-flash-lite")

    # MCP tools server (mcp_server/server.py)
    MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://localhost:8000/mcp")

    # semantic cache
    CACHE_ENABLED = os.environ.get("CACHE_ENABLED", "true").lower() == "true"
    CACHE_PATH = str(BASE_DIR / "data" / "cache")
    CACHE_COLLECTION = "detetive_mentor_cache"
    CACHE_EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    CACHE_DISTANCE_THRESHOLD = float(os.environ.get("CACHE_DISTANCE_THRESHOLD", "0.12"))
