# -*- coding: utf-8 -*-
"""
MCP 市场元数据注册表。
Phase 1：从本地 marketplace.json 读取。
Phase 2：从独立 Registry 服务 HTTP 拉取，每小时刷新。
"""
import os
import json
import time
import logging
from typing import List, Optional

from mcp.models import McpMeta

logger = logging.getLogger(__name__)

# 市场数据文件路径
_MARKETPLACE_PATH = os.path.join(os.path.dirname(__file__), "marketplace.json")


class McpRegistry:
    """MCP 市场元数据注册表（单例）。
    负责加载和缓存所有可用 MCP 的元数据。
    """

    _cache: List[McpMeta] = []
    _last_refresh: float = 0.0
    _refresh_interval_s: int = 3600  # 每小时刷新一次

    @classmethod
    async def load(cls):
        """Agent 启动时加载市场数据（Phase 1：读本地 JSON）"""
        await cls._load_from_local()
        logger.info(f"[MCP][市场] 加载完成，共 {len(cls._cache)} 个 MCP 插件")

    @classmethod
    async def _load_from_local(cls):
        """从本地 marketplace.json 加载"""
        if not os.path.exists(_MARKETPLACE_PATH):
            logger.warning(f"[MCP][市场] 市场数据文件不存在: {_MARKETPLACE_PATH}")
            return
        with open(_MARKETPLACE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        cls._cache = [McpMeta.from_dict(mcp) for mcp in data.get("mcps", [])]
        cls._last_refresh = time.time()

    @classmethod
    def list_all(cls, category: Optional[str] = None, keyword: Optional[str] = None) -> List[dict]:
        """浏览市场（支持分类/搜索），返回前端可直接用的字典列表"""
        result = cls._cache
        if category:
            result = [m for m in result if m.category == category]
        if keyword:
            kw = keyword.lower()
            result = [m for m in result if kw in m.name.lower() or kw in m.description.lower()]
        return [cls._meta_to_dict(m) for m in result]

    @classmethod
    def get(cls, mcp_id: str) -> Optional[McpMeta]:
        """获取单个 MCP 元数据"""
        for m in cls._cache:
            if m.mcp_id == mcp_id:
                return m
        return None

    @classmethod
    def get_detail(cls, mcp_id: str) -> Optional[dict]:
        """获取单个 MCP 详情（前端用）"""
        m = cls.get(mcp_id)
        if not m:
            return None
        return cls._meta_to_dict(m)

    @staticmethod
    def _meta_to_dict(m: McpMeta) -> dict:
        """将 McpMeta 转为前端可用的字典"""
        return {
            "mcp_id": m.mcp_id,
            "name": m.name,
            "version": m.version,
            "author": m.author,
            "category": m.category,
            "description": m.description,
            "icon": m.icon,
            "homepage": m.homepage,
            "risk_level": m.risk_level,
            "transport_type": m.transport.type if m.transport else "unknown",
            "env_template": [
                {"key": f.key, "label": f.label, "required": f.required,
                 "type": f.type, "help": f.help}
                for f in (m.transport.env_template if m.transport else [])
            ],
            "tools": [
                {"name": t.name, "description": t.description, "params_template": t.params_template}
                for t in m.tools
            ]
        }


# 全局单例
mcp_registry = McpRegistry()
