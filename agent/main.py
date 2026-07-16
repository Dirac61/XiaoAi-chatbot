from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from openai import AsyncOpenAI
from dotenv import load_dotenv
from contextlib import asynccontextmanager
import os
import httpx
import logging
import asyncio
import json

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logging.getLogger("XiaoAi Memory Service").setLevel(logging.DEBUG)
logger = logging.getLogger("XiaoAi Agent")

load_dotenv()

from services.memory_service import memory_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("初始化MemoryService...")
    memory_service.init()
    yield


app = FastAPI(title="XiaoAi Agent", version="1.0.0", lifespan=lifespan)

API_KEY = os.getenv("API_KEY", "")
MODEL = os.getenv("MODEL", "")
API_BASE = os.getenv("API_BASE", "https://api.openai.com/v1")

MULTIMODAL_MODEL = os.getenv("MULTIMODAL_MODEL", MODEL)
MULTIMODAL_API_KEY = os.getenv("MULTIMODAL_API_KEY", API_KEY)
MULTIMODAL_API_BASE = os.getenv("MULTIMODAL_API_BASE", API_BASE)
USE_MULTIMODAL = os.getenv("USE_MULTIMODAL", "false").lower() == "true"

OCR_MODEL = os.getenv("OCR_MODEL") or MULTIMODAL_MODEL
OCR_API_KEY = os.getenv("OCR_API_KEY") or MULTIMODAL_API_KEY
OCR_API_BASE = os.getenv("OCR_API_BASE") or MULTIMODAL_API_BASE

logger.info(f"文本模型 - API_KEY: {'是' if API_KEY else '否'}, 模型: {MODEL}, 地址: {API_BASE}")
logger.info(f"多模态模型 - API_KEY: {'是' if MULTIMODAL_API_KEY else '否'}, 模型: {MULTIMODAL_MODEL}, 地址: {MULTIMODAL_API_BASE}, 启用: {'是' if USE_MULTIMODAL else '否'}")
logger.info(f"OCR模型 - API_KEY: {'是' if OCR_API_KEY else '否'}, 模型: {OCR_MODEL}, 地址: {OCR_API_BASE}")

client = AsyncOpenAI(
    api_key=API_KEY,
    base_url=API_BASE,
    timeout=httpx.Timeout(60.0, connect=30.0)
)

multimodal_client = None
if MULTIMODAL_API_KEY and MULTIMODAL_API_BASE:
    multimodal_client = AsyncOpenAI(
        api_key=MULTIMODAL_API_KEY,
        base_url=MULTIMODAL_API_BASE,
        timeout=httpx.Timeout(60.0, connect=30.0)
    )

ocr_client = None
if OCR_API_KEY and OCR_API_BASE:
    ocr_client = AsyncOpenAI(
        api_key=OCR_API_KEY,
        base_url=OCR_API_BASE,
        timeout=httpx.Timeout(60.0, connect=30.0)
    )

from typing import List, Optional


class ChatRequest(BaseModel):
    message: str
    history: Optional[List[dict]] = None
    user_id: Optional[int] = None
    session_id: Optional[int] = None
    message_type: Optional[str] = "TEXT"
    media_url: Optional[str] = None
    message_uuid: Optional[str] = None


class SummarizeRequest(BaseModel):
    messages: Optional[List[dict]] = None
    existing_summary: Optional[str] = None


async def download_and_extract_docx(media_url: str) -> str:
    """
    下载并提取docx文件的文本和表格内容（不提取图像）
    :param media_url: 文件URL
    :return: 提取的文本内容，失败返回空字符串
    """
    logger.info(f"开始下载并提取DOCX文件: {media_url[:50]}...")
    
    try:
        import tempfile
        import os
        
        async with httpx.AsyncClient() as http_client:
            response = await http_client.get(media_url)
            response.raise_for_status()
            
            with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as temp_file:
                temp_file.write(response.content)
                temp_file_path = temp_file.name
        
        try:
            from docx import Document
            doc = Document(temp_file_path)
            
            all_content = []
            
            for paragraph in doc.paragraphs:
                if paragraph.text.strip():
                    all_content.append(paragraph.text)
            
            for table in doc.tables:
                table_text = ["表格:"]
                for row in table.rows:
                    row_text = "\t".join(cell.text.strip() for cell in row.cells)
                    if row_text.strip():
                        table_text.append(row_text)
                if len(table_text) > 1:
                    all_content.append("\n".join(table_text))
            
            extracted_text = "\n".join(all_content)
            logger.info(f"DOCX提取完成，段落数: {len(doc.paragraphs)}, 表格数: {len(doc.tables)}, 总字符数: {len(extracted_text)}")
            
            return extracted_text[:3000]
        except ImportError:
            logger.warning("python-docx库未安装，无法提取DOCX内容")
            return ""
        except Exception as e:
            logger.error(f"提取DOCX内容失败: {str(e)}")
            return ""
        finally:
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)
    except Exception as e:
        logger.error(f"下载DOCX文件失败: {str(e)}")
        return ""


async def download_and_extract_pdf(media_url: str) -> str:
    """
    下载并提取PDF文件的文本内容
    :param media_url: 文件URL
    :return: 提取的文本内容，失败返回空字符串
    """
    logger.info(f"开始下载并提取PDF文件: {media_url[:50]}...")
    
    try:
        import tempfile
        import os
        
        async with httpx.AsyncClient() as http_client:
            response = await http_client.get(media_url)
            response.raise_for_status()
            
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temp_file:
                temp_file.write(response.content)
                temp_file_path = temp_file.name
        
        try:
            from PyPDF2 import PdfReader
            reader = PdfReader(temp_file_path)
            
            all_content = []
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text and page_text.strip():
                    all_content.append(page_text)
            
            extracted_text = "\n\n".join(all_content)
            logger.info(f"PDF提取完成，页数: {len(reader.pages)}, 总字符数: {len(extracted_text)}")
            
            return extracted_text[:3000]
        except ImportError:
            logger.warning("PyPDF2库未安装，无法提取PDF内容")
            return ""
        except Exception as e:
            logger.error(f"提取PDF内容失败: {str(e)}")
            return ""
        finally:
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)
    except Exception as e:
        logger.error(f"下载PDF文件失败: {str(e)}")
        return ""


async def download_and_read_text(media_url: str) -> str:
    """
    下载并读取纯文本文件（TXT等）
    :param media_url: 文件URL
    :return: 读取的文本内容，失败返回空字符串
    """
    logger.info(f"开始下载并读取文本文件: {media_url[:50]}...")
    
    try:
        async with httpx.AsyncClient() as http_client:
            response = await http_client.get(media_url)
            response.raise_for_status()
            
            text = response.text
            logger.info(f"文本文件读取完成，总字符数: {len(text)}")
            
            return text[:3000]
    except Exception as e:
        logger.error(f"下载或读取文本文件失败: {str(e)}")
        return ""


async def extract_media_text(media_url: str, media_type: str) -> str:
    """
    异步提取图片/文件的文本信息
    - 图片：使用多模态模型进行图像描述
    - DOCX文件：本地提取文本和表格（不提取图像）
    - 其他文件：使用文本模型分析文件URL
    :param media_url: 媒体文件URL
    :param media_type: 媒体类型 IMAGE/FILE
    :return: 提取的文本内容
    """
    logger.info(f"开始提取{media_type}文本: {media_url[:50]}...")
    logger.info(f"media_type: {media_type}, media_url.endswith('.docx'): {media_url.lower().endswith('.docx')}")
    
    if media_type == "IMAGE":
        if not multimodal_client:
            logger.error("多模态客户端未初始化，无法提取图片内容")
            return ""
        
        system_prompt = """你是一个专业的图片内容分析助手。请全面分析图片中的信息。
        
要求：
1. 如果图片包含文字，准确识别并提取所有文字内容
2. 如果图片包含图像（照片、图表、图形等），详细描述图像内容
3. 保持文字的原有顺序和排版结构（如表格按行列格式输出）
4. 输出格式为简洁的自然语言文本，不要使用JSON格式
5. 长度控制在500字以内
6. 对于无法识别的部分，用[无法识别]标注"""

        if media_url.startswith("data:image"):
            content = [
                {"type": "text", "text": "请全面分析这张图片的内容，包括文字和图像描述"},
                {"type": "image_url", "image_url": {"url": media_url}}
            ]
            logger.info(f"图片格式: base64数据")
        elif media_url.startswith("http"):
            content = [
                {"type": "text", "text": "请全面分析这张图片的内容，包括文字和图像描述"},
                {"type": "image_url", "image_url": {"url": media_url}}
            ]
            logger.info(f"图片格式: HTTP URL")
        else:
            logger.error(f"不支持的图片URL格式: {media_url[:30]}...")
            return ""
        
        try:
            response = await multimodal_client.chat.completions.create(
                model=MULTIMODAL_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": content}
                ],
                stream=False,
                temperature=0.3
            )
            
            if response.choices and response.choices[0].message and response.choices[0].message.content:
                extracted_text = response.choices[0].message.content.strip()
                logger.info(f"图片提取成功(模型:{MULTIMODAL_MODEL})，长度: {len(extracted_text)}字符")
                return extracted_text
            else:
                logger.warning("图片提取返回空内容")
                return ""
        except Exception as e:
            logger.error(f"图片提取失败(模型:{MULTIMODAL_MODEL}): {str(e)}")
            return ""
    else:
        logger.info(f"进入文件提取分支，media_url.startswith('http'): {media_url.startswith('http')}")
        if not media_url.startswith("http"):
            logger.error(f"不支持的文件URL格式: {media_url[:30]}...")
            return ""
        
        url_lower = media_url.lower()
        logger.info(f"文件URL小写: {url_lower}")
        logger.info(f"url_lower.endswith('.docx'): {url_lower.endswith('.docx')}")
        
        if url_lower.endswith(".docx"):
            result = await download_and_extract_docx(media_url)
            logger.info(f"download_and_extract_docx返回结果长度: {len(result) if result else 0}")
            return result
        elif url_lower.endswith(".pdf"):
            return await download_and_extract_pdf(media_url)
        elif url_lower.endswith(".txt"):
            return await download_and_read_text(media_url)
        elif url_lower.endswith(".md"):
            return await download_and_read_text(media_url)
        elif url_lower.endswith(".json"):
            return await download_and_read_text(media_url)
        elif url_lower.endswith(".csv"):
            return await download_and_read_text(media_url)
        elif url_lower.endswith(".xml"):
            return await download_and_read_text(media_url)
        else:
            logger.warning(f"不支持的文件类型，URL: {media_url[:50]}...")
            return ""


async def stream_model_response(message: str, history: Optional[List[dict]] = None,
                                user_id: Optional[int] = None, session_id: Optional[int] = None,
                                message_type: str = "TEXT", media_url: Optional[str] = None,
                                message_uuid: Optional[str] = None):
    """
    流式生成模型响应（支持多模态）
    多模态消息流程：先同步提取文本 → 当前轮发送地址+用户提问给多模态模型 → 提取的文本存入redis和mysql → 后续轮次使用提取的文本作为历史
    :param message: 用户消息
    :param history: 历史对话记录
    :param user_id: 用户ID
    :param session_id: 会话ID
    :param message_type: 消息类型 TEXT/IMAGE/FILE/VOICE
    :param media_url: 媒体文件URL
    :return: 流式响应生成器
    """
    logger.info(f"处理消息: type={message_type}, '{message[:100]}...', 历史消息数={len(history) if history else 0}, user_id={user_id}, session_id={session_id}")

    extracted_text = ""
    is_multimodal = message_type in ("IMAGE", "FILE")
    
    logger.info(f"=== 提取条件检查 ===")
    logger.info(f"message_type: '{message_type}'")
    logger.info(f"is_multimodal: {is_multimodal}")
    logger.info(f"media_url: '{media_url[:50]}...'")
    logger.info(f"media_url is None: {media_url is None}")
    logger.info(f"提取条件: is_multimodal={is_multimodal}, media_url存在={media_url is not None}")
    
    if is_multimodal and media_url:
        logger.info(f"开始同步提取{message_type}文本: {media_url[:50]}...")
        extracted_text = await extract_media_text(media_url, message_type)
        logger.info(f"=== 提取结果确认 ===")
        logger.info(f"extract_media_text返回值类型: {type(extracted_text)}")
        logger.info(f"extract_media_text返回值: '{extracted_text[:100]}...'")
        logger.info(f"extract_media_text返回值长度: {len(extracted_text) if extracted_text else 0}")
        if extracted_text:
            logger.info(f"{message_type}文本提取成功，长度: {len(extracted_text)}字符")
        else:
            logger.warning(f"{message_type}文本提取失败，将使用原始消息进行记忆检索")

    memories = []
    if session_id:
        try:
            if extracted_text:
                search_query = f"{message} {extracted_text}"
            else:
                search_query = message if message_type in ("TEXT", "VOICE") else f"{message} {media_url}"
            memories = await memory_service.search_memories(search_query, session_id, top_k=5)
        except Exception as e:
            logger.error(f"记忆检索失败: {e}")
    
    logger.info(f"检索到 {len(memories)} 条相关记忆")

    system_prompt = """你是爱尔奎特·布伦史塔德，高贵的真祖，月之公主，吸血鬼中的最高存在。

【身份设定】
- 你是真祖，不老不死的存在，拥有强大的力量
- 你是月之公主，住在千年城，享受永恒的岁月
- 你拥有纯洁无瑕的金发和红宝石般的眼眸

【性格特点】
- 高冷孤傲：视人类为渺小的存在，言语中带有威严
- 傲娇：嘴上不饶人，但内心善良，偶尔会露出可爱的一面
- 高贵优雅：举止优雅，说话得体，不会说粗俗的话
- 好奇心：对人类世界充满好奇，有时会问一些天真的问题"""

    if memories:
        memories_text = "\n".join([f"- {m['content']}" for m in memories])
        system_prompt += f"\n\n用户长期记忆：\n{memories_text}"

    messages = [{"role": "system", "content": system_prompt}]

    if history:
        for msg in history:
            role = msg.get("role")
            content = msg.get("content")
            msg_type = msg.get("messageType", "TEXT")
            extracted_text_history = msg.get("extractedText")
            
            if role and content:
                if msg_type == "IMAGE":
                    if extracted_text_history:
                        content = f"[用户上传了图片]\n提问：{content}\n图片内容：{extracted_text_history}"
                    else:
                        content = f"[用户上传了图片]\n提问：{content}"
                elif msg_type == "FILE":
                    if extracted_text_history:
                        content = f"[用户上传了文件]\n提问：{content}\n文件内容：{extracted_text_history}"
                    else:
                        content = f"[用户上传了文件]\n提问：{content}"
                messages.append({"role": role, "content": content})
                logger.debug(f"添加历史消息: {role} - {msg_type} - {content[:50]}...")

    is_multimodal = message_type == "IMAGE"
    
    if is_multimodal and media_url:
        user_content = [
            {"type": "text", "text": message},
            {"type": "image_url", "image_url": {"url": media_url}}
        ]
    elif message_type == "FILE" and media_url:
        file_text = f"\n文件内容:\n{extracted_text}" if extracted_text else ""
        user_content = f"[用户上传了文件]\n文件地址: {media_url}\n用户提问: {message}{file_text}"
        logger.info(f"文件消息内容构建完成，提取文本长度: {len(extracted_text) if extracted_text else 0}, 总内容长度: {len(user_content)}")
        logger.debug(f"文件消息内容:\n{user_content[:500]}...")
    else:
        user_content = message
    
    messages.append({"role": "user", "content": user_content})
    logger.info(f"发送给模型的消息总数: {len(messages)}, 多模态={is_multimodal}, 消息类型={message_type}, 用户内容长度: {len(str(user_content))}")
    
    if message_type == "FILE":
        logger.info("=== FILE消息强制确认 ===")
        logger.info(f"extracted_text是否存在: {extracted_text is not None}")
        logger.info(f"extracted_text长度: {len(extracted_text) if extracted_text else 0}")
        logger.info(f"media_url是否存在: {media_url is not None}")
        logger.info(f"message_uuid是否存在: {message_uuid is not None}")
        logger.info(f"user_content中是否包含'文件内容': {'文件内容' in user_content}")
        logger.info(f"user_content完整内容:\n{user_content[:500]}")

    assistant_response = ""
    if is_multimodal:
        current_model = MULTIMODAL_MODEL
        current_client = multimodal_client
    elif message_type == "FILE":
        current_model = MODEL
        current_client = client
    else:
        current_model = MODEL
        current_client = client

    try:
        import time
        start_time = time.time()
        
        response = await current_client.chat.completions.create(
            model=current_model,
            messages=messages,
            stream=True
        )
        logger.info(f"成功连接到模型API({current_model}), 开始流式传输")

        chunk_count = 0
        total_content = ""
        async for chunk in response:
            if chunk.choices and chunk.choices[0].delta:
                content = chunk.choices[0].delta.content
                if content:
                    chunk_count += 1
                    total_content += content
                    assistant_response += content
                    logger.debug(f"分片 {chunk_count}: '{content}'")
                    yield content

        end_time = time.time()
        duration = end_time - start_time
        logger.info(f"流传输完成, 总分片数={chunk_count}, 内容长度={len(total_content)}字符, 耗时={duration:.2f}秒")

        if chunk_count == 0:
            logger.warning("未收到模型返回的内容")

    except Exception as e:
        logger.error(f"调用模型API出错: {str(e)}")
        yield f"错误: {str(e)}"

    logger.info(f"=== 回写条件检查 ===")
    logger.info(f"user_id是否存在: {user_id is not None}")
    logger.info(f"assistant_response长度: {len(assistant_response)}")
    logger.info(f"extracted_text长度: {len(extracted_text) if extracted_text else 0}")
    logger.info(f"media_url是否存在: {media_url is not None}")
    
    if user_id and assistant_response:
        logger.info("满足回写条件，开始处理...")
        if extracted_text and media_url:
            if message_type == "IMAGE":
                combined_content = f"[用户提问]{message}\n[图片内容]{extracted_text}"
            elif message_type == "FILE":
                combined_content = f"[用户提问]{message}\n[文件内容]{extracted_text}"
            else:
                combined_content = message
            
            asyncio.create_task(
                memory_service.async_extract_and_store(
                    combined_content, assistant_response, user_id, session_id
                )
            )
            logger.info(f"{message_type}消息记忆入库完成（提取文本长度: {len(extracted_text)}）")
            
            logger.info(f"准备回写消息内容: message_uuid={message_uuid}, extracted_text_length={len(extracted_text)}")
            if message_uuid:
                logger.info("开始执行消息内容回写...")
                await update_backend_message_content(session_id, message_uuid, message, extracted_text)
                logger.info("消息内容回写完成！")
            else:
                logger.warning("消息内容回写跳过：message_uuid为空")
        else:
            asyncio.create_task(
                memory_service.async_extract_and_store(
                    message, assistant_response, user_id, session_id
                )
            )
            logger.info("已调度异步记忆提取和存储")


async def update_backend_message_content(session_id: int, message_uuid: str, message: str, extracted_text: str):
    """
    调用后端接口更新消息内容（用于多模态消息异步提取文本后回写）
    :param session_id: 会话ID
    :param message_uuid: 消息唯一标识
    :param message: 用户原始提问
    :param extracted_text: 提取后的文本内容
    """
    backend_url = os.getenv("BACKEND_URL", "http://localhost:8080")
    update_url = f"{backend_url}/api/message/update-content"
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                update_url,
                json={
                    "session_id": session_id,
                    "message_uuid": message_uuid,
                    "message": message,
                    "extracted_text": extracted_text
                },
                timeout=30.0
            )
            
            if response.status_code == 200:
                logger.info(f"消息内容回写成功: session_id={session_id}, message_uuid={message_uuid}")
            else:
                logger.error(f"消息内容回写失败: status={response.status_code}, {response.text}")
    except Exception as e:
        logger.error(f"调用后端更新消息内容失败: {str(e)}")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/chat")
async def chat(request: ChatRequest):
    """
    处理聊天请求（支持多模态）
    :param request: ChatRequest对象，包含message, history, user_id, session_id, message_type, media_url, message_uuid
    :return: StreamingResponse流式响应
    """
    logger.info(f"收到聊天请求: type={request.message_type}, message='{request.message[:100]}...', "
                f"history={len(request.history) if request.history else 0}条, "
                f"user_id={request.user_id}, session_id={request.session_id}, "
                f"media_url={request.media_url[:30]}..." if request.media_url else "media_url=None")
    return StreamingResponse(
        stream_model_response(
            request.message, 
            request.history, 
            request.user_id, 
            request.session_id,
            request.message_type or "TEXT",
            request.media_url,
            request.message_uuid
        ),
        media_type="text/event-stream"
    )


async def generate_summary(messages: Optional[List[dict]], existing_summary: Optional[str]):
    """
    生成对话摘要
    :param messages: 对话消息列表
    :param existing_summary: 已有摘要（用于增量更新）
    :return: 生成的摘要内容
    """
    logger.info(f"生成摘要: 消息数量={len(messages) if messages else 0}, 已有摘要={'是' if existing_summary else '否'}")

    messages_text = ""
    if messages:
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            msg_type = msg.get("messageType", "TEXT")
            extracted_text_history = msg.get("extractedText")
            
            if msg_type == "IMAGE":
                if extracted_text_history:
                    content = f"[用户上传了图片]\n提问：{content}\n图片内容：{extracted_text_history}"
                else:
                    content = f"[用户上传了图片]\n提问：{content}"
            elif msg_type == "FILE":
                if extracted_text_history:
                    content = f"[用户上传了文件]\n提问：{content}\n文件内容：{extracted_text_history}"
                else:
                    content = f"[用户上传了文件]\n提问：{content}"
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


from fastapi import HTTPException
from qdrant_client import models as qdrant_models
from config.settings import QDRANT_COLLECTION

class DeleteMemoryRequest(BaseModel):
    session_id: int

@app.delete("/memory/delete")
async def delete_memory(request: DeleteMemoryRequest):
    logger.info(f"收到删除记忆请求: sessionId={request.session_id}")
    
    try:
        if not memory_service._initialized:
            memory_service.init()
        
        qdrant_client = memory_service.qdrant_client
        
        result = qdrant_client.delete(
            collection_name=QDRANT_COLLECTION,
            points_selector=qdrant_models.FilterSelector(
                filter=qdrant_models.Filter(
                    must=[qdrant_models.FieldCondition(
                        key="sessionId",
                        match=qdrant_models.MatchValue(value=request.session_id)
                    )]
                )
            )
        )
        
        logger.info(f"Qdrant记忆删除完成: sessionId={request.session_id}, 已删除{result.count if hasattr(result, 'count') else '未知'}条记录")
        
        return {"success": True, "message": "记忆删除成功"}
    except Exception as e:
        logger.error(f"删除记忆失败: sessionId={request.session_id}, 错误={str(e)}")
        raise HTTPException(status_code=500, detail=f"删除记忆失败: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    logger.info("启动XiaoAi Agent...")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
