# -*- coding: utf-8 -*-
"""
MCP 动态工具注册器。
根据用户已安装的 MCP，实时构建工具列表注入编排器 system prompt。
"""
import logging
from typing import List

from mcp.client_pool import mcp_client_pool
from mcp.models import ToolDesc
from config.tools import build_tool_description_line

logger = logging.getLogger(__name__)


class McpToolRegistry:
    """动态工具注册表。
    根据用户已安装的 MCP，实时构建工具列表。
    编排器 system prompt 里的「可用工具」段落由这里生成。
    """

    @staticmethod
    def get_tool_lines(user_id: int) -> List[str]:
        """给编排器 system prompt 注入的「可用工具」文本行。
        包含内置工具 + 用户已装 MCP 工具。
        """
        # 内置工具（始终可用）
        builtin_lines = [
            build_tool_description_line(
                "web_search", "联网搜索，获取最新信息",
                '{ keywords: 字符串数组 }'
            ),
            build_tool_description_line(
                "memory_search", "用户长期记忆检索（向量 + BM25）",
                '{ query: 字符串 }'
            ),
        ]

        # MCP 工具（用户已安装的）
        mcp_tools: List[ToolDesc] = mcp_client_pool.get_user_tools(user_id)
        mcp_lines = [
            build_tool_description_line(t.tool_name, t.description, t.params_template)
            for t in mcp_tools
        ]

        all_lines = builtin_lines + mcp_lines
        if mcp_lines:
            logger.debug(f"[MCP][工具注册] 用户 {user_id} 可用 {len(mcp_lines)} 个 MCP 工具")
        return all_lines

    @staticmethod
    async def execute(user_id: int, tool_name: str, args: dict) -> dict:
        """编排器调 MCP 工具时走这里 → 路由到对应 MCP。
        返回：{"summary": str, "data": list, "context_text": str, "duration_ms": int}
        """
        return await mcp_client_pool.call_tool(user_id, tool_name, args)

    @staticmethod
    def is_mcp_tool(tool_name: str) -> bool:
        """判断工具名是否属于 MCP 工具（带命名空间前缀）"""
        return "__" in tool_name


# 全局单例
mcp_tool_registry = McpToolRegistry()
