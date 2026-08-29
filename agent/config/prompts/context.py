# -*- coding: utf-8 -*-
"""
上下文模板：构造 FINAL 阶段 / 编排器 user prompt 时用的通用文本块。
原硬编码位置：
  - agent/main.py L560-L572（_build_global_context）
  - agent/main.py L533-L557（_build_thinking_history_prompt）
  - agent/main.py 中多处 [用户上传了图片]/[用户上传了文件] 前缀
"""

from typing import List, Any, Dict, Optional

from .persona import HISTORY_ROLE_USER_CN, HISTORY_ROLE_ASSISTANT_CN


# ==================== 全局上下文（_build_global_context 模板）====================

GLOBAL_CONTEXT_QUESTION_TITLE = "【用户提问】"
GLOBAL_CONTEXT_EXTRACTED_TITLE = "【图片/文件提取内容】"
GLOBAL_CONTEXT_MEMORY_TITLE = "【相关记忆】"
GLOBAL_CONTEXT_SEARCH_TITLE = "【联网搜索信息】"


def build_global_context_text(
    user_message: str,
    extracted_text: Optional[str],
    memory_context_parts: List[str],
    search_context_parts: List[str],
    *,
    extracted_max_len: int = 3000,
) -> str:
    """
    构造 FINAL 阶段（deep_thinking / reply_directly）共用的「全局上下文」文本块。
    顺序严格与原硬编码一致：用户提问 → 提取文本 → 相关记忆 → 联网搜索。

    :param user_message: 用户原始提问
    :param extracted_text: 图片/文件提取到的文本（None 视为无）
    :param memory_context_parts: 形如 ["- xxx", "- yyy"] 的行列表
    :param search_context_parts: 由搜索服务合成的大块文本列表
    :param extracted_max_len: 提取文本截断长度（原硬编码 3000）
    :return: 拼接好的全局上下文字符串
    """
    parts = [f"{GLOBAL_CONTEXT_QUESTION_TITLE}\n{user_message}"]
    if extracted_text:
        parts.append(f"{GLOBAL_CONTEXT_EXTRACTED_TITLE}\n{extracted_text[:extracted_max_len]}")
    if memory_context_parts:
        parts.append(f"{GLOBAL_CONTEXT_MEMORY_TITLE}\n" + "\n".join(memory_context_parts))
    if search_context_parts:
        parts.append(f"{GLOBAL_CONTEXT_SEARCH_TITLE}\n" + "\n\n".join(search_context_parts))
    return "\n\n".join(parts)


# ==================== 编排器思考历史（_build_thinking_history_prompt 模板）====================

THINKING_HISTORY_NOOP = "（暂无思考历史，这是第一次编排）"


def build_thinking_history_text(orch_history_records: List[Any]) -> str:
    """
    根据 ExpertState.orch_history 构造「思考历史」段落，喂给下一轮编排器。
    与原 _build_thinking_history_prompt 完全一致。

    :param orch_history_records: List[OrchHistoryRecord]（鸭子类型，需要 iteration/action/purpose/tools/analysis 字段）
    """
    if not orch_history_records:
        return THINKING_HISTORY_NOOP
    lines: List[str] = []
    for rec in orch_history_records:
        tools_line_parts: List[str] = []
        for t in rec.tools:
            if t.success:
                rc = f"{t.resultCount}条" if t.resultCount is not None else "成功"
                tools_line_parts.append(f"{t.tool} ✅ {rc}({round(t.durationMs / 1000, 2)}s)")
            else:
                tools_line_parts.append(
                    f"{t.tool} ❌ 失败: {(t.error or '')[:60]}"
                )
        tools_desc = "，".join(tools_line_parts) if tools_line_parts else "（本步无工具）"
        lines.append(
            f"第{rec.iteration}轮：\n"
            f"  action: {rec.action}\n"
            f"  purpose: {rec.purpose or ''}\n"
            f"  tools: {tools_desc}\n"
            f"  我当时的分析：{rec.analysis}"
        )
    return "\n".join(lines)


# ==================== 历史消息格式化为中文角色段落（编排器/reply_directly 共用）====================

def format_recent_history_for_llm(
    history: Optional[List[Dict[str, Any]]],
    *,
    recent_n: int = 10,
    max_len_each: int = 500,
) -> str:
    """
    把 history 消息列表格式化成「\n用户：xxx\n助手：xxx」段落。
    原硬编码位置：
      - main.py L1605-L1613（专家编排器历史）
      - main.py L1980-L1988（reply_directly 历史）

    :param history: 原始 history 列表，元素形如 {"role":"user|assistant", "content":"..."}
    :param recent_n: 仅使用最后 N 条（原硬编码 10）
    :param max_len_each: 每条内容截断字数（原硬编码 500）
    :return: 拼接好的字符串；空历史返回空字符串由调用方判空渲染"无"
    """
    if not history:
        return ""
    recent = history[-recent_n:]
    buf: List[str] = []
    for msg in recent:
        role = msg.get("role", "")
        content = (msg.get("content") or "")[:max_len_each]
        if not role or not content:
            continue
        role_cn = HISTORY_ROLE_USER_CN if role == "user" else HISTORY_ROLE_ASSISTANT_CN
        buf.append(f"\n{role_cn}：{content}")
    return "".join(buf).lstrip("\n")


# ==================== 快速模式里给主模型 user_content 追加的「上传了图片/文件」前缀模板 ====================

USER_PREFIX_UPLOAD_SINGLE_IMAGE = "[用户上传了图片]\n提问：{message}"
USER_PREFIX_UPLOAD_SINGLE_IMAGE_WITH_EXTRACTED = (
    "[用户上传了图片]\n提问：{message}\n图片内容：{extracted_text}"
)
USER_PREFIX_UPLOAD_SINGLE_FILE = "[用户上传了文件]\n文件地址: {media_url}\n用户提问: {message}{file_text_block}"
USER_PREFIX_UPLOAD_MULTI_FILES = "[用户上传了{n_files}个文件]\n用户提问: {message}{file_text_block}"

# 快速模式 history 遍历中，把 IMAGE/FILE 类型消息做前缀包装（用于历史上下文渲染，与 user_content 前缀一致但略简化）
HISTORY_IMAGE_PREFIX_SIMPLE = "[用户上传了图片]\n提问：{content}"
HISTORY_IMAGE_PREFIX_WITH_EXTRACTED = "[用户上传了图片]\n提问：{content}\n图片内容：{extracted_text}"
HISTORY_FILE_PREFIX_SIMPLE = "[用户上传了文件]\n提问：{content}"
HISTORY_FILE_PREFIX_WITH_EXTRACTED = "[用户上传了文件]\n提问：{content}\n文件内容：{extracted_text}"

# 文件内容块前缀（当有 extracted_text 时才拼）
FILE_TEXT_BLOCK_PREFIX = "\n文件内容:\n{text}"
