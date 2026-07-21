import os
from dotenv import load_dotenv

load_dotenv()

AGENT_PORT = int(os.getenv("AGENT_PORT", 8000))
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8080")

API_KEY = os.getenv("API_KEY", "")
MODEL = os.getenv("MODEL", "")
API_BASE = os.getenv("API_BASE", "https://api.openai.com/v1")

QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", 6333))
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "user_memories")

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY", "")
EMBEDDING_API_BASE = os.getenv("EMBEDDING_API_BASE", "")

RERANK_MODEL = os.getenv("RERANK_MODEL", "qwen3-rerank")
RERANK_API_KEY = os.getenv("RERANK_API_KEY", "")
RERANK_API_BASE = os.getenv("RERANK_API_BASE", "")

EXTRACTION_MODEL = os.getenv("EXTRACTION_MODEL", "")
EXTRACTION_API_KEY = os.getenv("EXTRACTION_API_KEY", "")
EXTRACTION_API_BASE = os.getenv("EXTRACTION_API_BASE", "")

SEARCH_API_KEY = os.getenv("SEARCH_API_KEY", "")
SEARCH_API_BASE = os.getenv("SEARCH_API_BASE", "")
SEARCH_MAX_RESULTS = int(os.getenv("SEARCH_MAX_RESULTS", "5"))
SEARCH_MAX_CONTENT_LENGTH = int(os.getenv("SEARCH_MAX_CONTENT_LENGTH", "500"))