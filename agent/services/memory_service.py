import asyncio
import hashlib
import logging
import re
from collections import Counter
from typing import List, Optional, Dict, Any

import jieba
import numpy as np
import redis
from qdrant_client import QdrantClient, models
from openai import AsyncOpenAI

from config.settings import (
    QDRANT_HOST, QDRANT_PORT, QDRANT_COLLECTION,
    EMBEDDING_MODEL, EMBEDDING_API_KEY, EMBEDDING_API_BASE,
    RERANK_MODEL, RERANK_API_KEY, RERANK_API_BASE,
    EXTRACTION_MODEL, EXTRACTION_API_KEY, EXTRACTION_API_BASE,
    API_KEY, API_BASE
)
# ========== 以下为新集中配置文件引入，消除散落的硬编码字面量 ==========
# 行为参数（温度/top_k/权重/截断/停用词）统一放到 config.behavior
from config.behavior import (
    STOPWORDS, TOKEN_MIN_LEN,
    BM25_K1, BM25_B, BM25_AVG_DOC_LEN_HINT, BM25_LOG_KEYWORDS_TOP_N,
    HYBRID_DENSE_BASE_WEIGHT, HYBRID_BM25_WEIGHT, HYBRID_IMPORTANCE_WEIGHT,
    MEMORY_SEARCH_DEFAULT_TOP_K,
    MEMORY_EXTRACTION_TEMPERATURE, MEMORY_EXTRACTION_MAX_TOKENS,
    MEMORY_EXTRACTION_MAX_RETRIES, MEMORY_EXTRACTION_FALLBACK_MODEL,
    MEMORY_CONTENT_DEFAULT_MAX_LENGTH,
    MEMORY_COUNT_BASELINE_NO_MEDIA, MEMORY_COUNT_BASELINE_MINIMUM,
)
# Prompt 大段文本统一放到 config.prompts.memory_extraction
from config.prompts.memory_extraction import (
    MEMORY_EXTRACTION_SYSTEM_PROMPT,
    build_memory_extraction_user_prompt,
)

logger = logging.getLogger("XiaoAi Memory Service")


def _extraction_extra_kwargs() -> Dict[str, Any]:
    """
    记忆提取模型调用的「关思考」附加参数构造（单文件内聚封装）。

    设计意图：
    - 记忆提取要求输出严格 JSON 数组，一旦模型开启 thinking（尤其 qwen3.8 系），
      会先输出 reasoning 文本或 <think> 标签，破坏 JSON 解析，导致提取失败或空数组。
    - 这里统一对提取调用注入 enable_thinking=False，透传方式兼容 AsyncOpenAI extra_body，
      不关心当前槽位是 deepseek / qwen3.8 / 其他，extra_body 未知字段通常被忽略，
      但 qwen3.8 系能被正确关思考，后续你把 EXTRACTION_MODEL 换成 qwen3.8-27b 也无需改代码。
    :return: 可直接 ** 解包到 chat.completions.create 的 kwargs
    """
    logger.debug("[记忆提取] 调用时注入 enable_thinking=False，避免 reasoning 污染 JSON")
    return {"extra_body": {"enable_thinking": False}}


class MemoryService:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def init(self):
        """
        初始化MemoryService，创建Qdrant、Redis、嵌入模型、重排序模型和提取模型的客户端
        """
        if self._initialized:
            logger.debug("MemoryService已初始化，跳过")
            return

        self.qdrant_client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
        self._init_redis_client()
        self._init_embedding_client()
        self._create_collection_if_not_exists()
        self._init_rerank_client()
        self._init_extraction_client()
        self._initialized = True
        logger.info("✅ MemoryService初始化成功")

    def _init_redis_client(self):
        """初始化Redis客户端，用于字面去重"""
        try:
            self.redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True, protocol=2)
            self.redis_client.ping()
            logger.info("🔗 Redis客户端连接成功")
        except Exception as e:
            logger.error(f"🔗 Redis连接失败: {e}, 将跳过Redis去重")
            self.redis_client = None

    def _init_embedding_client(self):
        """初始化嵌入模型客户端，用于生成文本向量"""
        if EMBEDDING_API_KEY:
            base_url = EMBEDDING_API_BASE if EMBEDDING_API_BASE else API_BASE
            self.embedding_client = AsyncOpenAI(
                api_key=EMBEDDING_API_KEY,
                base_url=base_url
            )
            self.embedding_model = EMBEDDING_MODEL
            if "v4" in EMBEDDING_MODEL.lower():
                self.embedding_dim = 1024
            elif "small" in EMBEDDING_MODEL.lower():
                self.embedding_dim = 384
            else:
                self.embedding_dim = 1024
            logger.info(f"🔹 使用API嵌入模型: {EMBEDDING_MODEL}, 维度={self.embedding_dim}")
        else:
            self.embedding_client = None
            self.embedding_model = None
            self.embedding_dim = 384
            logger.warning("🔹 未配置嵌入API密钥")

    def _init_rerank_client(self):
        """初始化重排序模型客户端，用于对检索结果重排序"""
        if RERANK_API_KEY:
            base_url = RERANK_API_BASE if RERANK_API_BASE else API_BASE
            if "/compatible-api/v1" not in base_url:
                base_url = base_url.replace("/compatible-mode/v1", "/compatible-api/v1")
            self.rerank_client = AsyncOpenAI(
                api_key=RERANK_API_KEY,
                base_url=base_url
            )
            self.rerank_model = RERANK_MODEL
            logger.info(f"🔹 使用API重排序模型: {RERANK_MODEL}")
        else:
            self.rerank_client = None
            self.rerank_model = None
            logger.info("🔹 未配置重排序API密钥，跳过重排序")

    def _init_extraction_client(self):
        """初始化记忆提取模型客户端，用于从对话中提取记忆单元"""
        if EXTRACTION_MODEL and EXTRACTION_API_KEY:
            self.extraction_client = AsyncOpenAI(
                api_key=EXTRACTION_API_KEY,
                base_url=EXTRACTION_API_BASE if EXTRACTION_API_BASE else API_BASE
            )
            self.extraction_model = EXTRACTION_MODEL
            logger.info(f"🔹 使用独立的记忆提取模型: {EXTRACTION_MODEL}")
        else:
            self.extraction_client = None
            self.extraction_model = None
            logger.info("🔹 未配置独立的记忆提取模型，将使用主模型")

    def _create_collection_if_not_exists(self):
        """创建Qdrant集合（如果不存在），配置向量维度和距离度量"""
        try:
            collections = self.qdrant_client.get_collections().collections
            collection_names = [c.name for c in collections]

            if QDRANT_COLLECTION not in collection_names:
                self.qdrant_client.create_collection(
                    collection_name=QDRANT_COLLECTION,
                    vectors_config=models.VectorParams(
                        size=self.embedding_dim,
                        distance=models.Distance.COSINE
                    )
                )
                logger.info(f"📦 创建Qdrant集合: {QDRANT_COLLECTION}, dense_dim={self.embedding_dim}")
            else:
                logger.info(f"📦 Qdrant集合已存在: {QDRANT_COLLECTION}")
        except Exception as e:
            logger.error(f"📦 创建/验证Qdrant集合失败: {e}")

    def _tokenize(self, text: str) -> List[str]:
        """
        中英文分词，使用jieba处理中文，正则处理英文，过滤停用词。
        停用词表、最小token长度统一从 config.behavior 读取，便于后续调优。
        :param text: 输入文本
        :return: 分词结果列表
        """
        text = text.lower()

        chinese_tokens = jieba.lcut(text)

        english_tokens = re.findall(r'[a-zA-Z]+', text)

        # 停用词集合从配置读取（避免每次 _tokenize 都构造一个 set 字面量，节省 GC）
        stopwords = STOPWORDS

        tokens = []
        for token in chinese_tokens:
            if len(token) >= TOKEN_MIN_LEN and token not in stopwords:
                tokens.append(token)

        for token in english_tokens:
            if len(token) >= TOKEN_MIN_LEN and token.lower() not in stopwords:
                tokens.append(token.lower())

        return tokens

    def _calculate_bm25(self, text: str) -> Dict[str, float]:
        """
        计算BM25关键词分数，基于TF（词频）和简化的IDF。
        参数 k1 / b / 平均文档长度 统一放到 config.behavior 便于调权。
        :param text: 输入文本
        :return: 关键词及其分数的字典
        """
        tokens = self._tokenize(text)
        token_counts = Counter(tokens)
        max_freq = max(token_counts.values()) if token_counts else 1

        # 从配置读取 BM25 核心超参
        k1 = BM25_K1
        b = BM25_B
        avgdl = BM25_AVG_DOC_LEN_HINT

        scores = {}
        for token, count in token_counts.items():
            tf = (count * (k1 + 1)) / (count + k1 * (1 - b + b * len(tokens) / avgdl))
            scores[token] = float(tf)

        return scores

    async def generate_embedding(self, text: str) -> Optional[List[float]]:
        """
        生成文本的稠密向量嵌入
        :param text: 输入文本
        :return: 向量列表，失败返回None
        """
        if not self.embedding_client:
            logger.warning("嵌入客户端未初始化")
            return None

        try:
            response = await self.embedding_client.embeddings.create(
                model=self.embedding_model,
                input=text
            )
            embedding = response.data[0].embedding
            logger.debug(f"生成嵌入向量: '{text[:30]}...', 维度={len(embedding)}")
            return embedding
        except Exception as e:
            logger.error(f"生成嵌入向量失败: {e}")
            return None

    async def extract_memory_units(self, user_message: str, assistant_message: str,
                                   user_id: int, session_id: str = None, existing_memories: List[str] = None) -> List[Dict[str, Any]]:
        """
        从对话中提取记忆单元，调用记忆提取模型进行语义分析。
        【硬编码移除】
          - system_prompt / user_prompt 统一放到 config.prompts.memory_extraction；
          - 字数/条数/温度/重试次数/fallback 模型名统一放到 config.behavior；
          便于后续调参和多语言改造。
        :param user_message: 用户消息
        :param assistant_message: 助手回复
        :param user_id: 用户ID
        :param session_id: 会话ID
        :param existing_memories: 已有记忆列表（用于去重参考）
        :return: 提取的记忆单元列表
        """
        messages_text = f"User: {user_message}\nAssistant: {assistant_message}"
        logger.debug(f"开始记忆提取: user_id={user_id}, session_id={session_id}, message='{user_message[:50]}...'")

        # 根据 [图片/文件内容] 出现次数，给出最少提取条数：max(MEMORY_COUNT_BASELINE_MINIMUM, MEMORY_COUNT_BASELINE_NO_MEDIA + media_count)
        media_count = messages_text.count("[图片内容]") + messages_text.count("[文件内容]")
        max_memory_count = max(MEMORY_COUNT_BASELINE_MINIMUM, MEMORY_COUNT_BASELINE_NO_MEDIA + media_count)
        max_content_length = MEMORY_CONTENT_DEFAULT_MAX_LENGTH

        # system_prompt 统一读配置
        system_prompt = MEMORY_EXTRACTION_SYSTEM_PROMPT
        # 首次调用 user_prompt 使用"正常"模式（已有记忆可引用）
        user_prompt = build_memory_extraction_user_prompt(
            messages_text, existing_memories,
            max_content_length=max_content_length,
            max_memory_count=max_memory_count,
            strict_without_existing=False,
        )

        try:
            if self.extraction_client and self.extraction_model:
                client = self.extraction_client
                model = self.extraction_model
            else:
                client = AsyncOpenAI(api_key=API_KEY, base_url=API_BASE)
                model = MEMORY_EXTRACTION_FALLBACK_MODEL

            memory_units = await self._extract_with_retry(
                client, model,
                system_prompt, user_prompt,
                messages_text, user_id, session_id,
                max_memory_count, max_content_length,
            )
            return memory_units
        except Exception as e:
            logger.error(f"记忆提取失败: {e}")
            return []

    async def _extract_with_retry(self, client, model, system_prompt, user_prompt, messages_text, user_id, session_id: str, max_memory_count, max_content_length):
        """
        带重试的记忆提取，格式校验失败时重试一次。
        所有超参（重试次数/温度/max_tokens/关思考开关）集中到 config.behavior 和 prompts 配置。
        """
        max_retries = MEMORY_EXTRACTION_MAX_RETRIES
        for attempt in range(1, max_retries + 1):
            # 记忆提取：强制关闭思考（推理内容会破坏 JSON 数组解析结构，导致提取为空）
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=MEMORY_EXTRACTION_TEMPERATURE,
                max_tokens=MEMORY_EXTRACTION_MAX_TOKENS,
                **_extraction_extra_kwargs()
            )

            if response.choices and response.choices[0].message and response.choices[0].message.content:
                content = response.choices[0].message.content.strip()
                logger.debug(f"记忆提取模型原始响应(第{attempt}次): {content}")

                content = content.strip()
                if content.startswith("```"):
                    content = content.split("```")[1]
                    if content.startswith("json"):
                        content = content[4:].strip()

                import json
                try:
                    memory_units = json.loads(content)
                    if isinstance(memory_units, list):
                        valid_units = []
                        for unit in memory_units[:max_memory_count]:
                            if isinstance(unit, dict) and unit.get("content") and unit.get("type"):
                                content_str = str(unit["content"])
                                if len(content_str) <= max_content_length:
                                    valid_units.append(unit)
                                else:
                                    logger.debug(f"记忆内容过长({len(content_str)}>={max_content_length}), 跳过")

                        for unit in valid_units:
                            unit["userId"] = user_id
                            unit["sessionId"] = session_id
                            unit["timestamp"] = int(asyncio.get_event_loop().time())

                        if len(valid_units) == 0:
                            logger.info(f"提取结果: 空数组(纯问候语或无新信息), user_id={user_id}, session_id={session_id}")
                        else:
                            logger.info(f"提取结果: {len(valid_units)} 个记忆单元, user_id={user_id}, session_id={session_id}")
                        return valid_units
                except json.JSONDecodeError:
                    logger.warning(f"第{attempt}次提取格式校验失败: {content[:300]}")

            if attempt < max_retries:
                logger.info(f"第{attempt}次提取失败，准备重试...")
                # 重试用 strict_without_existing=True 清空"已有记忆"引用，避免旧记忆干扰导致格式出问题
                user_prompt = build_memory_extraction_user_prompt(
                    messages_text, None,
                    max_content_length=max_content_length,
                    max_memory_count=max_memory_count,
                    strict_without_existing=True,
                )
                # 在严格重试模式下额外追加强约束行（与原硬编码完全一致）
                user_prompt += (
                    "\n- 必须输出严格的JSON数组格式，不要包含任何其他文字\n\n"
                    "请重新提取本轮对话的关键记忆。"
                )

        logger.info(f"提取结果: 重试{max_retries}次仍失败, user_id={user_id}, session_id={session_id}")
        return []

    def _generate_stable_point_id(self, content: str, user_id: int) -> str:
        """
        使用MD5生成稳定的UUID格式point_id，确保Qdrant和Redis中ID一致
        :param content: 记忆内容
        :param user_id: 用户ID
        :return: UUID格式的point_id字符串
        """
        hash_str = f"{user_id}:{content}"
        hash_bytes = hashlib.md5(hash_str.encode('utf-8')).digest()
        hex_str = hash_bytes.hex()
        point_id = f"{hex_str[:8]}-{hex_str[8:12]}-{hex_str[12:16]}-{hex_str[16:20]}-{hex_str[20:]}"
        logger.debug(f"生成稳定point_id: content='{content[:30]}...', user_id={user_id}, point_id={point_id}")
        return point_id

    def _is_duplicate_literal(self, point_id: str, session_id: str) -> bool:
        """
        第一层去重：检查Redis中是否已存在相同的point_id（字面去重）
        :param point_id: 记忆点ID
        :param session_id: 会话ID
        :return: True表示重复，False表示不重复
        """
        if not self.redis_client:
            logger.debug("Redis客户端未连接, 跳过字面去重")
            return False
        
        redis_key = f"memory:duplicate:{session_id}"
        exists = self.redis_client.sismember(redis_key, point_id)
        if exists:
            logger.info(f"✅ 字面去重命中: point_id={point_id[:20]}..., session_id={session_id}")
            return True
        logger.debug(f"字面去重未命中: point_id={point_id[:20]}..., session_id={session_id}")
        return False

    def _mark_as_stored(self, point_id: str, session_id: str):
        """
        将已存储的记忆点ID标记到Redis，用于后续字面去重
        :param point_id: 记忆点ID
        :param session_id: 会话ID
        """
        if not self.redis_client:
            logger.debug("Redis客户端未连接, 跳过标记已存储")
            return
        
        redis_key = f"memory:duplicate:{session_id}"
        result = self.redis_client.sadd(redis_key, point_id)
        self.redis_client.expire(redis_key, 30 * 24 * 3600)
        logger.debug(f"📝 标记已存储: point_id={point_id[:20]}..., session_id={session_id}, result={result}")

    def _is_session_deleted_tombstone(self, session_id: str) -> bool:
        """
        【墓碑机制-可选】通过 Redis 墓碑 key 判断会话是否已被删除。
        这是对后端 SessionServiceImpl 所立墓碑的"读端同步判断"，用于记忆写入前的二次拦截：
        一旦流结束后异步触发记忆提取时会话已被用户删除，就跳过向量 upsert，
        减少 Qdrant 孤儿向量点产生（定时清理仍会兜底，但这里能少写就少写）。
        :param session_id: 会话ID（字符串或数字都行，内部会 str 统一）
        :return: True=会话已删除，应跳过写入；False=会话存活或 Redis 未连接（保守放行）
        """
        if not session_id:
            return False
        if not self.redis_client:
            # Redis 未连接时无法判断，保守放行（后续定时孤儿清理兜底）
            return False
        tombstone_key = f"session:deleted:{session_id}"
        try:
            exists = self.redis_client.exists(tombstone_key) > 0
            if exists:
                logger.info(f"[墓碑命中-store_memory] 会话已被后端标记删除，跳过记忆写入: session_id={session_id}")
            return exists
        except Exception as e:
            logger.warning(f"[墓碑] Redis 墓碑查询异常(将保守放行): session_id={session_id}, 错误={e}")
            return False

    async def _is_duplicate_vector(self, content: str, dense_vector: List[float], session_id: str, threshold: float = 0.85) -> bool:
        """
        第二层去重：检查向量库中是否存在相似记忆（向量相似度去重）
        :param content: 记忆内容
        :param dense_vector: 稠密向量
        :param session_id: 会话ID
        :param threshold: 相似度阈值，默认0.85
        :return: True表示重复，False表示不重复
        """
        try:
            results = self.qdrant_client.query_points(
                collection_name=QDRANT_COLLECTION,
                query=dense_vector,
                query_filter=models.Filter(
                    must=[models.FieldCondition(
                        key="sessionId",
                        match=models.MatchValue(value=str(session_id))  # 强制转换为字符串
                    )]
                ),
                limit=5,
                with_payload=True
            )
            
            if results.points:
                max_score = 0
                max_content = ""
                for point in results.points:
                    existing_content = point.payload.get("content", "")[:30] if point.payload else "N/A"
                    logger.debug(f"  - 候选: id={point.id[:20]}..., score={point.score:.4f}, content='{existing_content}...'")
                    if point.score > max_score:
                        max_score = point.score
                        max_content = existing_content
                    if point.score >= threshold:
                        logger.info(f"✅ 向量相似度去重命中: content='{content[:30]}...', 相似度={point.score:.4f}, threshold={threshold}, 已存在记忆='{existing_content}...'")
                        return True
                
                logger.info(f"向量相似度去重未命中: content='{content[:30]}...', 最高相似度={max_score:.4f}, threshold={threshold}, 最相似记忆='{max_content}...'")
            else:
                logger.info(f"向量相似度去重未命中: content='{content[:30]}...', 无相似记忆")
        except Exception as e:
            logger.error(f"向量相似度去重检查失败: {e}")
        
        return False

    async def store_memory(self, memory_units: List[Dict[str, Any]]):
        """
        存储记忆单元到Qdrant，包含两层去重（字面去重+向量相似度去重）
        :param memory_units: 记忆单元列表
        """
        if not memory_units:
            logger.debug("没有记忆单元需要存储")
            return

        logger.info(f"📥 开始存储 {len(memory_units)} 个记忆单元")
        points = []
        skipped_literal = 0
        skipped_vector = 0
        skipped_tombstone = 0
        failed_embedding = 0
        
        for idx, unit in enumerate(memory_units):
            content = unit.get("content", "")
            if not content:
                logger.debug(f"跳过空记忆单元 #{idx}")
                continue

            user_id = unit.get("userId", 0)
            session_id = unit.get("sessionId", 0)

            # 【墓碑可选拦截】会话已被后端删除时不做后续去重/嵌入/写入
            if self._is_session_deleted_tombstone(str(session_id)):
                skipped_tombstone += 1
                continue
            
            point_id = self._generate_stable_point_id(content, user_id)
            
            if self._is_duplicate_literal(point_id, session_id):
                skipped_literal += 1
                continue

            dense_vector = await self.generate_embedding(content)
            if dense_vector is None:
                failed_embedding += 1
                continue

            if await self._is_duplicate_vector(content, dense_vector, session_id):
                skipped_vector += 1
                continue

            bm25_scores = self._calculate_bm25(content)
            logger.debug(f"BM25关键词: {list(bm25_scores.keys())[:5]}")

            payload = {
                "userId": user_id,
                "sessionId": str(session_id),  # 强制转换为字符串，确保与删除时的类型一致
                "content": content,
                "type": unit.get("type", "FACTS"),
                "importance_score": unit.get("importance_score", 0.5),
                "entities": unit.get("entities", []),
                "timestamp": unit.get("timestamp", 0),
                "bm25_keywords": list(bm25_scores.keys())[:10]
            }

            points.append(models.PointStruct(
                id=point_id,
                vector=dense_vector,
                payload=payload
            ))

        if points:
            try:
                logger.info(f"📥 向Qdrant集合 {QDRANT_COLLECTION} 写入 {len(points)} 个点")
                result = self.qdrant_client.upsert(
                    collection_name=QDRANT_COLLECTION,
                    points=points
                )
                
                for point in points:
                    self._mark_as_stored(point.id, point.payload.get("sessionId", 0))
                
                collection_info = self.qdrant_client.get_collection(QDRANT_COLLECTION)
                logger.info(f"✅ 成功存储 {len(points)} 个记忆点到Qdrant")
                logger.info(f"📊 存储统计: dense_dim={self.embedding_dim}, bm25_keywords={len(bm25_scores) if points else 0}, total_points={collection_info.points_count}")
                logger.info(f"📊 去重统计: 墓碑跳过={skipped_tombstone}, 字面去重跳过={skipped_literal}, 向量去重跳过={skipped_vector}, 嵌入失败={failed_embedding}")
            except Exception as e:
                logger.error(f"❌ 存储记忆失败: {e}")
        else:
            logger.warning(f"📥 处理后没有有效的记忆点需要存储(墓碑跳过={skipped_tombstone}, 字面去重={skipped_literal}, 向量去重={skipped_vector}, 嵌入失败={failed_embedding})")

    async def search_memories(self, query: str, session_id: str, top_k: int = None) -> List[Dict[str, Any]]:
        """
        混合搜索记忆：稠密向量搜索 + BM25关键词搜索 + 重要性分数融合 + Rerank重排序。
        【硬编码移除】
          - top_k 默认值由 MEMORY_SEARCH_DEFAULT_TOP_K 提供（避免调用方漏传时行为不一）
          - BM25 关键字遍历上限、打分公式权重统一来自 config.behavior
        :param query: 查询文本
        :param session_id: 会话ID
        :param top_k: 返回结果数量（None 时读默认 MEMORY_SEARCH_DEFAULT_TOP_K）
        :return: 排序后的记忆结果列表
        """
        if not self.embedding_client:
            logger.warning("嵌入客户端未初始化, 跳过记忆检索")
            return []

        # top_k 缺省走配置（调用处目前有显式 top_k=5；这里兜底防止新增调用忘了传参）
        if top_k is None:
            top_k = MEMORY_SEARCH_DEFAULT_TOP_K

        logger.info(f"🔍 开始记忆检索, session_id={session_id}, 查询='{query[:50]}...', top_k={top_k}")

        dense_vector = await self.generate_embedding(query)
        if dense_vector is None:
            logger.error("❌ 查询向量生成失败, 跳过检索")
            return []

        bm25_scores = self._calculate_bm25(query)
        keywords = list(bm25_scores.keys())
        logger.debug(f"BM25关键词提取: {keywords[:BM25_LOG_KEYWORDS_TOP_N]}")

        try:
            dense_results = self.qdrant_client.query_points(
                collection_name=QDRANT_COLLECTION,
                query=dense_vector,
                query_filter=models.Filter(
                    must=[models.FieldCondition(
                        key="sessionId",
                        match=models.MatchValue(value=str(session_id))  # 强制转换为字符串
                    )]
                ),
                limit=top_k,
                with_payload=True
            )
            logger.info(f"🔹 稠密搜索返回 {len(dense_results.points)} 条结果")

            result_dict = {}
            for point in dense_results.points:
                point_id = point.id
                # dense 分数按 HYBRID_DENSE_BASE_WEIGHT 倍作为"基础分"（保持原值），便于之后调 dense 权重
                base_dense = point.score * HYBRID_DENSE_BASE_WEIGHT
                result_dict[point_id] = {
                    "content": point.payload.get("content", ""),
                    "type": point.payload.get("type", "FACTS"),
                    "importance_score": point.payload.get("importance_score", 0.5),
                    "entities": point.payload.get("entities", []),
                    "dense_score": point.score,
                    "score": base_dense,
                }

            if keywords:
                logger.info(f"🔹 执行BM25关键词搜索, 关键词数量={len(keywords)}")
                for keyword in keywords[:BM25_LOG_KEYWORDS_TOP_N]:
                    keyword_results = self.qdrant_client.query_points(
                        collection_name=QDRANT_COLLECTION,
                        query=dense_vector,
                        query_filter=models.Filter(
                            must=[
                                models.FieldCondition(
                                    key="sessionId",
                                    match=models.MatchValue(value=str(session_id))  # 强制转换为字符串
                                ),
                                models.FieldCondition(
                                    key="bm25_keywords",
                                    match=models.MatchAny(any=[keyword])
                                )
                            ]
                        ),
                        limit=top_k,
                        with_payload=True
                    )
                    logger.debug(f"关键词 '{keyword}' 返回 {len(keyword_results.points)} 条结果")

                    for point in keyword_results.points:
                        point_id = point.id
                        if point_id not in result_dict:
                            result_dict[point_id] = {
                                "content": point.payload.get("content", ""),
                                "type": point.payload.get("type", "FACTS"),
                                "importance_score": point.payload.get("importance_score", 0.5),
                                "entities": point.payload.get("entities", []),
                                "dense_score": 0,
                                "score": 0,
                            }
                        # BM25 贡献分 = point.score * bm25_keyword_weight * HYBRID_BM25_WEIGHT
                        result_dict[point_id]["score"] += (
                            point.score * bm25_scores[keyword] * HYBRID_BM25_WEIGHT
                        )

            # 重要性加权：importance_score × HYBRID_IMPORTANCE_WEIGHT（原硬编码 0.1）
            for point_id in result_dict:
                result_dict[point_id]["score"] += (
                    result_dict[point_id].get("importance_score", 0.5) * HYBRID_IMPORTANCE_WEIGHT
                )

            sorted_results = sorted(result_dict.values(), key=lambda x: x["score"], reverse=True)[:top_k]
            logger.info(f"🔹 混合搜索合并 {len(result_dict)} 条唯一结果, 过滤后保留 {len(sorted_results)} 条")

            if self.rerank_client and sorted_results:
                logger.info("🔹 使用交叉编码器重排序...")
                sorted_results = await self._rerank(query, sorted_results, top_k)
            else:
                logger.info("🔹 跳过重排序(没有重排序客户端或没有结果)")

            logger.info(f"✅ 记忆检索完成: {len(sorted_results)} 条结果")
            for i, result in enumerate(sorted_results[:3], 1):
                logger.info(f"  结果 #{i}: '{result['content'][:60]}...' (分数={result['score']:.4f})")

            return sorted_results
        except Exception as e:
            logger.error(f"❌ 记忆检索失败: {e}")
            return []

    async def _rerank(self, query: str, results: List[Dict[str, Any]], top_k: int) -> List[Dict[str, Any]]:
        """
        使用交叉编码器对检索结果进行重排序
        :param query: 查询文本
        :param results: 初步检索结果列表
        :param top_k: 返回结果数量
        :return: 重排序后的结果列表
        """
        if not results or not self.rerank_client:
            return results

        try:
            documents = [item["content"] for item in results]

            response = await self.rerank_client.post(
                "/reranks",
                body={
                    "model": self.rerank_model,
                    "query": query,
                    "documents": documents,
                    "top_n": top_k
                },
                cast_to=object
            )

            if hasattr(response, 'to_dict'):
                response_data = response.to_dict()
            else:
                response_data = dict(response)

            rerank_results = response_data.get("results", [])

            for i, item in enumerate(results):
                item["rerank_score"] = 0.0

            for rerank_item in rerank_results:
                index = rerank_item.get("index")
                score = rerank_item.get("score", 0.0)
                if isinstance(index, int) and 0 <= index < len(results):
                    results[index]["rerank_score"] = float(score)

            results.sort(key=lambda x: x.get("rerank_score", 0), reverse=True)
            logger.debug(f"重排序完成: {len(results)} 条结果")
            return results[:top_k]
        except Exception as e:
            logger.error(f"重排序失败: {e}")
            return results

    async def async_extract_and_store(self, user_message: str, assistant_message: str,
                                      user_id: int, session_id: str = None, existing_memories: List[str] = None):
        """
        异步提取记忆并存储（线程池执行）
        :param user_message: 用户消息
        :param assistant_message: 助手回复
        :param user_id: 用户ID
        :param session_id: 会话ID
        :param existing_memories: 已有记忆列表
        """
        try:
            memory_units = await self.extract_memory_units(
                user_message, assistant_message, user_id, session_id, existing_memories
            )
            if memory_units:
                await self.store_memory(memory_units)
        except Exception as e:
            logger.error(f"异步记忆提取和存储失败: {e}")

    def cleanup_orphan_points(self, alive_session_ids: List) -> int:
        """
        【定时孤儿清理-Qdrant层】清理会话已被删除但向量点还残留的孤儿记忆点。

        执行流程：
          1. 将 alive_session_ids 转成 Set[str] 方便 O(1) 差集判断（注意 Qdrant payload 的 sessionId 都是字符串）
          2. 使用 qdrant_client.scroll 增量迭代整个 collection（不 fetch vectors，只带 payload 省网络）
          3. 每批点：若 point.payload.sessionId 不在 alive_ids_set 内，就是孤儿点，收集 point.id
          4. 孤儿点累积到 ORPHAN_DELETE_BATCH(500) 个就执行一次 delete，避免一次请求过大
          5. scroll 完后，把不足一批的尾巴再 flush 一次 delete

        :param alive_session_ids: 存活会话 ID 列表（元素可以是 int/str，内部统一转 str）
        :return: 实际删除的 Qdrant 向量点总数
        """
        if not self._initialized:
            self.init()
        client = self.qdrant_client

        # alive_ids_set：统一为字符串（与 payload 里的 sessionId 类型严格匹配，避免 int/str 比较永远 False）
        alive_ids_set: set = set()
        for sid in alive_session_ids or []:
            if sid is None:
                continue
            alive_ids_set.add(str(sid))

        total_deleted = 0
        orphan_ids: List[Any] = []
        # 一批累积到 500 个就执行删除（Qdrant gRPC/HTTP 单包体积安全阈值）
        ORPHAN_DELETE_BATCH = 500

        logger.info(f"[Qdrant孤儿清理] 开始：存活会话数={len(alive_ids_set)}, scroll collection={QDRANT_COLLECTION}")

        def _flush_orphans() -> int:
            """内部函数：把 orphan_ids 累积的孤儿点执行一次 delete，返回本次删除数"""
            nonlocal orphan_ids
            if not orphan_ids:
                return 0
            batch = orphan_ids
            orphan_ids = []
            try:
                result = client.delete(
                    collection_name=QDRANT_COLLECTION,
                    points_selector=models.PointIdsList(points=batch),
                )
                # qdrant_client 不同版本返回结构有差异，安全兼容多种写法
                cnt = 0
                if hasattr(result, "count") and isinstance(result.count, int):
                    cnt = result.count
                elif hasattr(result, "status"):
                    # 新版 API 可能返回 operation_id，用 len(batch) 近似
                    cnt = len(batch)
                else:
                    cnt = len(batch)
                logger.info(f"[Qdrant孤儿清理] 批量删除孤儿点 {len(batch)}/{cnt} 个")
                return cnt
            except Exception as e:
                logger.error(f"[Qdrant孤儿清理] 批量删除失败: batch_size={len(batch)}, 错误={e}")
                return 0

        try:
            offset = None
            scroll_batch_size = 500
            # scroll 迭代（order_by=None / with_payload=True / with_vectors=False）
            while True:
                records, next_offset = client.scroll(
                    collection_name=QDRANT_COLLECTION,
                    limit=scroll_batch_size,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                if not records:
                    break
                for rec in records:
                    payload = rec.payload or {}
                    sid = payload.get("sessionId")
                    if sid is None:
                        # 没有 sessionId 的点也视为孤儿（不合法数据）
                        orphan_ids.append(rec.id)
                        continue
                    sid_str = str(sid)
                    if sid_str not in alive_ids_set:
                        orphan_ids.append(rec.id)
                # 累积够一批就 flush
                if len(orphan_ids) >= ORPHAN_DELETE_BATCH:
                    total_deleted += _flush_orphans()
                # scroll 终止条件：next_offset 为 None/空
                if next_offset is None:
                    break
                offset = next_offset
            # flush 尾批
            total_deleted += _flush_orphans()
            logger.info(f"[Qdrant孤儿清理] 完成：总删除点数={total_deleted}, 存活会话数={len(alive_ids_set)}")
            return total_deleted
        except Exception as e:
            # 出异常前也尽量 flush 已收集的孤儿点，避免下一次重算
            tail_cnt = _flush_orphans()
            logger.error(f"[Qdrant孤儿清理] scroll异常: 已累计删除={total_deleted + tail_cnt}, 错误={e}")
            return total_deleted + tail_cnt


memory_service = MemoryService()