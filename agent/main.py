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


class ChatRequest(BaseModel):
    message: str
    history: Optional[List[dict]] = None
    user_id: Optional[int] = None
    session_id: Optional[str] = None
    message_type: Optional[str] = "TEXT"
    media_url: Optional[str] = None
    media_urls: Optional[List[str]] = None
    message_uuid: Optional[str] = None


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
    start_time = time.time()
    logger.info(f"[批量提取] 开始提取{media_type}文本: 数量={len(media_urls)}")
    
    all_extracted = []
    for i, url in enumerate(media_urls):
        logger.info(f"[批量提取] 提取第{i+1}/{len(media_urls)}个{media_type}: {url[:50]}...")
        text = await extract_media_text(url, media_type)
        if text:
            all_extracted.append(f"【文件{i+1}】\n{text}")
        else:
            all_extracted.append(f"【文件{i+1}】\n[提取失败]")
    
    duration = time.time() - start_time
    result = "\n\n".join(all_extracted)
    logger.info(f"[批量提取] 完成，总字符数: {len(result)}, 耗时={duration:.2f}秒")
    
    return result


async def stream_model_response(message: str, history: Optional[List[dict]] = None,
                                user_id: Optional[int] = None, session_id: Optional[int] = None,
                                message_type: str = "TEXT", media_url: Optional[str] = None,
                                media_urls: Optional[List[str]] = None,
                                message_uuid: Optional[str] = None):
    request_start_time = time.time()
    logger.info(f"{'='*60}")
    logger.info(f"[请求开始] 会话ID: {session_id}, 用户ID: {user_id}, 消息类型: {message_type}")
    logger.info(f"[请求开始] 用户消息: '{message[:100]}...'")
    logger.info(f"[请求开始] 历史消息数: {len(history) if history else 0}")
    logger.info(f"{'='*60}")

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
            yield json.dumps({"type": "search_results", "data": search_results}, ensure_ascii=False) + "\n"
            logger.info(f"[搜索结果] 已通过流式响应返回: {len(search_results)}条")

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

【输出格式】
必须输出严格的JSON格式，包含以下字段：
- need_search: 布尔值，是否需要联网搜索
- search_keywords: 字符串数组，搜索关键词列表（最多5个）
- analysis_text: 对问题的简要分析（用于调试）

【判断规则】
- 需要最新信息（新闻、事件、数据、当前状态）→ need_search: true
- 需要专业知识但不确定准确性 → 需要搜索验证
- 关于人物、地点、事件的最新信息 → 需要搜索
- 纯聊天、情感交流、已有记忆足够回答 → need_search: false
- 已有记忆中的信息可以直接回答 → need_search: false"""

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
                f"user_id={request.user_id}, session_id={request.session_id}")
    return StreamingResponse(
        stream_model_response(
            request.message, 
            request.history, 
            request.user_id, 
            request.session_id,
            request.message_type or "TEXT",
            request.media_url,
            request.media_urls,
            request.message_uuid
        ),
        media_type="text/event-stream"
    )


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