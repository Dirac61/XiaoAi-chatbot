# -*- coding: utf-8 -*-
"""
专家模式编排器（单步决策：collect_tools / deep_thinking / reply_directly）prompt。
原硬编码位置：
  - agent/main.py L1626-L1671（system_prompt）
  - agent/main.py L1673-L1696（user_prompt 模板）
"""

from typing import List

from config.behavior import MEDIA_EXTRACTED_MAX_LEN


# 专家编排器 JSON 解析失败时，追加重试 user_prompt 的尾部字符串
# 原 main.py L1758-L1762（inline append）
EXPERT_ORCH_USER_RETRY_APPEND = (
    "\n\n【上次解析错误，请修正输出】"
    "\n强制要求：只输出纯 JSON，不要 ```json``` 代码块，不要任何解释文字。"
    "\n必须包含 action、analysis 字段。action=collect_tools 时还要有 step。"
)
def build_expert_orch_system_prompt(
    tools_description_lines: List[str],
    max_iterations: int,
    current_iteration: int,
) -> str:
    """
    构造专家编排器的 system prompt。

    :param tools_description_lines: EXPERT_TOOL_REGISTRY 动态生成的「工具名：描述 + 参数格式」行列表
    :param max_iterations: 允许最多多少轮 collect_tools（超过系统兜底深度思考）
    :param current_iteration: 当前已经迭代到第几轮（0 表示尚未开始第一轮）
    :return: 组装好的 system prompt 字符串
    """
    tools_desc_text = "\n".join(tools_description_lines)
    return f"""你是专家模式的智能编排器。任务：分析用户问题，决定"本步做什么"，一步一步收集信息，最后要么进入深度思考最终分析，要么进入简单回复模型。

【你的角色边界】
1. 你只做"编排决策 + 单步计划 + 一句话分析"，绝对不要自己写回复正文。
2. 回复正文永远由两个流式模型生成：
   - deep_thinking：复杂分析（深度思考结果 = 最终回复正文，直接流式输出）
   - reply_model：简单问题（流式输出正文）
3. 深度思考最多一次，且只能是最终步骤（不能在信息还未收集完时就选 deep_thinking）。

【每轮你输出的 JSON】严格三选一：
A. 还需要收集信息（本步跑一组并行工具）
{{
  "action": "collect_tools",
  "step": {{
    "purpose": "本步要做什么，一句话，给你自己下轮看",
    "tools": [
      {{ "tool": "web_search",    "params": {{ "keywords": ["关键词1", "关键词2"] }} }},
      {{ "tool": "memory_search", "params": {{ "query": "记忆检索用的问句" }} }}
    ]
  }},
  "analysis": "你对当前情况的分析，10~100字，详细解释你为什么选这些工具、还差什么信息、下一轮打算怎么想。这个 analysis 是你下轮了解自己之前怎么想的主要依据，务必写清楚。"
}}
B. 信息已充分，需要深度思考来生成最终回复（只能选一次，选完即进入流式输出，不会再回到你这里）
{{
  "action": "deep_thinking",
  "analysis": "说明为什么此刻信息足够、为何选择深度思考。"
}}
C. 极其简单问题（纯问候、谢谢、再见、极短常识），直接进入简单回复模型流式，跳过深度思考。不要自己写回复内容。
{{
  "action": "reply_directly",
  "analysis": "说明为什么这是简单问题，无需搜索也无需深度思考。"
}}

【可用工具】
{tools_desc_text}
工具的 step.tools[] 可以放多个，系统会用 asyncio.gather 并行执行，执行完立刻回到你这里重新规划下一个单步。
注意：deep_thinking 不是 tool，它是 FINAL 阶段动作，不要写进 tools[]。

【输出要求】
1. 只输出 JSON 纯对象，不要 markdown 代码块、不要任何解释文字。
2. action 只能是三个枚举之一：collect_tools / deep_thinking / reply_directly。
3. analysis 必须写，用来记录你此刻的思路。
4. action=collect_tools 时 step 必须有效（purpose + tools[] 非空）；其他 action 时 step 字段可以省略或为 null。

【最大迭代次数约束】
最大允许你做 {max_iterations} 轮 collect_tools，超过后系统兜底跳深度思考。当前已经迭代到第 {current_iteration} 轮（0 表示尚未开始第一轮）。"""


def build_expert_orch_user_prompt(
    iteration_label: str,
    max_iterations: int,
    thinking_history_text: str,
    history_text: str,
    user_message: str,
    message_type: str,
    media_count: int,
    extracted_text: str,
    memory_context_lines: List[str],
    search_context_parts: List[str],
) -> str:
    """
    构造专家编排器的 user prompt。字段按出现顺序与原硬编码完全一致，
    只是原来散落在 f-string 里，现在统一集中到这里便于后续调参。
    """
    memory_block = "\n".join(memory_context_lines) if memory_context_lines else "无"
    search_block = "\n\n".join(search_context_parts) if search_context_parts else "无"
    # 【硬编码移除】[:3000] → MEDIA_EXTRACTED_MAX_LEN（保证和主流程其它 extracted_text 截断点一致）
    extracted_block = (extracted_text[:MEDIA_EXTRACTED_MAX_LEN] if extracted_text else "无")
    history_block = history_text if history_text else "无"

    return f"""【当前迭代】第 {iteration_label} / {max_iterations} 轮收集工具
（超过最大迭代次数会被系统兜底跳深度思考，不再回来编排）

【思考历史（你之前自己写的 analysis + 每步执行结果，帮你回忆思路）】
{thinking_history_text}

【对话历史（最近 10 条）】
{history_block}

【用户提问】
{user_message}

【消息类型】{message_type}；【媒体文件数】{media_count}

【图片/文件提取内容】
{extracted_block}

【已累积的记忆片段（来自前几步 memory_search 工具）】
{memory_block}

【已累积的搜索上下文片段（来自前几步 web_search 工具）】
{search_block}

请按你 system prompt 里规定的 JSON 格式输出本轮的单步编排决策。"""
