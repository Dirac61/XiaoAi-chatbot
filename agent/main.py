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

class SummarizeRequest(BaseModel):
    messages: Optional[List[dict]] = None
    existing_summary: Optional[str] = None

async def stream_model_response(message: str, history: Optional[List[dict]] = None):
    logger.info(f"Received message: '{message}'")
    logger.info(f"History messages count: {len(history) if history else 0}")
    
    messages = [{"role": "system", "content": "你是高冷的真祖爱尔奎特。"}]
    
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

async def generate_summary(messages: Optional[List[dict]], existing_summary: Optional[str]):
    logger.info(f"Generating summary: messages count={len(messages) if messages else 0}, existing_summary={'Yes' if existing_summary else 'No'}")
    
    messages_text = ""
    if messages:
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            messages_text += f"{role}: {content}\n"
        logger.debug(f"Messages text: {messages_text[:200]}..." if len(messages_text) > 200 else f"Messages text: {messages_text}")
    
    system_prompt = """你是一个专业的对话摘要助手。请根据对话内容生成结构化事实摘要。
    
摘要要求：
1. 长度不超过500个字符
2. 使用JSON格式输出，包含以下字段：
   - "key_points": 关键要点数组（3-5条）
   - "entities": 涉及的实体/人物列表
   - "summary": 简短的自然语言摘要（100字以内）

示例输出格式：
{
  "key_points": ["要点1", "要点2", "要点3"],
  "entities": ["实体1", "实体2"],
  "summary": "简短摘要..."
}"""
    
    user_prompt = f"""请根据以下对话内容生成结构化事实摘要：

{"--- 已有摘要 ---" if existing_summary else ""}
{existing_summary if existing_summary else ""}

{"--- 新增对话内容 ---" if messages_text else ""}
{messages_text if messages_text else "无对话内容"}

请输出符合要求的JSON格式摘要。"""
    
    try:
        response = await client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            stream=False,
            temperature=0.3
        )
        
        if response.choices and response.choices[0].message and response.choices[0].message.content:
            summary_content = response.choices[0].message.content.strip()
            logger.info(f"Summary generated successfully: length={len(summary_content)}")
            return summary_content
        else:
            logger.warning("No summary content received from model")
            return None
            
    except Exception as e:
        logger.error(f"Error generating summary: {str(e)}")
        return None

@app.post("/summarize")
async def summarize(request: SummarizeRequest):
    logger.info(f"Summarize request received: messages={len(request.messages) if request.messages else 0} items")
    
    summary = await generate_summary(request.messages, request.existing_summary)
    
    if summary:
        return {"summary": summary}
    else:
        return {"summary": ""}

if __name__ == "__main__":
    import uvicorn
    logger.info("Starting XiaoAi Agent...")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)