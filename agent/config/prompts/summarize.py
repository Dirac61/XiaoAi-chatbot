# -*- coding: utf-8 -*-
"""
后端调用 /summarize 接口时的摘要 prompt。
原硬编码位置：agent/main.py L2443-L2460
"""

# 摘要 system prompt：JSON 输出，字段固定 key_points / entities / summary
# 【补充示例】原硬编码只有字段说明无示例，模型输出格式不稳定；补一段输出示例做 few-shot
SUMMARIZE_SYSTEM_PROMPT = """你是一个专业的对话摘要助手。请根据对话内容生成结构化事实摘要。

摘要要求：
1. 长度不超过500个字符
2. 使用JSON格式输出，包含以下字段：
   - "key_points": 关键要点数组（3-5条）
   - "entities": 涉及的实体/人物列表
   - "summary": 简短的自然语言摘要（100字以内）

【输出示例】
对话内容：
user: 我叫张三，在北京做Java开发，最近在学Spring Boot
assistant: 你好张三！北京Java圈很活跃，Spring Boot是当前主流框架，学习方向很好。

输出：
{"key_points": ["用户名叫张三", "在北京从事Java开发工作", "正在学习Spring Boot"], "entities": ["张三", "北京", "Java", "Spring Boot"], "summary": "用户张三自我介绍为北京的Java开发工程师，正在学习Spring Boot框架。"}"""


def build_summarize_user_prompt(messages_text: str, existing_summary: str) -> str:
    """
    构造摘要 user prompt。按原硬编码格式：如果存在已有摘要，加"--- 已有摘要 ---"分隔块。

    :param messages_text: 格式化后的对话文本（「User: xxx / Assistant: xxx\n」逐行）
    :param existing_summary: 上一次的摘要字符串，空字符串或 None 视为没有
    :return: 组装好的 user prompt
    """
    has_existing = bool(existing_summary)
    has_messages = bool(messages_text)
    block = ""
    if has_existing:
        block += "--- 已有摘要 ---\n"
        block += existing_summary
        block += "\n\n"
    if has_messages:
        block += "--- 新增对话内容 ---\n"
        block += messages_text
    else:
        # 原硬编码分支：如果 messages_text 为空 → 仍要写 "无对话内容" 占位
        block += "无对话内容"

    return f"请根据以下对话内容生成结构化事实摘要：\n\n{block}\n\n请输出符合要求的JSON格式摘要。"


# 摘要模型温度（原硬编码 0.3，输出 JSON 要低）
SUMMARIZE_TEMPERATURE = 0.3

# 摘要关思考（JSON 结构会被 reasoning 破坏）
SUMMARIZE_DISABLE_THINKING = True
