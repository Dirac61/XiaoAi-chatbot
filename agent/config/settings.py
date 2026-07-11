import os
from dotenv import load_dotenv

load_dotenv()

AGENT_PORT = int(os.getenv("AGENT_PORT", 8000))
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8080")