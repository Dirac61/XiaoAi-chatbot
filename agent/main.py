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
import time
from typing import List, Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logging.getLogger("XiaoAi Memory Service").setLevel(logging.DEBUG)
logger = logging.getLogger("XiaoAi Agent")

load_dotenv()

from services.memory_service import memory_service
from services.search_service import search_service


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

ORCHESTRATION_MODEL = os.getenv("ORCHESTRATION_MODEL") or MODEL
ORCHESTRATION_API_KEY = os.getenv("ORCHESTRATION_API_KEY") or API_KEY
ORCHESTRATION_API_BASE = os.getenv("ORCHESTRATION_API_BASE") or API_BASE

logger.info(f"文本模型 - API_KEY: {'是' if API_KEY else '否'}, 模型: {MODEL}, 地址: {API_BASE}")
logger.info(f"多模态模型 - API_KEY: {'是' if MULTIMODAL_API_KEY else '否'}, 模型: {MULTIMODAL_MODEL}, 地址: {MULTIMODAL_API_BASE}, 启用: {'是' if USE_MULTIMODAL else '否'}")
logger.info(f"OCR模型 - API_KEY: {'是' if OCR_API_KEY else '否'}, 模型: {OCR_MODEL}, 地址: {OCR_API_BASE}")
logger.info(f"编排器模型 - API_KEY: {'是' if ORCHESTRATION_API_KEY else '否'}, 模型: {ORCHESTRATION_MODEL}, 地址: {ORCHESTRATION_API_BASE}")

# === 专家模式配置 ===
EXPERT_MODE_ENABLED = os.getenv("EXPERT_MODE_ENABLED", "false").lower() == "true"
EXPERT_MAX_ITERATIONS = int(os.getenv("EXPERT_MAX_ITERATIONS", "3"))

EXPERT_ORCHESTRATION_MODEL = os.getenv("EXPERT_ORCHESTRATION_MODEL", "")
EXPERT_ORCHESTRATION_API_KEY = os.getenv("EXPERT_ORCHESTRATION_API_KEY", "")
EXPERT_ORCHESTRATION_API_BASE = os.getenv("EXPERT_ORCHESTRATION_API_BASE", "")

EXPERT_DEEP_THINKING_MODEL = os.getenv("EXPERT_DEEP_THINKING_MODEL", "")
EXPERT_DEEP_THINKING_API_KEY = os.getenv("EXPERT_DEEP_THINKING_API_KEY", "")
EXPERT_DEEP_THINKING_API_BASE = os.getenv("EXPERT_DEEP_THINKING_API_BASE", "")

logger.info(f"专家模式 - 启用: {'是' if EXPERT_MODE_ENABLED else '否'}")
logger.info(f"专家模式编排器 - API_KEY: {'是' if EXPERT_ORCHESTRATION_API_KEY else '否'}, 模型: {EXPERT_ORCHESTRATION_MODEL}, 地址: {EXPERT_ORCHESTRATION_API_BASE}")
logger.info(f"深度思考模型 - API_KEY: {'是' if EXPERT_DEEP_THINKING_API_KEY else '否'}, 模型: {EXPERT_DEEP_THINKING_MODEL}, 地址: {EXPERT_DEEP_THINKING_API_BASE}")
logger.info(f"专家模式最大迭代次数: {EXPERT_MAX_ITERATIONS}")
logger.info(f"专家模式 - 编排器直接生成回复，不使用主模型")

# 主聊天模型 client
# timeout: 读取超时 30s（覆盖大模型首 token 响应），connect 5s（正常握手 1~2s 足够）
# max_retries=0: 禁用 AsyncOpenAI 内置重试，避免单次超时被放大为 3 倍时长，失败由业务层处理
client = AsyncOpenAI(
    api_key=API_KEY,
    base_url=API_BASE,
    timeout=httpx.Timeout(30.0, connect=5.0),
    max_retries=0
)

# 多模态模型 client（配置策略同主 client）
multimodal_client = None
if MULTIMODAL_API_KEY and MULTIMODAL_API_BASE:
    multimodal_client = AsyncOpenAI(
        api_key=MULTIMODAL_API_KEY,
        base_url=MULTIMODAL_API_BASE,
        timeout=httpx.Timeout(30.0, connect=5.0),
        max_retries=0
    )

# OCR 模型 client（配置策略同主 client）
ocr_client = None
if OCR_API_KEY and OCR_API_BASE:
    ocr_client = AsyncOpenAI(
        api_key=OCR_API_KEY,
        base_url=OCR_API_BASE,
        timeout=httpx.Timeout(30.0, connect=5.0),
        max_retries=0
    )

# 编排器小模型 client
# timeout: 读取 15s（编排器只输出 JSON，响应应较快），connect 5s
# max_retries=0: 禁用重试，失败时直接走 fallback（need_search=False），不拖累主流程
orchestration_client = None
if ORCHESTRATION_API_KEY and ORCHESTRATION_API_BASE:
    orchestration_client = AsyncOpenAI(
        api_key=ORCHESTRATION_API_KEY,
        base_url=ORCHESTRATION_API_BASE,
        timeout=httpx.Timeout(15.0, connect=5.0),
        max_retries=0
    )

# === 专家模式专用 client ===
# 专家模式编排器 client（多模态模型，支持图片理解）
expert_orchestration_client = None
if EXPERT_ORCHESTRATION_API_KEY and EXPERT_ORCHESTRATION_API_BASE:
    expert_orchestration_client = AsyncOpenAI(
        api_key=EXPERT_ORCHESTRATION_API_KEY,
        base_url=EXPERT_ORCHESTRATION_API_BASE,
        timeout=httpx.Timeout(30.0, connect=5.0),
        max_retries=0
    )

# 深度思考模型 client（多模态模型，接收图片URL进行分析）
deep_thinking_client = None
if EXPERT_DEEP_THINKING_API_KEY and EXPERT_DEEP_THINKING_API_BASE:
    deep_thinking_client = AsyncOpenAI(
        api_key=EXPERT_DEEP_THINKING_API_KEY,
        base_url=EXPERT_DEEP_THINKING_API_BASE,
        timeout=httpx.Timeout(60.0, connect=5.0),
        max_retries=0
    )

# 专家模式主模型 client - 已移除，由编排器直接生成回复


class ChatRequest(BaseModel):
    message: str
    history: Optional[List[dict]] = None
    user_id: Optional[int] = None
    session_id: Optional[str] = None
    message_type: Optional[str] = "TEXT"
    media_url: Optional[str] = None
    media_urls: Optional[List[str]] = None
    message_uuid: Optional[str] = None
    mode: Optional[str] = "fast"  # fast: 快速模式, expert: 专家模式


class SummarizeRequest(BaseModel):
    messages: Optional[List[dict]] = None
    existing_summary: Optional[str] = None


async def download_and_extract_docx(media_url: str) -> str:
    logger.info(f"[文件提取] 开始下载并提取DOCX文件: {media_url[:50]}...")
    
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
            logger.info(f"[文件提取] DOCX提取完成，段落数: {len(doc.paragraphs)}, 表格数: {len(doc.tables)}, 总字符数: {len(extracted_text)}")
            
            return extracted_text[:3000]
        except ImportError:
            logger.warning("[文件提取] python-docx库未安装，无法提取DOCX内容")
            return ""
        except Exception as e:
            logger.error(f"[文件提取] 提取DOCX内容失败: {str(e)}")
            return ""
        finally:
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)
    except Exception as e:
        logger.error(f"[文件提取] 下载DOCX文件失败: {str(e)}")
        return ""


async def download_and_extract_pdf(media_url: str) -> str:
    logger.info(f"[文件提取] 开始下载并提取PDF文件: {media_url[:50]}...")
    
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
            logger.info(f"[文件提取] PDF提取完成，页数: {len(reader.pages)}, 总字符数: {len(extracted_text)}")
            
            return extracted_text[:3000]
        except ImportError:
            logger.warning("[文件提取] PyPDF2库未安装，无法提取PDF内容")
            return ""
        except Exception as e:
            logger.error(f"[文件提取] 提取PDF内容失败: {str(e)}")
            return ""
        finally:
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)
    except Exception as e:
        logger.error(f"[文件提取] 下载PDF文件失败: {str(e)}")
        return ""


async def download_and_read_text(media_url: str) -> str:
    logger.info(f"[文件提取] 开始下载并读取文本文件: {media_url[:50]}...")
    
    try:
        async with httpx.AsyncClient() as http_client:
            response = await http_client.get(media_url)
            response.raise_for_status()
            
            text = response.text
            logger.info(f"[文件提取] 文本文件读取完成，总字符数: {len(text)}")
            
            return text[:3000]
    except Exception as e:
        logger.error(f"[文件提取] 下载或读取文本文件失败: {str(e)}")
        return ""


async def extract_media_text(media_url: str, media_type: str) -> str:
    start_time = time.time()
    
    if media_type == "IMAGE":
        if ocr_client:
            client = ocr_client
            model = OCR_MODEL
            logger.info(f"[图片提取] 使用OCR模型: {OCR_MODEL}")
        elif multimodal_client:
            client = multimodal_client
            model = MULTIMODAL_MODEL
            logger.info(f"[图片提取] 使用多模态模型: {MULTIMODAL_MODEL}")
        else:
            logger.error("[图片提取] OCR和多模态客户端均未初始化，无法提取图片内容")
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
        elif media_url.startswith("http"):
            content = [
                {"type": "text", "text": "请全面分析这张图片的内容，包括文字和图像描述"},
                {"type": "image_url", "image_url": {"url": media_url}}
            ]
        else:
            logger.error(f"[图片提取] 不支持的图片URL格式: {media_url[:30]}...")
            return ""
        
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": content}
                ],
                stream=False,
                temperature=0.3
            )
            
            duration = time.time() - start_time
            
            if response.usage:
                logger.info(f"[图片提取] Token消耗(模型:{model}): prompt={response.usage.prompt_tokens}, completion={response.usage.completion_tokens}, total={response.usage.total_tokens}, 耗时={duration:.2f}秒")
            
            if response.choices and response.choices[0].message and response.choices[0].message.content:
                extracted_text = response.choices[0].message.content.strip()
                logger.info(f"[图片提取] 成功(模型:{model})，长度: {len(extracted_text)}字符，耗时={duration:.2f}秒")
                return extracted_text
            else:
                logger.warning(f"[图片提取] 返回空内容，耗时={duration:.2f}秒")
                return ""
        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"[图片提取] 失败(模型:{model}): {str(e)}，耗时={duration:.2f}秒")
            return ""
    else:
        if not media_url.startswith("http"):
            logger.error(f"[文件提取] 不支持的文件URL格式: {media_url[:30]}...")
            return ""
        
        url_lower = media_url.lower()
        
        if url_lower.endswith(".docx"):
            return await download_and_extract_docx(media_url)
        elif url_lower.endswith(".pdf"):
            return await download_and_extract_pdf(media_url)
        elif url_lower.endswith(".txt") or url_lower.endswith(".md") or url_lower.endswith(".json") or url_lower.endswith(".csv") or url_lower.endswith(".xml"):
            return await download_and_read_text(media_url)
        else:
            logger.warning(f"[文件提取] 不支持的文件类型: {media_url[:50]}...")
            return ""


async def extract_media_text_batch(media_urls: List[str], media_type: str) -> str:
    """批量提取媒体文本 - 使用并行处理提高速度"""
    start_time = time.time()
    logger.info(f"[批量提取] 开始提取{media_type}文本: 数量={len(media_urls)}")
    
    if media_type == "IMAGE" and len(media_urls) > 1:
        # 图片类型：尝试一次调用处理多张图片（支持多图输入的模型）
        extracted_text = await extract_multiple_images(media_urls)
        if extracted_text:
            duration = time.time() - start_time
            logger.info(f"[批量提取] 批量处理完成，总字符数: {len(extracted_text)}, 耗时={duration:.2f}秒")
            return extracted_text
        else:
            # 批量处理失败，回退到并行处理
            logger.info(f"[批量提取] 批量处理失败，回退到并行处理")
    
    # 并行处理多个媒体文件
    tasks = []
    for i, url in enumerate(media_urls):
        logger.info(f"[批量提取] 启动任务{i+1}/{len(media_urls)}: {url[:50]}...")
        tasks.append(extract_media_text(url, media_type))
    
    # 使用asyncio.gather并发执行
    results = await asyncio.gather(*tasks)
    
    all_extracted = []
    for i, text in enumerate(results):
        if text:
            all_extracted.append(f"图{i+1}：{text}")
        else:
            all_extracted.append(f"图{i+1}：[提取失败]")
    
    duration = time.time() - start_time
    result = "\n\n".join(all_extracted)
    logger.info(f"[批量提取] 并行处理完成，总字符数: {len(result)}, 耗时={duration:.2f}秒")
    
    return result


async def extract_multiple_images(media_urls: List[str]) -> str:
    """一次调用处理多张图片 - 支持多图输入的模型"""
    start_time = time.time()
    logger.info(f"[多图提取] 一次调用处理{len(media_urls)}张图片")
    
    if ocr_client:
        client = ocr_client
        model = OCR_MODEL
        logger.info(f"[多图提取] 使用OCR模型: {OCR_MODEL}")
    elif multimodal_client:
        client = multimodal_client
        model = MULTIMODAL_MODEL
        logger.info(f"[多图提取] 使用多模态模型: {MULTIMODAL_MODEL}")
    else:
        logger.error("[多图提取] OCR和多模态客户端均未初始化")
        return ""
    
    system_prompt = """你是一个专业的图片内容分析助手。请按图片顺序编号分析所有图片。

输出格式要求：
- 每张图片的分析必须以"图N："开头（N为图片序号，从1开始）
- 图1：描述第一张图片的内容
- 图2：描述第二张图片的内容
- 以此类推

分析要求：
1. 如果图片包含文字，准确识别并提取所有文字内容
2. 如果图片包含图像（照片、图表、图形等），详细描述图像内容
3. 保持文字的原有顺序和排版结构
4. 对于无法识别的部分，用[无法识别]标注
5. 长度控制在1500字以内"""
    
    # 构建多图内容
    content = [{"type": "text", "text": "请全面分析以下所有图片的内容，包括文字和图像描述"}]
    for i, url in enumerate(media_urls):
        content.append({"type": "image_url", "image_url": {"url": url, "index": i + 1}})
    
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content}
            ],
            stream=False,
            temperature=0.3
        )
        
        duration = time.time() - start_time
        
        if response.usage:
            logger.info(f"[多图提取] Token消耗(模型:{model}): prompt={response.usage.prompt_tokens}, completion={response.usage.completion_tokens}, total={response.usage.total_tokens}, 耗时={duration:.2f}秒")
        
        if response.choices and response.choices[0].message and response.choices[0].message.content:
            extracted_text = response.choices[0].message.content.strip()
            logger.info(f"[多图提取] 成功(模型:{model})，长度: {len(extracted_text)}字符，耗时={duration:.2f}秒")
            return extracted_text
        else:
            logger.warning(f"[多图提取] 返回空内容，耗时={duration:.2f}秒")
            return ""
    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"[多图提取] 失败(模型:{model}): {str(e)}，耗时={duration:.2f}秒")
        return ""


async def stream_model_response(message: str, history: Optional[List[dict]] = None,
                                user_id: Optional[int] = None, session_id: Optional[int] = None,
                                message_type: str = "TEXT", media_url: Optional[str] = None,
                                media_urls: Optional[List[str]] = None,
                                message_uuid: Optional[str] = None,
                                mode: str = "fast"):
    request_start_time = time.time()
    logger.info(f"{'='*60}")
    logger.info(f"[请求开始] 会话ID: {session_id}, 用户ID: {user_id}, 消息类型: {message_type}")
    logger.info(f"[请求开始] 用户消息: '{message[:100]}...'")
    logger.info(f"[请求开始] 历史消息数: {len(history) if history else 0}")
    logger.info(f"[请求开始] 模式: {mode}")
    logger.info(f"{'='*60}")
    
    # 根据模式选择处理函数
    if mode == "expert":
        async for result in expert_mode_process(message, history, user_id, session_id, 
                                                message_type, media_url, media_urls, 
                                                message_uuid, request_start_time):
            yield result
        return

    extracted_text = ""
    is_multimodal = message_type in ("IMAGE", "FILE")
    
    if is_multimodal and (media_url or (media_urls and len(media_urls) > 0)):
        if media_urls and len(media_urls) > 0:
            extracted_text = await extract_media_text_batch(media_urls, message_type)
        else:
            extracted_text = await extract_media_text(media_url, message_type)
        
        if extracted_text:
            logger.info(f"[媒体提取] 成功，长度: {len(extracted_text)}字符")
        else:
            logger.warning(f"[媒体提取] 失败，将使用原始消息进行记忆检索")

    memories = []
    if session_id:
        mem_start = time.time()
        try:
            search_query = f"{message} {extracted_text}" if extracted_text else (message if message_type in ("TEXT", "VOICE") else (f"{message} {media_url}" if media_url else message))
            memories = await memory_service.search_memories(search_query, session_id, top_k=5)
            logger.info(f"[记忆检索] 完成，找到{len(memories)}条相关记忆，耗时={time.time()-mem_start:.2f}秒")
        except Exception as e:
            logger.error(f"[记忆检索] 失败: {e}")

    search_results = []
    search_context = ""
    
    context_text = message
    if extracted_text:
        context_text += f"\n{extracted_text}"
    if memories:
        memories_text = "\n".join([f"- {m['content']}" for m in memories])
        context_text += f"\n\n相关记忆：\n{memories_text}"

    orch_start = time.time()
    orchestration_result = await _call_orchestration_model(context_text, message)
    logger.info(f"[编排器] 调用完成，耗时={time.time()-orch_start:.2f}秒")
    
    if orchestration_result:
        need_search = orchestration_result.get("need_search", False)
        search_keywords = orchestration_result.get("search_keywords", [])
        
        logger.info(f"[编排器结果] need_search={need_search}, keywords={search_keywords}")
        
        if need_search and search_keywords:
            search_start = time.time()
            search_results = await search_service.web_search(search_keywords)
            search_context = await search_service.get_search_context(search_keywords)
            logger.info(f"[联网搜索] 完成，找到{len(search_results)}条结果，耗时={time.time()-search_start:.2f}秒")

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

    if search_context:
        system_prompt += f"\n\n联网搜索信息：\n{search_context}"

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

    is_multimodal = message_type == "IMAGE"
    
    if is_multimodal and (media_urls and len(media_urls) > 0):
        user_content = [{"type": "text", "text": message}]
        for url in media_urls:
            user_content.append({"type": "image_url", "image_url": {"url": url}})
    elif is_multimodal and media_url:
        user_content = [
            {"type": "text", "text": message},
            {"type": "image_url", "image_url": {"url": media_url}}
        ]
    elif message_type == "FILE" and (media_url or (media_urls and len(media_urls) > 0)):
        file_text = f"\n文件内容:\n{extracted_text}" if extracted_text else ""
        if media_urls and len(media_urls) > 0:
            user_content = f"[用户上传了{len(media_urls)}个文件]\n用户提问: {message}{file_text}"
        else:
            user_content = f"[用户上传了文件]\n文件地址: {media_url}\n用户提问: {message}{file_text}"
    else:
        user_content = message
    
    messages.append({"role": "user", "content": user_content})
    logger.info(f"[消息构建] 发送给模型的消息数: {len(messages)}, 用户内容长度: {len(str(user_content))}")

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
        model_start = time.time()
        
        response = await current_client.chat.completions.create(
            model=current_model,
            messages=messages,
            stream=True
        )
        logger.info(f"[模型调用] 成功连接到模型API({current_model}), 开始流式传输")

        chunk_count = 0
        total_content = ""
        async for chunk in response:
            if chunk.choices and chunk.choices[0].delta:
                content = chunk.choices[0].delta.content
                if content:
                    chunk_count += 1
                    total_content += content
                    assistant_response += content
                    logger.debug(f"[流式传输] 分片 {chunk_count}: '{content}'")
                    yield json.dumps({"type": "content", "data": content}, ensure_ascii=False) + "\n"

        model_duration = time.time() - model_start
        
        if hasattr(response, 'usage') and response.usage:
            logger.info(f"[模型调用] Token消耗(模型:{current_model}): prompt={response.usage.prompt_tokens}, completion={response.usage.completion_tokens}, total={response.usage.total_tokens}, 耗时={model_duration:.2f}秒")
        
        logger.info(f"[流式传输] 完成, 总分片数={chunk_count}, 内容长度={len(total_content)}字符, 耗时={model_duration:.2f}秒")

        if chunk_count == 0:
            logger.warning("[流式传输] 未收到模型返回的内容")

        if search_results:
            # 过滤搜索结果，只保留标题和URL，不保存搜索摘要（content）
            filtered_results = []
            for result in search_results:
                filtered_results.append({
                    "title": result.get("title", ""),
                    "url": result.get("url", "")
                })
            yield json.dumps({"type": "search_results", "data": filtered_results}, ensure_ascii=False) + "\n"
            logger.info(f"[搜索结果] 已通过流式响应返回: {len(filtered_results)}条")

    except Exception as e:
        logger.error(f"[模型调用] 出错: {str(e)}")
        yield f"错误: {str(e)}"

    if user_id and assistant_response:
        if extracted_text and media_url:
            combined_content = f"[用户提问]{message}\n[图片内容]{extracted_text}" if message_type == "IMAGE" else f"[用户提问]{message}\n[文件内容]{extracted_text}"
            
            asyncio.create_task(
                memory_service.async_extract_and_store(
                    combined_content, assistant_response, user_id, session_id
                )
            )
            
            if message_uuid:
                await update_backend_message_content(session_id, message_uuid, message, extracted_text)
        else:
            asyncio.create_task(
                memory_service.async_extract_and_store(
                    message, assistant_response, user_id, session_id
                )
            )

    total_duration = time.time() - request_start_time
    logger.info(f"{'='*60}")
    logger.info(f"[请求结束] 总耗时={total_duration:.2f}秒")
    logger.info(f"[请求结束] 助手响应长度: {len(assistant_response)}字符")
    logger.info(f"[请求结束] 搜索结果数: {len(search_results)}")
    logger.info(f"[请求结束] 记忆条数: {len(memories)}")
    logger.info(f"{'='*60}")


async def _call_orchestration_model(context_text: str, message: str) -> dict:
    if not orchestration_client:
        logger.warning("[编排器] client未初始化，跳过编排")
        return {"need_search": False, "search_keywords": [], "analysis_text": "编排器未初始化"}
    
    start_time = time.time()
    
    system_prompt = """你是一个智能编排器，负责分析用户问题和上下文，决定是否需要联网搜索。

【核心职责】
判断用户问题是否需要通过联网搜索获取最新信息，以提升回答的准确性和时效性。

【输出格式】
必须输出严格的JSON格式，不要包含任何markdown代码块标记，不要包含解释文字。
格式示例：{"need_search": true, "search_keywords": ["关键词1", "关键词2"], "analysis_text": "分析原因"}

字段说明：
- need_search: 布尔值，true表示需要搜索，false表示不需要搜索
- search_keywords: 字符串数组，搜索关键词列表（1-5个，简洁准确）
- analysis_text: 对判断的简要分析（用于调试，50字以内）

【必须搜索的场景（need_search = true）】
1. 当前时间相关：今天天气、今天新闻、最近事件、最新数据
2. 时效性强：股价、赛事结果、体育比分、实时状态
3. 最新信息：新发布、新版本、最新进展、今日资讯
4. 特定日期：2026年7月、本周、本月、近期
5. 地点相关：xxx天气、xxx新闻、xxx现状
6. 不确定的事实：是否、有没有、是否存在、最新消息

【不需要搜索的场景（need_search = false）】
1. 常识性问题：地球是圆的、1+1=2、太阳从东方升起
2. 纯聊天对话：你好、早上好、谢谢、闲聊
3. 情感交流：安慰、鼓励、建议
4. 已有记忆足够回答：用户之前提到过的信息
5. 历史事实：已经发生过的、有定论的历史事件
6. 数学计算：简单的加减乘除、逻辑推理

【关键词提取规则】
1. 关键词要简洁，每个词2-8个字
2. 优先使用中文关键词
3. 避免使用过于宽泛的词（如"新闻"、"信息"）
4. 包含核心实体（人物、地点、事件、时间）

【示例】
用户提问："今天北京天气怎么样？"
输出：{"need_search": true, "search_keywords": ["2026年7月23日北京天气预报"], "analysis_text": "查询当前天气需要最新数据"}

用户提问："你是谁？"
输出：{"need_search": false, "search_keywords": [], "analysis_text": "自我介绍不需要搜索"}

用户提问："Python和Java哪个好？"
输出：{"need_search": false, "search_keywords": [], "analysis_text": "技术选型建议不需要最新数据"}

用户提问："2026年奥运会在哪里举办？"
输出：{"need_search": true, "search_keywords": ["2026年奥运会举办地点"], "analysis_text": "需要确认最新赛事信息"}

用户提问："昨天买的贵州茅台股票今天涨了吗？"
输出：{"need_search": true, "search_keywords": ["贵州茅台今日股价"], "analysis_text": "需要查询实时股价"}

用户提问："iPhone 17什么时候发布？"
输出：{"need_search": true, "search_keywords": ["iPhone 17发布时间"], "analysis_text": "需要查询最新产品发布信息"}

用户提问："杭州亚运会中国获得多少金牌？"
输出：{"need_search": true, "search_keywords": ["杭州亚运会中国金牌数"], "analysis_text": "需要查询赛事结果"}"""

    user_prompt = f"""用户提问：{message}

上下文信息：
{context_text[:2000]}

请分析是否需要联网搜索，并生成搜索关键词。"""

    max_retries = 2
    for attempt in range(1, max_retries + 1):
        try:
            response = await orchestration_client.chat.completions.create(
                model=ORCHESTRATION_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                stream=False,
                temperature=0.3
            )

            if response.usage:
                logger.info(f"[编排器] Token消耗(模型:{ORCHESTRATION_MODEL}): prompt={response.usage.prompt_tokens}, completion={response.usage.completion_tokens}, total={response.usage.total_tokens}")

            if response.choices and response.choices[0].message and response.choices[0].message.content:
                content = response.choices[0].message.content.strip()
                
                content = _clean_json_response(content)
                
                try:
                    result = json.loads(content)
                    if isinstance(result, dict):
                        need_search = result.get("need_search", False)
                        search_keywords = result.get("search_keywords", [])
                        analysis_text = result.get("analysis_text", "")
                        return {
                            "need_search": need_search,
                            "search_keywords": search_keywords,
                            "analysis_text": analysis_text
                        }
                except json.JSONDecodeError as je:
                    logger.warning(f"[编排器] 第{attempt}次调用JSON解析失败: {je}")
                    if attempt < max_retries:
                        user_prompt = f"""用户提问：{message}

上下文信息：
{context_text[:2000]}

请分析是否需要联网搜索，并生成搜索关键词。

【强制要求】
必须输出严格的JSON格式，不要包含任何markdown代码块标记（如```json），不要包含任何解释文字。
只输出JSON对象：{{"need_search": true/false, "search_keywords": [...], "analysis_text": "..."}}"""
                    continue
        except Exception as e:
            logger.error(f"[编排器] 第{attempt}次调用失败({ORCHESTRATION_MODEL}): {e}")
            if attempt < max_retries:
                continue

    logger.error(f"[编排器] 调用失败({ORCHESTRATION_MODEL})，已重试{max_retries}次")
    return {"need_search": False, "search_keywords": [], "analysis_text": "编排器调用失败"}


def _clean_json_response(content: str) -> str:
    if not content:
        return content
    
    content = content.strip()
    
    if content.startswith("```"):
        first_backtick = content.find("```")
        last_backtick = content.rfind("```")
        if first_backtick != last_backtick:
            content = content[first_backtick + 3:last_backtick]
        else:
            content = content[3:]
    
    content = content.strip()
    if content.startswith("json"):
        content = content[4:].strip()
    
    import re
    json_match = re.search(r'\{[\s\S]*\}', content)
    if json_match:
        content = json_match.group(0)
    
    return content.strip()


async def update_backend_search_results(session_id: int, message_uuid: str, search_results: list):
    backend_url = os.getenv("BACKEND_URL", "http://localhost:8080")
    internal_secret = os.getenv("INTERNAL_SECRET", "")
    update_url = f"{backend_url}/api/message/update-search-results"
    
    try:
        search_results_json = json.dumps(search_results, ensure_ascii=False)
        
        async with httpx.AsyncClient() as http_client:
            response = await http_client.post(
                update_url,
                json={
                    "session_id": session_id,
                    "message_uuid": message_uuid,
                    "search_results": search_results_json
                },
                headers={
                    "X-Internal-Secret": internal_secret
                },
                timeout=30.0
            )
            
            if response.status_code == 200:
                logger.info(f"[搜索结果保存] 成功: session_id={session_id}, message_uuid={message_uuid}, count={len(search_results)}")
            else:
                logger.error(f"[搜索结果保存] 失败: status={response.status_code}, {response.text}")
    except Exception as e:
        logger.error(f"[搜索结果保存] 调用后端失败: {str(e)}")


async def update_backend_message_content(session_id: int, message_uuid: str, message: str, extracted_text: str):
    backend_url = os.getenv("BACKEND_URL", "http://localhost:8080")
    internal_secret = os.getenv("INTERNAL_SECRET", "")
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
                headers={
                    "X-Internal-Secret": internal_secret
                },
                timeout=30.0
            )
            
            if response.status_code == 200:
                logger.info(f"[消息回写] 成功: session_id={session_id}, message_uuid={message_uuid}")
            else:
                logger.error(f"[消息回写] 失败: status={response.status_code}, {response.text}")
    except Exception as e:
        logger.error(f"[消息回写] 调用后端失败: {str(e)}")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/chat")
async def chat(request: ChatRequest):
    logger.info(f"[API入口] 收到聊天请求: type={request.message_type}, message='{request.message[:100]}...', "
                f"history={len(request.history) if request.history else 0}条, "
                f"user_id={request.user_id}, session_id={request.session_id}, mode={request.mode}")
    return StreamingResponse(
        stream_model_response(
            request.message, 
            request.history, 
            request.user_id, 
            request.session_id,
            request.message_type or "TEXT",
            request.media_url,
            request.media_urls,
            request.message_uuid,
            request.mode or "fast"
        ),
        media_type="text/event-stream; charset=utf-8"
    )


# === 专家模式处理函数 ===
async def expert_mode_process(message: str, history: Optional[List[dict]], user_id: Optional[int], 
                              session_id: Optional[int], message_type: str, media_url: Optional[str],
                              media_urls: Optional[List[str]], message_uuid: Optional[str],
                              request_start_time: float):
    """专家模式处理流程：编排器 + Tool调用循环 + 深度思考模型"""
    
    logger.info(f"[专家模式] 开始处理")
    
    # 1. 媒体提取（图片/文件）
    extracted_text = ""
    all_media_urls = media_urls or []
    if media_url and media_url not in all_media_urls:
        all_media_urls.append(media_url)
    
    is_multimodal = message_type in ("IMAGE", "FILE")
    if is_multimodal and len(all_media_urls) > 0:
        if len(all_media_urls) > 1:
            extracted_text = await extract_media_text_batch(all_media_urls, message_type)
        else:
            extracted_text = await extract_media_text(all_media_urls[0], message_type)
        
        if extracted_text:
            logger.info(f"[专家模式][媒体提取] 成功，长度: {len(extracted_text)}字符")
        else:
            logger.warning(f"[专家模式][媒体提取] 失败")
    
    # 2. 记忆检索
    memories = []
    if session_id:
        mem_start = time.time()
        try:
            search_query = f"{message} {extracted_text}" if extracted_text else message
            memories = await memory_service.search_memories(search_query, session_id, top_k=5)
            logger.info(f"[专家模式][记忆检索] 完成，找到{len(memories)}条相关记忆，耗时={time.time()-mem_start:.2f}秒")
        except Exception as e:
            logger.error(f"[专家模式][记忆检索] 失败: {e}")
    
    # 3. 构建上下文
    context_text = message
    if extracted_text:
        context_text += f"\n\n[图片/文件提取内容]\n{extracted_text}"
    if memories:
        memories_text = "\n".join([f"- {m['content']}" for m in memories])
        context_text += f"\n\n[相关记忆]\n{memories_text}"
    
    # 4. Tool调用循环
    tool_results = []
    search_results = []
    
    for iteration in range(EXPERT_MAX_ITERATIONS):
        logger.info(f"[专家模式][迭代 {iteration+1}/{EXPERT_MAX_ITERATIONS}]")
        
        # 调用专家编排器（传递迭代信息和对话历史）
        orch_start = time.time()
        is_last_iteration = (iteration == EXPERT_MAX_ITERATIONS - 1)
        orchestration_result = await _call_expert_orchestration_model(
            context_text, message, extracted_text, tool_results, len(all_media_urls) > 0,
            is_last_iteration, iteration + 1, EXPERT_MAX_ITERATIONS, history
        )
        logger.info(f"[专家模式][编排器] 调用完成，耗时={time.time()-orch_start:.2f}秒")
        
        if not orchestration_result:
            break
        
        need_search = orchestration_result.get("need_search", False)
        need_deep_thinking = orchestration_result.get("need_deep_thinking", False)
        need_more_info = orchestration_result.get("need_more_info", False)
        search_keywords = orchestration_result.get("search_keywords", [])
        
        # 关键修复：如果需要调用工具，强制继续迭代，确保工具结果被编排器看到后再生成回复
        if need_search or need_deep_thinking:
            need_more_info = True
            logger.info(f"[专家模式][强制迭代] 需要调用工具，强制need_more_info=True")
        
        # 最后一次迭代强制生成回复
        if iteration == EXPERT_MAX_ITERATIONS - 1:
            need_more_info = False
            logger.info(f"[专家模式][最后迭代] 强制生成最终回复")
        
        logger.info(f"[专家模式][编排器结果] need_search={need_search}, need_deep_thinking={need_deep_thinking}, "
                    f"need_more_info={need_more_info}, keywords={search_keywords}")
        
        # 调用联网搜索
        if need_search and search_keywords:
            # 发送搜索开始状态
            yield json.dumps({"type": "search_start", "data": {"keywords": search_keywords}}, ensure_ascii=False) + "\n"
            logger.info(f"[专家模式][联网搜索] 开始搜索: {search_keywords}")
            
            search_start = time.time()
            current_search_results = await search_service.web_search(search_keywords)
            search_context = await search_service.get_search_context(search_keywords)
            search_duration = time.time() - search_start
            logger.info(f"[专家模式][联网搜索] 完成，找到{len(current_search_results)}条结果，耗时={search_duration:.2f}秒")
            
            # 发送搜索摘要（包含搜索结果）
            # 过滤搜索结果，只保留标题和URL，不保存搜索摘要（content）
            filtered_results = []
            for result in current_search_results:
                filtered_results.append({
                    "title": result.get("title", ""),
                    "url": result.get("url", "")
                })
            
            search_summary = {
                "keywords": search_keywords,
                "results": filtered_results,
                "count": len(filtered_results),
                "duration": round(search_duration, 2)
            }
            yield json.dumps({"type": "search_summary", "data": search_summary}, ensure_ascii=False) + "\n"
            
            search_results.extend(filtered_results)
            tool_results.append({
                "type": "search",
                "keywords": search_keywords,
                "results": current_search_results,
                "context": search_context
            })
        
        # 调用深度思考模型（不依赖图片，支持文本问题的深度分析）
        if need_deep_thinking:
            thinking_start = time.time()
            # 深度思考模型返回生成器，收集思考内容并转发流式消息
            deep_result = ""
            async for chunk in _call_deep_thinking_model(message, all_media_urls, context_text, tool_results):
                # 转发流式消息（思考过程）
                yield chunk
                # 同时收集最终结果（从特殊标记中提取）
                if chunk.strip().startswith('{"type": "thinking"'):
                    try:
                        parsed = json.loads(chunk)
                        deep_result += parsed.get("data", "")
                    except:
                        pass
            
            logger.info(f"[专家模式][深度思考] 完成，耗时={time.time()-thinking_start:.2f}秒")
            
            tool_results.append({
                "type": "deep_thinking",
                "result": deep_result
            })
        
        # 判断是否需要继续迭代
        if not need_more_info:
            logger.info(f"[专家模式][迭代结束] 信息足够，停止迭代")
            break
    
    # 5. 构建最终响应 - 使用流式调用来生成回复内容
    logger.info(f"[专家模式][流式回复] 开始流式生成回复内容")
    
    async for chunk in _stream_expert_reply(message, context_text, extracted_text, 
                                            tool_results, search_results, history):
        yield chunk
    
    logger.info(f"[专家模式][流式回复] 完成")
    
    if search_results:
        yield json.dumps({"type": "search_results", "data": search_results}, ensure_ascii=False) + "\n"
        logger.info(f"[专家模式][搜索结果] 已通过流式响应返回: {len(search_results)}条")
    
    # 异步保存记忆
    if user_id:
        asyncio.create_task(
            memory_service.async_extract_and_store(
                message, "", user_id, session_id
            )
        )
    
    total_duration = time.time() - request_start_time
    logger.info(f"{'='*60}")
    logger.info(f"[专家模式][请求结束] 总耗时={total_duration:.2f}秒（流式回复）")
    logger.info(f"[专家模式][请求结束] 搜索结果数: {len(search_results)}")
    logger.info(f"[专家模式][请求结束] 记忆条数: {len(memories)}")
    logger.info(f"[专家模式][请求结束] Tool调用次数: {len(tool_results)}")
    logger.info(f"{'='*60}")
    return


async def _call_expert_orchestration_model(context_text: str, message: str, extracted_text: str, 
                                           tool_results: list, has_images: bool,
                                           is_last_iteration: bool = False, iteration: int = 1, 
                                           max_iterations: int = 3, history: Optional[List[dict]] = None) -> dict:
    """专家模式编排器：决定是否调用联网搜索和深度思考模型，信息足够时直接生成回复"""
    
    if not expert_orchestration_client:
        logger.warning("[专家模式][编排器] client未初始化，跳过编排")
        return {"need_search": False, "need_deep_thinking": False, "need_more_info": False, 
                "search_keywords": [], "analysis_text": "编排器未初始化"}
    
    start_time = time.time()
    
    system_prompt = """你是智能编排器，分析问题并决定工具调用。

【核心指令】
- 深度思考是专家模式的核心！除非问题极其简单，否则必须调用深度思考模型
- 深度思考模型能处理图片分析、复杂推理、多步分析、创造性问题
- 只有纯问候（你好、谢谢）或极其简单的常识（1+1=2）才跳过深度思考

【工具】
1. 搜索：获取最新信息（天气、新闻、股价等）
2. 深度思考：分析图片、复杂推理、深入分析（优先使用！）

【输出格式】JSON
{"need_search": true/false, "search_keywords": ["关键词"], "need_deep_thinking": true/false, "need_more_info": true/false, "analysis_text": "简短分析"}

【规则】
- 需要搜索或深度思考 → need_more_info=true
- 信息足够 → need_more_info=false
- 深度思考：有图片必调用；复杂问题必调用；包含"为什么/如何/分析/解释"必调用
- 最后一次迭代必须设置need_more_info=false

【示例】
用户："这张图片里的天气怎么样？" → {"need_search":true,"search_keywords":["北京今日天气"],"need_deep_thinking":true,"need_more_info":true,"analysis_text":"需要搜索+图片分析"}
用户："你是谁？" → {"need_search":false,"search_keywords":[],"need_deep_thinking":false,"need_more_info":false,"analysis_text":"简单问候"}
用户："为什么天空是蓝色的？" → {"need_search":false,"search_keywords":[],"need_deep_thinking":true,"need_more_info":true,"analysis_text":"需要深度解释"}"""
    
    # 构建对话历史文本
    history_text = ""
    if history:
        recent_history = history[-10:]  # 只取最近10条
        for msg in recent_history:
            role = msg.get("role", "")
            content = msg.get("content", "")[:500]  # 每条消息截断到500字符
            if role and content:
                role_cn = "用户" if role == "user" else "助手"
                history_text += f"\n{role_cn}：{content}"
    
    user_prompt = f"""当前迭代：第 {iteration}/{max_iterations} 次
是否最后一次迭代：{'是' if is_last_iteration else '否'}

用户提问：{message}

图片/文件提取内容：
{extracted_text[:3000] if extracted_text else '无'}

上下文信息：
{context_text[:2000]}

对话历史（最近10条）：
{history_text if history_text else '无'}

已有工具调用结果：
{json.dumps(tool_results, ensure_ascii=False) if tool_results else '无'}

是否有图片：{'是' if has_images else '否'}

请分析是否需要调用联网搜索和深度思考模型，并生成搜索关键词。
如果是最后一次迭代，请必须生成完整的reply_content。"""
    
    max_retries = 2
    for attempt in range(1, max_retries + 1):
        try:
            response = await expert_orchestration_client.chat.completions.create(
                model=EXPERT_ORCHESTRATION_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                stream=False,
                temperature=0.7,
                max_tokens=3000
            )
            
            if response.usage:
                logger.info(f"[专家模式][编排器] Token消耗(模型:{EXPERT_ORCHESTRATION_MODEL}): "
                            f"prompt={response.usage.prompt_tokens}, completion={response.usage.completion_tokens}, "
                            f"total={response.usage.total_tokens}")
            
            if response.choices and response.choices[0].message and response.choices[0].message.content:
                content = response.choices[0].message.content.strip()
                content = _clean_json_response(content)
                
                try:
                    result = json.loads(content)
                    if isinstance(result, dict):
                        return {
                            "need_search": result.get("need_search", False),
                            "search_keywords": result.get("search_keywords", []),
                            "need_deep_thinking": result.get("need_deep_thinking", False),
                            "need_more_info": result.get("need_more_info", False),
                            "analysis_text": result.get("analysis_text", "")
                        }
                except json.JSONDecodeError as je:
                    logger.warning(f"[专家模式][编排器] 第{attempt}次调用JSON解析失败: {je}")
                    if attempt < max_retries:
                        user_prompt = f"""用户提问：{message}

图片/文件提取内容：
{extracted_text[:3000] if extracted_text else '无'}

上下文信息：
{context_text[:2000]}

已有工具调用结果：
{json.dumps(tool_results, ensure_ascii=False) if tool_results else '无'}

是否有图片：{'是' if has_images else '否'}

请分析是否需要调用联网搜索和深度思考模型，并生成搜索关键词。

【强制要求】
必须输出严格的JSON格式，不要包含任何markdown代码块标记，不要包含任何解释文字。
只输出JSON对象：{{"need_search": true/false, "search_keywords": [...], "need_deep_thinking": true/false, "need_more_info": true/false, "analysis_text": "..."}}"""
                    continue
        except Exception as e:
            logger.error(f"[专家模式][编排器] 第{attempt}次调用失败({EXPERT_ORCHESTRATION_MODEL}): {e}")
            if attempt < max_retries:
                continue
    
    logger.error(f"[专家模式][编排器] 调用失败({EXPERT_ORCHESTRATION_MODEL})，已重试{max_retries}次")
    return {"need_search": False, "search_keywords": [], "need_deep_thinking": False, 
            "need_more_info": False, "analysis_text": "编排器调用失败"}


async def _stream_expert_reply(message: str, context_text: str, extracted_text: str,
                               tool_results: list, search_results: list, history: Optional[List[dict]] = None):
    """专家模式流式回复生成器：使用流式调用生成详细回复内容"""
    
    if not expert_orchestration_client:
        logger.warning("[专家模式][流式回复] client未初始化")
        return
    
    # 构建搜索结果文本
    search_text = ""
    if search_results:
        search_text = "\n".join([f"- {r.get('title', '')}: {r.get('url', '')}" for r in search_results])
    
    # 构建工具结果文本
    tool_text = ""
    if tool_results:
        for result in tool_results:
            if result.get("type") == "deep_thinking":
                tool_text += f"\n【深度思考结果】\n{result.get('result', '')}"
            elif result.get("type") == "search":
                tool_text += f"\n【搜索结果】\n{result.get('result', '')}"
    
    # 构建对话历史文本
    history_text = ""
    if history:
        recent_history = history[-10:]
        for msg in recent_history:
            role = msg.get("role", "")
            content = msg.get("content", "")[:500]
            if role and content:
                role_cn = "用户" if role == "user" else "助手"
                history_text += f"\n{role_cn}：{content}"
    
    system_prompt = """你是爱尔奎特·布伦史塔德，高贵的真祖，月之公主。

【核心指令】
- 基于深度思考结果进行精简总结，保留核心推理过程和结论
- 不要添加深度思考结果中没有的内容，不要自由发挥
- 用高贵傲慢的语气重新组织语言，保持角色设定"""
    
    user_prompt = f"""用户提问：{message}

图片/文件提取内容：
{extracted_text[:3000] if extracted_text else '无'}

搜索结果：
{search_text}

深度思考结果：
{tool_text}

对话历史：
{history_text}

请生成回复，保持深度思考结果的基本结构，优化格式使其美观。"""
    
    try:
        response = await expert_orchestration_client.chat.completions.create(
            model=EXPERT_ORCHESTRATION_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            stream=True,
            temperature=0.7,
            max_tokens=3000
        )
        
        full_content = ""
        async for chunk in response:
            if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                content_chunk = chunk.choices[0].delta.content
                full_content += content_chunk
                yield json.dumps({"type": "content", "data": content_chunk}, ensure_ascii=False) + "\n"
        
        logger.info(f"[专家模式][流式回复] 完成，内容长度: {len(full_content)}字符")
        return
        
    except Exception as e:
        logger.error(f"[专家模式][流式回复] 调用失败: {e}")
        return


async def _call_deep_thinking_model(message: str, media_urls: list, context_text: str, tool_results: list):
    """深度思考模型：接收图片URL进行深度分析，流式返回思考过程"""
    
    if not deep_thinking_client:
        logger.warning("[专家模式][深度思考] client未初始化，跳过深度思考")
        return
    
    start_time = time.time()
    
    system_prompt = """你是深度思考模型，擅长分析图片和解决复杂问题。

【任务】
- 分析图片内容：识别物体、场景、文字、图表
- 解决复杂问题：多步推理、深入分析、创造性思考
- 输出思考过程：一步一步展示你的真实推理过程

【输出要求】
- 用自然语言写出你的思考过程，不要刻意格式化
- 先分析问题，再逐步推理，最后给出结论
- 推理过程要详细，展示你的分析思路
- 结论要明确，回答用户的问题"""
    
    # 构建用户消息（包含图片URL）
    user_content = [{"type": "text", "text": f"用户提问：{message}\n\n上下文：{context_text}"}]
    for url in media_urls:
        user_content.append({"type": "image_url", "image_url": {"url": url}})
    
    # 添加工具调用结果
    if tool_results:
        results_text = "\n".join([
            f"【{r['type']}】\n{r['context'] if 'context' in r else r['result']}" 
            for r in tool_results 
            if 'context' in r or 'result' in r
        ])
        system_prompt += f"\n\n【已有工具调用结果】\n{results_text}"
    
    # 发送深度思考开始状态
    yield json.dumps({"type": "thinking_start", "data": {"message": "正在深度分析图片..."}}, ensure_ascii=False) + "\n"
    logger.info(f"[专家模式][深度思考] 开始分析图片: {len(media_urls)}张图片")
    
    try:
        response = await deep_thinking_client.chat.completions.create(
            model=EXPERT_DEEP_THINKING_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            stream=True,
            temperature=0.3
        )
        
        logger.info(f"[专家模式][深度思考] 成功连接到模型API({EXPERT_DEEP_THINKING_MODEL}), 开始流式传输")
        
        chunk_count = 0
        total_content = ""
        async for chunk in response:
            if chunk.choices and chunk.choices[0].delta:
                content = chunk.choices[0].delta.content
                if content:
                    chunk_count += 1
                    total_content += content
                    # 发送思考过程的流式消息
                    yield json.dumps({"type": "thinking", "data": content}, ensure_ascii=False) + "\n"
                    logger.debug(f"[专家模式][深度思考] 思考过程分片 {chunk_count}: '{content[:30]}...'")
        
        duration = time.time() - start_time
        
        if hasattr(response, 'usage') and response.usage:
            logger.info(f"[专家模式][深度思考] Token消耗(模型:{EXPERT_DEEP_THINKING_MODEL}): "
                        f"prompt={response.usage.prompt_tokens}, completion={response.usage.completion_tokens}, "
                        f"total={response.usage.total_tokens}, 耗时={duration:.2f}秒")
        
        logger.info(f"[专家模式][深度思考] 完成, 总分片数={chunk_count}, 内容长度={len(total_content)}字符")
    
    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"[专家模式][深度思考] 失败({EXPERT_DEEP_THINKING_MODEL}): {str(e)}，耗时={duration:.2f}秒")
        yield json.dumps({"type": "thinking_error", "data": {"error": str(e)}}, ensure_ascii=False) + "\n"


async def generate_summary(messages: Optional[List[dict]], existing_summary: Optional[str]):
    logger.info(f"[摘要生成] 开始: 消息数量={len(messages) if messages else 0}, 已有摘要={'是' if existing_summary else '否'}")

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

    system_prompt = """你是一个专业的对话摘要助手。请根据对话内容生成结构化事实摘要。

摘要要求：
1. 长度不超过500个字符
2. 使用JSON格式输出，包含以下字段：
   - "key_points": 关键要点数组（3-5条）
   - "entities": 涉及的实体/人物列表
   - "summary": 简短的自然语言摘要（100字以内）"""

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
            logger.info(f"[摘要生成] 成功: 长度={len(summary_content)}")
            return summary_content
        else:
            logger.warning("[摘要生成] 未收到模型返回的摘要内容")
            return None

    except Exception as e:
        logger.error(f"[摘要生成] 出错: {str(e)}")
        return None


@app.post("/summarize")
async def summarize(request: SummarizeRequest):
    logger.info(f"[API入口] 收到摘要请求: 消息数量={len(request.messages) if request.messages else 0} 条")

    summary = await generate_summary(request.messages, request.existing_summary)

    if summary:
        return {"summary": summary}
    else:
        return {"summary": ""}


from fastapi import HTTPException, Request
from qdrant_client import models as qdrant_models
from config.settings import QDRANT_COLLECTION

class DeleteMemoryRequest(BaseModel):
    session_id: str

@app.delete("/memory/delete")
async def delete_memory(request: DeleteMemoryRequest, request_obj: Request):
    internal_secret = os.getenv("INTERNAL_SECRET", "")
    header_secret = request_obj.headers.get("X-Internal-Secret", "")
    
    if not internal_secret or not header_secret or not header_secret == internal_secret:
        logger.warning(f"[内存删除] 内部接口认证失败: sessionId={request.session_id}")
        raise HTTPException(status_code=403, detail="内部接口认证失败")
    
    logger.info(f"[内存删除] 收到请求: sessionId={request.session_id}, 类型={type(request.session_id)}")
    
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
                        match=qdrant_models.MatchValue(value=str(request.session_id))
                    )]
                )
            )
        )
        
        logger.info(f"[内存删除] 完成: sessionId={request.session_id}, 已删除{result.count if hasattr(result, 'count') else '未知'}条记录")
        
        return {"success": True, "message": "记忆删除成功"}
    except Exception as e:
        logger.error(f"[内存删除] 失败: sessionId={request.session_id}, 错误={str(e)}")
        raise HTTPException(status_code=500, detail=f"删除记忆失败: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    logger.info("启动XiaoAi Agent...")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)