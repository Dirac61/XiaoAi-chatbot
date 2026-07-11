from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from openai import AsyncOpenAI
from dotenv import load_dotenv
import os
import httpx

load_dotenv()

app = FastAPI(title="XiaoAi Agent", version="1.0.0")

API_KEY = os.getenv("API_KEY", "")
MODEL = os.getenv("MODEL", "")
API_BASE = os.getenv("API_BASE", "https://api.openai.com/v1")

client = AsyncOpenAI(
    api_key=API_KEY,
    base_url=API_BASE,
    timeout=httpx.Timeout(60.0, connect=30.0)
)

class ChatRequest(BaseModel):
    message: str

async def stream_model_response(message: str):
    response = await client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "你是一个有用的AI助手。"},
            {"role": "user", "content": message}
        ],
        stream=True
    )
    async for chunk in response:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/chat")
async def chat(request: ChatRequest):
    return StreamingResponse(
        stream_model_response(request.message),
        media_type="text/event-stream"
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)