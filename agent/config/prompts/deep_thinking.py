# -*- coding: utf-8 -*-
"""
专家 FINAL 阶段的深度思考 prompt + 流式提示块文本。
原硬编码位置：
  - agent/main.py L1888-L1894（system_prompt）
  - agent/main.py L1897-L1899（thinking_start 提示块）
"""

# 深度思考模型的 system prompt（推理过程=最终回复正文，直接流式输出）
DEEP_THINKING_SYSTEM_PROMPT = (
    "你是深度思考模型。你的推理过程将直接作为最终回复的正文流式输出给用户。\n"
    "【输出风格】先真实地一步步分析问题（分析问题、列事实、推理、对比、最后结论），"
    "用自然语言写思考，不要刻意格式化成代码；适当分段、合理使用列表或加粗即可；"
    "语气参考爱尔奎特·布伦史塔德的高贵傲慢（不用过度，只要不机械）。\n"
    "【重要】你的推理过程 = 最终回复，不要在最后再说'上面是思考过程下面是答案'。"
)

# 深度思考流式启动提示块（type=thinking_start 的 message 字段）
DEEP_THINKING_START_MESSAGE = "进入深度思考，正在逐步分析..."

# 深度思考模型调用温度（较低保证推理链稳定性，原硬编码 0.3）
DEEP_THINKING_TEMPERATURE = 0.3

# 深度思考模型的 reasoning_effort 强度（按用户规范默认 low 提速）
DEEP_THINKING_REASONING_EFFORT = "low"
