from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from openai import AsyncOpenAI
from dotenv import load_dotenv
import os
import httpx
import logging
import asyncio

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logging.getLogger("XiaoAi Memory Service").setLevel(logging.DEBUG)
logger = logging.getLogger("XiaoAi Agent")

load_dotenv()

app = FastAPI(title="XiaoAi Agent", version="1.0.0")

API_KEY = os.getenv("API_KEY", "")
MODEL = os.getenv("MODEL", "")
API_BASE = os.getenv("API_BASE", "https://api.openai.com/v1")

logger.info(f"API_KEY 已配置: {'是' if API_KEY else '否'}")
logger.info(f"模型: {MODEL}")
logger.info(f"API地址: {API_BASE}")

client = AsyncOpenAI(
    api_key=API_KEY,
    base_url=API_BASE,
    timeout=httpx.Timeout(60.0, connect=30.0)
)

from typing import List, Optional
from services.memory_service import memory_service


class ChatRequest(BaseModel):
    message: str
    history: Optional[List[dict]] = None
    user_id: Optional[int] = None
    session_id: Optional[int] = None


class SummarizeRequest(BaseModel):
    messages: Optional[List[dict]] = None
    existing_summary: Optional[str] = None


async def stream_model_response(message: str, history: Optional[List[dict]] = None,
                                user_id: Optional[int] = None, session_id: Optional[int] = None):
    logger.info(f"收到消息: '{message}'")
    logger.info(f"历史消息数量: {len(history) if history else 0}")
    logger.info(f"用户ID: {user_id}, 会话ID: {session_id}")

    memories = []
    if session_id:
        try:
            memories = await memory_service.search_memories(message, session_id, top_k=5)
            logger.info(f"找到 {len(memories)} 条相关记忆")
        except Exception as e:
            logger.error(f"记忆检索失败: {e}")

    system_prompt = "你是高冷的真祖爱尔奎特。"

    if memories:
        memories_text = "\n".join([f"- {m['content']}" for m in memories])
        system_prompt += f"\n\n用户长期记忆：\n{memories_text}"

    messages = [{"role": "system", "content": system_prompt}]

    if history:
        for msg in history:
            role = msg.get("role")
            content = msg.get("content")
            if role and content:
                messages.append({"role": role, "content": content})
                logger.debug(f"添加历史消息: {role} - {content[:50]}...")

    messages.append({"role": "user", "content": message})
    logger.info(f"发送给模型的消息总数: {len(messages)}")

    assistant_response = ""

    try:
        response = await client.chat.completions.create(
            model=MODEL,
            messages=messages,
            stream=True
        )
        logger.info("成功连接到模型API")

        chunk_count = 0
        total_content = ""
        async for chunk in response:
            logger.debug(f"原始chunk: {chunk}")
            if chunk.choices:
                logger.debug(f"选项: {chunk.choices}")
                if chunk.choices[0].delta:
                    logger.debug(f"增量: {chunk.choices[0].delta}")
                    content = chunk.choices[0].delta.content
                    if content:
                        chunk_count += 1
                        total_content += content
                        assistant_response += content
                        logger.info(f"分片 {chunk_count}: '{content}'")
                        yield content

        logger.info(f"流传输完成, 总分片数: {chunk_count}, 总内容: '{total_content}'")

        if chunk_count == 0:
            logger.warning("未收到模型返回的内容")

    except Exception as e:
        logger.error(f"调用模型API出错: {str(e)}")
        yield f"错误: {str(e)}"

    if user_id and assistant_response:
        asyncio.create_task(
            memory_service.async_extract_and_store(
                message, assistant_response, user_id, session_id
            )
        )
        logger.info("已调度异步记忆提取和存储")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/chat")
async def chat(request: ChatRequest):
    logger.info(f"收到聊天请求: message='{request.message}', "
                f"history={len(request.history) if request.history else 0} 条, "
                f"user_id={request.user_id}, session_id={request.session_id}")
    return StreamingResponse(
        stream_model_response(request.message, request.history, request.user_id, request.session_id),
        media_type="text/event-stream"
    )


async def generate_summary(messages: Optional[List[dict]], existing_summary: Optional[str]):
    logger.info(f"生成摘要: 消息数量={len(messages) if messages else 0}, "
                f"已有摘要={'是' if existing_summary else '否'}")

    messages_text = ""
    if messages:
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            messages_text += f"{role}: {content}\n"
        logger.debug(f"消息文本: {messages_text[:200]}..." if len(messages_text) > 200
                     else f"消息文本: {messages_text}")

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
            logger.info(f"摘要生成成功: 长度={len(summary_content)}")
            return summary_content
        else:
            logger.warning("未收到模型返回的摘要内容")
            return None

    except Exception as e:
        logger.error(f"生成摘要出错: {str(e)}")
        return None


@app.post("/summarize")
async def summarize(request: SummarizeRequest):
    logger.info(f"收到摘要请求: 消息数量={len(request.messages) if request.messages else 0} 条")

    summary = await generate_summary(request.messages, request.existing_summary)

    if summary:
        return {"summary": summary}
    else:
        return {"summary": ""}


@app.on_event("startup")
async def startup():
    logger.info("初始化MemoryService...")
    memory_service.init()


if __name__ == "__main__":
    import uvicorn
    logger.info("启动XiaoAi Agent...")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)