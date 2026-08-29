# -*- coding: utf-8 -*-
"""
专家模式 reply_directly 简易路径 prompt。
原硬编码位置：agent/main.py L1990-L2001
"""

# 简易回复 system prompt：高贵但简短的人设 + 不要出思考/JSON 约束
REPLY_DIRECTLY_SYSTEM_PROMPT = (
    "你是爱尔奎特·布伦史塔德，高贵的真祖，月之公主。\n"
    "【角色】高贵、稍微有点傲慢但态度不恶劣；说话简洁、自然，不用复杂 markdown。\n"
    "【任务】基于用户提问 + 给定上下文，直接生成简短自然的回复正文，"
    "严格禁止输出'思考过程'标题或 JSON，直接输出对话正文即可。"
)


def build_reply_directly_user_prompt(
    user_message: str,
    global_context: str,
    history_text: str,
) -> str:
    """
    构造 reply_directly 路径的 user prompt。

    :param user_message: 原用户提问
    :param global_context: 「_build_global_context(state)」生成的全局上下文文本
    :param history_text: 最近 10 条对话历史（角色中文名 + 内容截断），空字符串则渲染"无"
    :return: 组装好的 user prompt
    """
    history_block = history_text if history_text else "无"
    return (
        f"【用户提问】\n{user_message}\n\n"
        f"【上下文】\n{global_context}\n\n"
        f"【对话历史（最近10条）】\n{history_block}\n\n"
        "请直接回复用户的问题，简短自然。"
    )


# 简易回复温度（偏高一点更自然，原硬编码 0.7）
REPLY_DIRECTLY_TEMPERATURE = 0.7

# 简易回复 max_tokens 上限（原硬编码 2000）
REPLY_DIRECTLY_MAX_TOKENS = 2000
