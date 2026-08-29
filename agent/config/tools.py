# -*- coding: utf-8 -*-
"""
config.tools：工具注册表的工具描述、SSE 工具摘要模板、内部动作枚举、协议常量。
和 config.behavior（纯数值）区分：本文件放"字符串型协议常量 / 工具描述 / 动作名称"。

工具名用"注册常量"的好处：
  1. 工具名改一处即可同步 EXPERT_TOOL_REGISTRY key + 编排器 prompt 里生成的 JSON + 前端 SSE type
  2. 避免打错字符串导致编排器写了未知工具名被 _tool_web_search / memory_search 直接当失败（fail-safe 虽然接住了但有性能损失）
"""

from typing import Dict, Tuple, Callable, Any, List

# ==========================================
# 1. 专家模式编排器 3 个 action（OrchResult.action 三选一）
#    原硬编码字符串："collect_tools" / "deep_thinking" / "reply_directly" 出现十几次
# ==========================================

EXPERT_ACTION_COLLECT = "collect_tools"
EXPERT_ACTION_DEEP = "deep_thinking"
EXPERT_ACTION_REPLY = "reply_directly"

# 编排最终路径（写入 expert_trace.finalPath）
# ⚠ 注意：快速模式在 ChatView.vue / ExpertTraceRenderer.vue 中前端渲染判断字符串是 "fast_reply"；
#        专家模式 deep_thinking / reply_directly 则分别是下面两项。
EXPERT_FINAL_PATH_DEEP = "deep_thinking"
EXPERT_FINAL_PATH_REPLY = "reply_directly"
FAST_MODE_FINAL_PATH = "fast_reply"


# ==========================================
# 2. 专家工具注册表：工具名常量 + 对应「参数格式说明行模板」
# ==========================================

TOOL_NAME_WEB_SEARCH = "web_search"
TOOL_NAME_MEMORY_SEARCH = "memory_search"

# 工具描述（英文名字符串 + 一行中文说明），给编排器 system prompt 注入使用
# 原硬编码位置：main.py L1617-L1623
TOOL_DESC_WEB_SEARCH = "联网搜索，获取最新信息"
TOOL_DESC_MEMORY_SEARCH = "用户长期记忆检索（向量 + BM25）"

# 参数格式（拼到工具描述行末尾）
TOOL_PARAMS_WEB_SEARCH = '{{ keywords: 字符串数组 }}'
TOOL_PARAMS_MEMORY_SEARCH = '{{ query: 字符串 }}'


def build_tool_description_line(name: str, desc: str, params_template: str = "") -> str:
    """
    生成编排器 system prompt 里展示的「- 工具名：描述，参数: { ... }」行。
    与原 main.py L1618-L1623 格式完全一致。
    """
    base = f"- {name}：{desc}"
    if params_template:
        base += f"，参数: {params_template}"
    return base


# 默认描述行工厂（main.py 里直接用，避免重复拼）
def default_tool_description_lines(extra_tools: Dict[str, Tuple[Callable, str]] = None) -> List[str]:
    """
    构造 EXPERT_TOOL_REGISTRY 的所有描述行（动态注入），
    对于 web_search / memory_search 使用上面的"参数格式规范版"，
    其余新增工具兜底只输出名称 + 描述（后续新增工具可在 EXPERT_TOOL_REGISTRY 里直接加，无需改这里）。
    """
    from agent.main import EXPERT_TOOL_REGISTRY  # 延迟导入避免循环
    tools = dict(extra_tools) if extra_tools else dict(EXPERT_TOOL_REGISTRY)
    lines: List[str] = []
    for name, (_fn, desc) in tools.items():
        if name == TOOL_NAME_WEB_SEARCH:
            lines.append(build_tool_description_line(name, desc or TOOL_DESC_WEB_SEARCH, TOOL_PARAMS_WEB_SEARCH))
        elif name == TOOL_NAME_MEMORY_SEARCH:
            lines.append(build_tool_description_line(name, desc or TOOL_DESC_MEMORY_SEARCH, TOOL_PARAMS_MEMORY_SEARCH))
        else:
            lines.append(build_tool_description_line(name, desc or ""))
    return lines


# ==========================================
# 3. SSE tool_call_result 摘要模板（web_search / memory_search 统一）
#    原硬编码字符串：f"已搜索 {result_count} 个网页" / f"已读取 {resultCount} 个记忆片段"
# ==========================================

SUMMARY_TEMPLATE_WEB_SEARCH = "已搜索 {n} 个网页"
SUMMARY_TEMPLATE_MEMORY_SEARCH = "已读取 {n} 个记忆片段"

# 错误时摘要
SUMMARY_TEMPLATE_WEB_SEARCH_FAIL = "搜索失败"
SUMMARY_TEMPLATE_MEMORY_SEARCH_FAIL = "记忆读取失败"


# ==========================================
# 4. 编排器 step phase 名（发给前端 orchestration_step 的 phase 字段）
#    原硬编码：main.py L2283 "planning" / "thinking"
# ==========================================

ORCH_PHASE_PLANNING = "planning"
ORCH_PHASE_THINKING = "thinking"


# ==========================================
# 5. 回写后端接口的路由后缀
#    原 main.py L1490 / L1522 直接写字符串，避免输错路径
# ==========================================

BACKEND_ENDPOINT_UPDATE_SEARCH_RESULTS = "/api/message/update-search-results"
BACKEND_ENDPOINT_UPDATE_MESSAGE_CONTENT = "/api/message/update-content"
BACKEND_ENDPOINT_UPDATE_EXPERT_TRACE_LEGACY = "/api/message/update-expert-trace"
BACKEND_ENDPOINT_MEMORY_DELETE = "/api/memory/delete"


# ==========================================
# 6. 搜索服务传给博查 API 的固定参数（freshness/summary）
#    原 search_service.py L52 L53 字面量
# ==========================================

SEARCH_API_SUMMARY_FLAG = True
SEARCH_API_FRESHNESS = "noLimit"


# ==========================================
# 7. 搜索服务 → LLM 上下文拼接模板（search_service.get_search_context 使用）
#    原 search_service.py 里硬编码 f"【搜索结果{i}】标题: ...\n内容: ..."
# ==========================================

SEARCH_CONTEXT_ITEM_TEMPLATE = "【搜索结果{index}】标题: {title}\n内容: {content}"


# ==========================================
# 8. 发送给后端的 mediaType 约定常量（避免四处写 "IMAGE" / "FILE" 字符串不一致）
#    原 main.py L568 / L635 / L676 / L705 / L785 等处硬编码
# ==========================================

MEDIA_TYPE_IMAGE = "IMAGE"
MEDIA_TYPE_FILE = "FILE"
