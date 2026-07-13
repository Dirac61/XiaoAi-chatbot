import asyncio
import hashlib
import logging
import re
from collections import Counter
from typing import List, Optional, Dict, Any

import numpy as np
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
        if self._initialized:
            return

        self.qdrant_client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
        self._init_embedding_client()
        self._create_collection_if_not_exists()
        self._init_rerank_client()
        self._init_extraction_client()
        self._initialized = True
        logger.info("MemoryService初始化成功")

    def _init_embedding_client(self):
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
            logger.info(f"使用API嵌入模型: {EMBEDDING_MODEL}, 维度={self.embedding_dim}")
        else:
            self.embedding_client = None
            self.embedding_model = None
            self.embedding_dim = 384
            logger.warning("未配置嵌入API密钥")

    def _init_rerank_client(self):
        if RERANK_API_KEY:
            base_url = RERANK_API_BASE if RERANK_API_BASE else API_BASE
            if "/compatible-api/v1" not in base_url:
                base_url = base_url.replace("/compatible-mode/v1", "/compatible-api/v1")
            self.rerank_client = AsyncOpenAI(
                api_key=RERANK_API_KEY,
                base_url=base_url
            )
            self.rerank_model = RERANK_MODEL
            logger.info(f"使用API重排序模型: {RERANK_MODEL}")
        else:
            self.rerank_client = None
            self.rerank_model = None
            logger.info("未配置重排序API密钥，跳过重排序")

    def _init_extraction_client(self):
        if EXTRACTION_MODEL and EXTRACTION_API_KEY:
            self.extraction_client = AsyncOpenAI(
                api_key=EXTRACTION_API_KEY,
                base_url=EXTRACTION_API_BASE if EXTRACTION_API_BASE else API_BASE
            )
            self.extraction_model = EXTRACTION_MODEL
            logger.info(f"使用独立的记忆提取模型: {EXTRACTION_MODEL}")
        else:
            self.extraction_client = None
            self.extraction_model = None
            logger.info("未配置独立的记忆提取模型，将使用主模型")

    def _create_collection_if_not_exists(self):
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
                logger.info(f"创建Qdrant集合: {QDRANT_COLLECTION}, dense_dim={self.embedding_dim}")
            else:
                logger.info(f"Qdrant集合已存在: {QDRANT_COLLECTION}")
        except Exception as e:
            logger.error(f"创建/验证Qdrant集合失败: {e}")

    def _tokenize(self, text: str) -> List[str]:
        text = text.lower()
        tokens = re.findall(r'[a-zA-Z]+|[一-龥]+|\d+', text)
        return [t for t in tokens if len(t) >= 2]

    def _calculate_bm25(self, text: str) -> Dict[str, float]:
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
                                   user_id: int, session_id: int = None, existing_memories: List[str] = None) -> List[Dict[str, Any]]:
        messages_text = f"User: {user_message}\nAssistant: {assistant_message}"

        system_prompt = """你是一个专业的记忆提取助手。请从对话中提取关键信息作为长期记忆。

记忆类型：
- FACTS：客观事实、知识
- PREFERENCES：用户偏好、喜好
- ENTITY：重要实体、人物、地点
- RELATION：实体之间的关系
- EVENT：事件、经历

提取要求：
1. 只提取本轮对话的重点，不要重复已有记忆
2. 每条记忆内容简洁（50-100字）
3. 评估重要性分数（0-1）
4. 列出涉及的实体
5. 输出严格的JSON格式

输出格式示例：
[
  {"content": "用户喜欢川菜", "type": "PREFERENCES", "importance_score": 0.8, "entities": ["川菜"]}
]"""

        user_prompt = f"""对话内容：
{messages_text}

已有记忆：
{existing_memories if existing_memories else "无"}

请提取本轮对话的关键记忆。"""

        try:
            if self.extraction_client and self.extraction_model:
                client = self.extraction_client
                model = self.extraction_model
            else:
                client = AsyncOpenAI(api_key=API_KEY, base_url=API_BASE)
                model = "qwen3.7-plus"

            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3,
                max_tokens=500
            )

            if response.choices and response.choices[0].message and response.choices[0].message.content:
                content = response.choices[0].message.content.strip()
                import json
                try:
                    memory_units = json.loads(content)
                    if isinstance(memory_units, list):
                        for unit in memory_units:
                            unit["userId"] = user_id
                            unit["sessionId"] = session_id
                            unit["timestamp"] = int(asyncio.get_event_loop().time())
                        logger.info(f"提取到 {len(memory_units)} 个记忆单元, user_id={user_id}, session_id={session_id}")
                        return memory_units
                except json.JSONDecodeError:
                    logger.warning(f"解析记忆提取响应失败: {content[:200]}")
            return []
        except Exception as e:
            logger.error(f"记忆提取失败: {e}")
            return []

    async def store_memory(self, memory_units: List[Dict[str, Any]]):
        if not memory_units:
            logger.debug("没有记忆单元需要存储")
            return

        logger.info(f"开始存储 {len(memory_units)} 个记忆单元")
        points = []
        
        for idx, unit in enumerate(memory_units):
            content = unit.get("content", "")
            if not content:
                logger.debug(f"跳过空记忆单元 #{idx}")
                continue

            logger.debug(f"处理记忆单元 #{idx}: '{content[:50]}...'")
            
            dense_vector = await self.generate_embedding(content)
            if dense_vector is None:
                logger.error(f"记忆单元 #{idx} 生成嵌入向量失败, 跳过")
                continue

            logger.debug(f"计算BM25稀疏向量...")
            bm25_scores = self._calculate_bm25(content)
            logger.debug(f"BM25关键词: {list(bm25_scores.keys())[:5]}, 分数: {list(bm25_scores.values())[:5]}")

            payload = {
                "userId": unit.get("userId", 0),
                "sessionId": unit.get("sessionId", 0),
                "content": content,
                "type": unit.get("type", "FACTS"),
                "importance_score": unit.get("importance_score", 0.5),
                "entities": unit.get("entities", []),
                "timestamp": unit.get("timestamp", 0),
                "bm25_keywords": list(bm25_scores.keys())[:10]
            }

            point_id = abs(hash(content + str(unit.get("userId", 0)))) % (10 ** 18)

            points.append(models.PointStruct(
                id=point_id,
                vector=dense_vector,
                payload=payload
            ))
            logger.info(f"记忆单元 #{idx} 准备存储: dense_dim={len(dense_vector)}, bm25_keywords={len(bm25_scores)}, id={point_id}")

        if points:
            try:
                logger.info(f"向Qdrant集合 {QDRANT_COLLECTION} 写入 {len(points)} 个点")
                result = self.qdrant_client.upsert(
                    collection_name=QDRANT_COLLECTION,
                    points=points
                )
                logger.info(f"✅ 成功存储 {len(points)} 个记忆点到Qdrant")
                logger.info(f"📊 存储详情: dense_dim={self.embedding_dim}, BM25关键词已存储到payload")
                
                collection_info = self.qdrant_client.get_collection(QDRANT_COLLECTION)
                logger.info(f"📊 Qdrant集合统计: total_points={collection_info.points_count}")
            except Exception as e:
                logger.error(f"❌ 存储记忆失败: {e}")
        else:
            logger.warning("处理后没有有效的记忆点需要存储")

    async def search_memories(self, query: str, session_id: int, top_k: int = 10) -> List[Dict[str, Any]]:
        if not self.embedding_client:
            logger.warning("嵌入客户端未初始化, 跳过记忆检索")
            return []

        logger.info(f"🔍 开始记忆检索, session_id={session_id}, 查询='{query[:50]}...', top_k={top_k}")

        dense_vector = await self.generate_embedding(query)
        if dense_vector is None:
            logger.error("❌ 查询向量生成失败, 跳过检索")
            return []
        logger.debug(f"查询向量生成成功, 维度={len(dense_vector)}")

        bm25_scores = self._calculate_bm25(query)
        keywords = list(bm25_scores.keys())
        logger.debug(f"BM25关键词提取: {keywords[:5]}")

        try:
            logger.info("🔹 执行稠密向量搜索...")
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
            logger.info(f"稠密搜索返回 {len(dense_results.points)} 条结果")

            result_dict = {}
            for rank, point in enumerate(dense_results.points, 1):
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
                logger.info(f"🔹 执行BM25关键词搜索, 关键词数量={len(keywords[:5])}...")
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
                                    key="content",
                                    match=models.MatchText(text=keyword)
                                )
                            ]
                        ),
                        limit=top_k,
                        with_payload=True
                    )
                    logger.debug(f"关键词 '{keyword}' 返回 {len(keyword_results.points)} 条结果")

                    for rank, point in enumerate(keyword_results.points, 1):
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

            logger.info("🔹 应用重要性分数提升...")
            for point_id in result_dict:
                result_dict[point_id]["score"] += result_dict[point_id].get("importance_score", 0.5) * 0.1

            sorted_results = sorted(result_dict.values(), key=lambda x: x["score"], reverse=True)[:top_k]
            logger.info(f"🔹 混合搜索合并 {len(result_dict)} 条唯一结果, 过滤后保留 {len(sorted_results)} 条")

            if self.rerank_client and sorted_results:
                logger.info("🔹 使用交叉编码器重排序...")
                sorted_results = await self._rerank(query, sorted_results, top_k)
                logger.info(f"重排序完成, {len(sorted_results)} 条结果")
            else:
                logger.info("跳过重排序(没有重排序客户端或没有结果)")

            logger.info(f"✅ 记忆检索完成: {len(sorted_results)} 条结果")
            for i, result in enumerate(sorted_results[:3], 1):
                logger.info(f"  结果 #{i}: '{result['content'][:60]}...' (分数={result['score']:.4f})")
            
            return sorted_results
        except Exception as e:
            logger.error(f"❌ 记忆检索失败: {e}")
            return []

    async def _rerank(self, query: str, results: List[Dict[str, Any]], top_k: int) -> List[Dict[str, Any]]:
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
            logger.debug(f"使用API重排序 {len(results)} 条结果")
            return results[:top_k]
        except Exception as e:
            logger.error(f"重排序失败: {e}")
            return results

    async def async_extract_and_store(self, user_message: str, assistant_message: str,
                                      user_id: int, session_id: int = None, existing_memories: List[str] = None):
        try:
            memory_units = await self.extract_memory_units(
                user_message, assistant_message, user_id, session_id, existing_memories
            )
            if memory_units:
                await self.store_memory(memory_units)
        except Exception as e:
            logger.error(f"异步记忆提取和存储失败: {e}")


memory_service = MemoryService()