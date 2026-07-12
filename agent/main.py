from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from openai import AsyncOpenAI
from dotenv import load_dotenv
import os
import httpx
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("XiaoAi Agent")

load_dotenv()

app = FastAPI(title="XiaoAi Agent", version="1.0.0")

API_KEY = os.getenv("API_KEY", "")
MODEL = os.getenv("MODEL", "")
API_BASE = os.getenv("API_BASE", "https://api.openai.com/v1")

logger.info(f"API_KEY configured: {'Yes' if API_KEY else 'No'}")
logger.info(f"MODEL: {MODEL}")
logger.info(f"API_BASE: {API_BASE}")

client = AsyncOpenAI(
    api_key=API_KEY,
    base_url=API_BASE,
    timeout=httpx.Timeout(60.0, connect=30.0)
)

from typing import List, Optional

class ChatRequest(BaseModel):
    message: str
    history: Optional[List[dict]] = None

async def stream_model_response(message: str, history: Optional[List[dict]] = None):
    logger.info(f"Received message: '{message}'")
    logger.info(f"History messages count: {len(history) if history else 0}")
    
    messages = [{"role": "system", "content": "你是真祖爱尔奎特。"}]
    
    if history:
        for msg in history:
            role = msg.get("role")
            content = msg.get("content")
            if role and content:
                messages.append({"role": role, "content": content})
                logger.debug(f"Added history message: {role} - {content[:50]}...")
    
    messages.append({"role": "user", "content": message})
    logger.info(f"Total messages to model: {len(messages)}")
    
    try:
        response = await client.chat.completions.create(
            model=MODEL,
            messages=messages,
            stream=True
        )
        logger.info("Connected to model API successfully")
        
        chunk_count = 0
        total_content = ""
        async for chunk in response:
            logger.debug(f"Raw chunk: {chunk}")
            if chunk.choices:
                logger.debug(f"Choices: {chunk.choices}")
                if chunk.choices[0].delta:
                    logger.debug(f"Delta: {chunk.choices[0].delta}")
                    content = chunk.choices[0].delta.content
                    if content:
                        chunk_count += 1
                        total_content += content
                        logger.info(f"Chunk {chunk_count}: '{content}'")
                        yield content
        
        logger.info(f"Stream completed, total chunks: {chunk_count}, total content: '{total_content}'")
        
        if chunk_count == 0:
            logger.warning("No content received from model")
            
    except Exception as e:
        logger.error(f"Error calling model API: {str(e)}")
        yield f"Error: {str(e)}"

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/chat")
async def chat(request: ChatRequest):
    logger.info(f"Chat request received: message='{request.message}', history={len(request.history) if request.history else 0} items")
    return StreamingResponse(
        stream_model_response(request.message, request.history),
        media_type="text/event-stream"
    )

if __name__ == "__main__":
    import uvicorn
    logger.info("Starting XiaoAi Agent...")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)