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

logger = logging.getLogger("XiaoAi Memory Service")


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
        中英文分词，使用jieba处理中文，正则处理英文，过滤停用词
        :param text: 输入文本
        :return: 分词结果列表
        """
        text = text.lower()
        
        chinese_tokens = jieba.lcut(text)
        
        english_tokens = re.findall(r'[a-zA-Z]+', text)
        
        stopwords = {'的', '了', '是', '在', '我', '有', '和', '就', '不', '人', '都', '一', '一个', '上', '也', '很', '到', '说', '要', '去', '你', '会', '着', '没有', '看', '好', '自己', '这', '那', '那是', '但是', '所以', '因为', '如果', '虽然', '但是', '而且', '或者', '还是', '的话', '吗', '呢', '啊', '哦', '嗯', '吧', '呀', '哇', '哈', '嘿', '哼', '唉', '咦', '嗯', '唔', '哦'}
        
        tokens = []
        for token in chinese_tokens:
            if len(token) >= 2 and token not in stopwords:
                tokens.append(token)
        
        for token in english_tokens:
            if len(token) >= 2 and token.lower() not in stopwords:
                tokens.append(token.lower())
        
        return tokens

    def _calculate_bm25(self, text: str) -> Dict[str, float]:
        """
        计算BM25关键词分数，基于TF（词频）和简化的IDF
        :param text: 输入文本
        :return: 关键词及其分数的字典
        """
        tokens = self._tokenize(text)
        token_counts = Counter(tokens)
        max_freq = max(token_counts.values()) if token_counts else 1

        k1 = 1.2
        b = 0.75

        scores = {}
        for token, count in token_counts.items():
            tf = (count * (k1 + 1)) / (count + k1 * (1 - b + b * len(tokens) / 100))
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
        从对话中提取记忆单元，调用记忆提取模型进行语义分析
        :param user_message: 用户消息
        :param assistant_message: 助手回复
        :param user_id: 用户ID
        :param session_id: 会话ID
        :param existing_memories: 已有记忆列表（用于去重参考）
        :return: 提取的记忆单元列表
        """
        messages_text = f"User: {user_message}\nAssistant: {assistant_message}"
        logger.debug(f"开始记忆提取: user_id={user_id}, session_id={session_id}, message='{user_message[:50]}...'")

        system_prompt = """你是一个专业的记忆提取助手，负责从用户与AI助手爱尔奎特的对话中提取长期记忆。

【记忆类型定义】
- FACTS：客观事实、知识、数据、属性（如：用户是程序员、身高180cm、图片中的文字内容）
- PREFERENCES：用户偏好、喜好、厌恶、习惯（如：喜欢川菜、讨厌香菜、喜欢猫）
- ENTITY：重要实体、人物、地点、事物（如：父母、北京、iPhone、图片中的关键对象）
- RELATION：实体之间的关系（如：用户是小明的同事、公司在上海）
- EVENT：事件、经历、计划、目标（如：下周去旅游、昨天看电影、图片中的场景）
- NEEDS：用户需求、意图、问题、关注点（如：用户想了解微信、用户有问题要问）

【提取规则】
1. 提取本轮对话中用户提到的任何有用信息，不要重复已有记忆列表中的内容
2. 每条记忆内容简洁（10-60字），使用陈述句，不改变原意
3. 重要性评分标准：
   - 0.8-1.0：核心信息（用户身份、长期偏好、重要事件、核心需求）
   - 0.5-0.7：有用信息（短期偏好、次要事实、次要需求）
   - 0.1-0.4：边缘信息（临时想法、无关细节）
4. 实体提取：列出记忆内容中涉及的关键名词，用中文，不超过5个
5. 以下情况也要提取：用户提到的事物、表达的兴趣、提出的问题、表达的情感
6. 只有纯问候语（如"你好"、"再见"）才输出空数组
7. 对话中标注为[图片内容]的部分代表用户上传图片的视觉信息，应提取为FACTS或ENTITY类型记忆
8. 从图片中提取的信息包括：图片中的文字内容、图片描述的对象/场景、图片展示的关键信息

【高质量记忆示例】

示例1：
对话内容：
User: 我是一名Java后端开发，平时喜欢吃川菜，特别喜欢麻辣火锅
Assistant: 原来如此，Java后端开发是个不错的职业呢，川菜确实很美味

提取结果：
[
  {"content": "用户是一名Java后端开发工程师", "type": "FACTS", "importance_score": 0.9, "entities": ["Java", "后端开发"]},
  {"content": "用户喜欢吃川菜，尤其喜欢麻辣火锅", "type": "PREFERENCES", "importance_score": 0.85, "entities": ["川菜", "麻辣火锅"]}
]

示例2：
对话内容：
User: [用户提问]这张照片里是什么？[图片内容]图片显示一只白色的猫坐在沙发上，背景是灰色的墙壁，猫看起来很放松
Assistant: 这是一只白色的猫咪，看起来很可爱

提取结果：
[
  {"content": "用户上传了一张白色猫咪坐在沙发上的照片", "type": "FACTS", "importance_score": 0.6, "entities": ["猫咪", "沙发"]},
  {"content": "用户可能喜欢猫", "type": "PREFERENCES", "importance_score": 0.55, "entities": ["猫"]}
]

示例3：
对话内容：
User: [用户提问]帮我看看这段代码有什么问题？[图片内容]图片显示一段Python代码，定义了一个名为calculate的函数，使用了Java的语法结构，有语法错误
Assistant: 这段代码使用了Java的语法写Python，需要修改

提取结果：
[
  {"content": "用户正在学习Python编程", "type": "FACTS", "importance_score": 0.7, "entities": ["Python", "编程"]},
  {"content": "用户遇到了Python代码语法错误", "type": "NEEDS", "importance_score": 0.65, "entities": ["代码", "语法"]}
]

示例4：
对话内容：
User: [用户提问]这是我家的风景照[图片内容]图片显示一片美丽的海滩，蓝色的大海和白色的沙滩，远处有椰子树
Assistant: 你的家乡风景真美

提取结果：
[
  {"content": "用户家乡有美丽的海滩风景", "type": "FACTS", "importance_score": 0.75, "entities": ["海滩", "家乡"]},
  {"content": "用户喜欢海滩风景", "type": "PREFERENCES", "importance_score": 0.5, "entities": ["海滩"]}
]

示例5：
对话内容：
User: 我下周要去杭州旅游，和女朋友小红一起
Assistant: 杭州是个很美的城市，祝你们玩得开心

提取结果：
[
  {"content": "用户计划下周末和女朋友去杭州旅游", "type": "EVENT", "importance_score": 0.75, "entities": ["杭州", "旅游"]},
  {"content": "用户的女朋友叫小红", "type": "ENTITY", "importance_score": 0.8, "entities": ["小红"]}
]

示例6：
对话内容：
User: 你好
Assistant: 你好

提取结果：
[]

【输出要求】
- 必须输出严格的JSON数组格式，不要包含任何其他文字
- 确保JSON格式正确，逗号、引号、括号配对完整
- 如果没有可提取的记忆，输出空数组：[]"""

        media_count = messages_text.count("[图片内容]") + messages_text.count("[文件内容]")
        max_memory_count = max(5, 3 + media_count)
        max_content_length = 80

        user_prompt = f"""对话内容：
{messages_text}

已有记忆：
{existing_memories if existing_memories else "无"}

约束条件：
- 每条记忆内容长度不超过{max_content_length}字
- 提取的记忆数量不超过{max_memory_count}条

请提取本轮对话的关键记忆。"""

        try:
            if self.extraction_client and self.extraction_model:
                client = self.extraction_client
                model = self.extraction_model
            else:
                client = AsyncOpenAI(api_key=API_KEY, base_url=API_BASE)
                model = "qwen3.7-plus"

            memory_units = await self._extract_with_retry(client, model, system_prompt, user_prompt, messages_text, user_id, session_id, max_memory_count, max_content_length)
            return memory_units
        except Exception as e:
            logger.error(f"记忆提取失败: {e}")
            return []

    async def _extract_with_retry(self, client, model, system_prompt, user_prompt, messages_text, user_id, session_id: str, max_memory_count, max_content_length):
        """
        带重试的记忆提取，格式校验失败时重试一次
        """
        max_retries = 2
        for attempt in range(1, max_retries + 1):
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3,
                max_tokens=2000
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
                user_prompt = f"""对话内容：
{messages_text}

已有记忆：
无

约束条件：
- 每条记忆内容长度不超过{max_content_length}字
- 提取的记忆数量不超过{max_memory_count}条
- 必须输出严格的JSON数组格式，不要包含任何其他文字

请重新提取本轮对话的关键记忆。"""
        
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
                        match=models.MatchValue(value=session_id)
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
        failed_embedding = 0
        
        for idx, unit in enumerate(memory_units):
            content = unit.get("content", "")
            if not content:
                logger.debug(f"跳过空记忆单元 #{idx}")
                continue

            user_id = unit.get("userId", 0)
            session_id = unit.get("sessionId", 0)
            
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
                "sessionId": session_id,
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
                logger.info(f"📊 去重统计: 字面去重跳过={skipped_literal}, 向量去重跳过={skipped_vector}, 嵌入失败={failed_embedding}")
            except Exception as e:
                logger.error(f"❌ 存储记忆失败: {e}")
        else:
            logger.warning(f"📥 处理后没有有效的记忆点需要存储(字面去重={skipped_literal}, 向量去重={skipped_vector}, 嵌入失败={failed_embedding})")

    async def search_memories(self, query: str, session_id: str, top_k: int = 10) -> List[Dict[str, Any]]:
        """
        混合搜索记忆：稠密向量搜索 + BM25关键词搜索 + 重要性分数融合 + Rerank重排序
        :param query: 查询文本
        :param session_id: 会话ID
        :param top_k: 返回结果数量
        :return: 排序后的记忆结果列表
        """
        if not self.embedding_client:
            logger.warning("嵌入客户端未初始化, 跳过记忆检索")
            return []

        logger.info(f"🔍 开始记忆检索, session_id={session_id}, 查询='{query[:50]}...', top_k={top_k}")

        dense_vector = await self.generate_embedding(query)
        if dense_vector is None:
            logger.error("❌ 查询向量生成失败, 跳过检索")
            return []

        bm25_scores = self._calculate_bm25(query)
        keywords = list(bm25_scores.keys())
        logger.debug(f"BM25关键词提取: {keywords[:5]}")

        try:
            dense_results = self.qdrant_client.query_points(
                collection_name=QDRANT_COLLECTION,
                query=dense_vector,
                query_filter=models.Filter(
                    must=[models.FieldCondition(
                        key="sessionId",
                        match=models.MatchValue(value=session_id)
                    )]
                ),
                limit=top_k,
                with_payload=True
            )
            logger.info(f"🔹 稠密搜索返回 {len(dense_results.points)} 条结果")

            result_dict = {}
            for point in dense_results.points:
                point_id = point.id
                result_dict[point_id] = {
                    "content": point.payload.get("content", ""),
                    "type": point.payload.get("type", "FACTS"),
                    "importance_score": point.payload.get("importance_score", 0.5),
                    "entities": point.payload.get("entities", []),
                    "dense_score": point.score,
                    "score": point.score
                }

            if keywords:
                logger.info(f"🔹 执行BM25关键词搜索, 关键词数量={len(keywords)}")
                for keyword in keywords[:5]:
                    keyword_results = self.qdrant_client.query_points(
                        collection_name=QDRANT_COLLECTION,
                        query=dense_vector,
                        query_filter=models.Filter(
                            must=[
                                models.FieldCondition(
                                    key="sessionId",
                                    match=models.MatchValue(value=session_id)
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
                                "score": 0
                            }
                        result_dict[point_id]["score"] += point.score * bm25_scores[keyword] * 0.3

            for point_id in result_dict:
                result_dict[point_id]["score"] += result_dict[point_id].get("importance_score", 0.5) * 0.1

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


memory_service = MemoryService()