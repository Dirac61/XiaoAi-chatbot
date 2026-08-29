import json
import logging
import httpx
from typing import List, Dict, Optional

from config.settings import (
    SEARCH_API_KEY, SEARCH_API_BASE,
    SEARCH_MAX_RESULTS, SEARCH_MAX_CONTENT_LENGTH
)
# 行为参数（HTTP 超时/搜索上下文模板等）统一放到 config.behavior / config.tools
from config.behavior import SEARCH_HTTP_TIMEOUT
from config.tools import SEARCH_CONTEXT_ITEM_TEMPLATE

logger = logging.getLogger("XiaoAi Search Service")


class SearchService:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    async def web_search(self, keywords: List[str], max_results: int = None) -> List[Dict[str, str]]:
        """
        调用博查搜索API获取搜索结果。
        【硬编码移除】
          - HTTP 超时 30.0 → config.behavior.SEARCH_HTTP_TIMEOUT
          - freshness/count/summary 等协议字段留为业务常量（无需可配置，保持稳定）
        :param keywords: 搜索关键词列表
        :param max_results: 最大返回结果数，默认使用配置值
        :return: 搜索结果列表，每项包含title、url、content字段
        """
        if not SEARCH_API_KEY or not SEARCH_API_BASE:
            logger.info("未配置博查搜索API，跳过联网搜索")
            return []

        if not keywords or len(keywords) == 0:
            logger.info("搜索关键词为空，跳过联网搜索")
            return []

        max_results = max_results or SEARCH_MAX_RESULTS
        query = " ".join(keywords)
        
        logger.info(f"开始博查联网搜索: query='{query}', max_results={max_results}")

        try:
            # 【硬编码移除】HTTP 超时统一用 SEARCH_HTTP_TIMEOUT（原来 hardcode 为 30.0）
            async with httpx.AsyncClient(timeout=SEARCH_HTTP_TIMEOUT) as client:
                response = await client.post(
                    SEARCH_API_BASE,
                    headers={
                        "Authorization": f"Bearer {SEARCH_API_KEY}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "query": query,
                        "summary": True,
                        "freshness": "noLimit",
                        "count": max_results
                    }
                )
                
                response.raise_for_status()
                data = response.json()
                
                # 博查API响应结构：webPages.value 数组
                web_pages = data.get("webPages", {})
                # 兼容部分返回data外层包裹的情况
                if not web_pages and "data" in data:
                    web_pages = data.get("data", {}).get("webPages", {})
                
                value_list = web_pages.get("value", [])
                
                results = []
                for item in value_list[:max_results]:
                    title = item.get("name", "")
                    url = item.get("url", "")
                    # 优先使用summary（长文本摘要），其次用snippet（简短摘要）
                    content = item.get("summary", "") or item.get("snippet", "")
                    content = content[:SEARCH_MAX_CONTENT_LENGTH]
                    
                    if title and url:
                        results.append({
                            "title": title,
                            "url": url,
                            "content": content
                        })
                
                logger.info(f"博查搜索完成: 返回 {len(results)} 条结果")
                return results
                
        except httpx.HTTPError as e:
            logger.error(f"博查搜索HTTP错误: {e}")
            return []
        except json.JSONDecodeError as e:
            logger.error(f"博查搜索响应解析失败: {e}")
            return []
        except Exception as e:
            logger.error(f"博查搜索异常: {e}")
            return []

    async def get_search_context(self, keywords: List[str], max_results: int = None) -> str:
        """
        获取搜索结果的上下文文本，用于传递给Chat模型。
        【硬编码移除】
          - 每条搜索结果拼接模板 "【搜索结果{i}】标题: ...\n内容: ..." → config.tools.SEARCH_CONTEXT_ITEM_TEMPLATE
        :param keywords: 搜索关键词列表
        :param max_results: 最大返回结果数
        :return: 搜索结果拼接成的上下文文本
        """
        results = await self.web_search(keywords, max_results)
        
        if not results:
            return ""
        
        context_parts = []
        for i, item in enumerate(results, 1):
            content = item.get("content", "")
            if content:
                # 统一从模板生成条目（原 f"【搜索结果{i}】标题: {item['title']}\n内容: {content}"）
                context_parts.append(SEARCH_CONTEXT_ITEM_TEMPLATE.format(
                    index=i, title=item["title"], content=content
                ))
        
        return "\n\n".join(context_parts)


search_service = SearchService()