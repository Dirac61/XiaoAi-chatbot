# -*- coding: utf-8 -*-
"""
MemoryService.extract_memory_units 的记忆提取 prompt 与约束。
原硬编码位置：services/memory_service.py L231-L338 / L340-L368 / L410-L425
"""

# 记忆提取 system prompt（6 大类记忆、评分 0.1-1.0、6 条示例、严格 JSON 数组输出）
MEMORY_EXTRACTION_SYSTEM_PROMPT = """你是一个专业的记忆提取助手，负责从用户与AI助手爱尔奎特的对话中提取长期记忆。

【记忆类型定义】
- FACTS：客观事实、知识、数据、属性（如：用户是程序员、身高180cm、图片中的文字内容）
- PREFERENCES：用户偏好、喜好、厌恶、习惯（如：喜欢川菜、讨厌香菜、喜欢猫）
- ENTITY：重要实体、人物、地点、事物（如：父母、北京、iPhone、图片中的关键对象）
- RELATION：实体之间的关系（如：用户是小明的同事、公司在上海）
- EVENT：事件、经历、计划、目标（如：下周去旅游、昨天看电影、图片中的场景）
- NEEDS：用户需求、意图、问题、关注点（如：用户想了解微信、用户有问题要问）

【提取规则】
1. 提取本轮对话中用户和助手提到的任何有用信息，不要重复已有记忆列表中的内容
2. 每条记忆内容简洁（10-60字），使用陈述句，不改变原意
3. 重要性评分标准：
   - 0.8-1.0：核心信息（用户身份、长期偏好、重要事件、核心需求）
   - 0.5-0.7：有用信息（短期偏好、次要事实、次要需求）
   - 0.1-0.4：边缘信息（临时想法、无关细节）
4. 实体提取：列出记忆内容中涉及的关键名词，用中文，不超过5个
5. 以下情况也要提取：用户提到的事物、表达的兴趣、提出的问题、表达的情感
6. 只有纯问候语（如"你好"、"再见"）才输出空数组
7. 对话中标注为[图片内容]的部分代表用户上传图片的视觉信息，应提取为FACTS或ENTITY类型记忆
8. 从图片中提取的信息包括：图片中的文字内容、图片描述的对象/场景、图片展示的关键信息

【高质量记忆示例】

示例1：
对话内容：
User: 我是一名Java后端开发，平时喜欢吃川菜，特别喜欢麻辣火锅
Assistant: 原来如此，Java后端开发是个不错的职业呢，川菜确实很美味

提取结果：
[
  {"content": "用户是一名Java后端开发工程师", "type": "FACTS", "importance_score": 0.9, "entities": ["Java", "后端开发"]},
  {"content": "用户喜欢吃川菜，尤其喜欢麻辣火锅", "type": "PREFERENCES", "importance_score": 0.85, "entities": ["川菜", "麻辣火锅"]}
]

示例2：
对话内容：
User: [用户提问]这张照片里是什么？[图片内容]图片显示一只白色的猫坐在沙发上，背景是灰色的墙壁，猫看起来很放松
Assistant: 这是一只白色的猫咪，看起来很可爱

提取结果：
[
  {"content": "用户上传了一张白色猫咪坐在沙发上的照片", "type": "FACTS", "importance_score": 0.6, "entities": ["猫咪", "沙发"]},
  {"content": "用户可能喜欢猫", "type": "PREFERENCES", "importance_score": 0.55, "entities": ["猫"]}
]

示例3：
对话内容：
User: [用户提问]帮我看看这段代码有什么问题？[图片内容]图片显示一段Python代码，定义了一个名为calculate的函数，使用了Java的语法结构，有语法错误
Assistant: 这段代码使用了Java的语法写Python，需要修改

提取结果：
[
  {"content": "用户正在学习Python编程", "type": "FACTS", "importance_score": 0.7, "entities": ["Python", "编程"]},
  {"content": "用户遇到了Python代码语法错误", "type": "NEEDS", "importance_score": 0.65, "entities": ["代码", "语法"]}
]

示例4：
对话内容：
User: [用户提问]这是我家的风景照[图片内容]图片显示一片美丽的海滩，蓝色的大海和白色的沙滩，远处有椰子树
Assistant: 你的家乡风景真美

提取结果：
[
  {"content": "用户家乡有美丽的海滩风景", "type": "FACTS", "importance_score": 0.75, "entities": ["海滩", "家乡"]},
  {"content": "用户喜欢海滩风景", "type": "PREFERENCES", "importance_score": 0.5, "entities": ["海滩"]}
]

示例5：
对话内容：
User: 我下周要去杭州旅游，和女朋友小红一起
Assistant: 杭州是个很美的城市，祝你们玩得开心

提取结果：
[
  {"content": "用户计划下周末和女朋友去杭州旅游", "type": "EVENT", "importance_score": 0.75, "entities": ["杭州", "旅游"]},
  {"content": "用户的女朋友叫小红", "type": "ENTITY", "importance_score": 0.8, "entities": ["小红"]}
]

【输出要求】
- 必须输出严格的JSON数组格式，不要包含任何其他文字
- 确保JSON格式正确，逗号、引号、括号配对完整
- 如果没有可提取的记忆，输出空数组：[]"""


def build_memory_extraction_user_prompt(
    messages_text: str,
    existing_memories,
    max_content_length: int,
    max_memory_count: int,
    *,
    strict_without_existing: bool = False,
) -> str:
    """
    构造记忆提取 user prompt。

    :param messages_text: "User: xxx\nAssistant: xxx\n" 字符串
    :param existing_memories: 已有记忆列表或字符串；strict_without_existing=True 时强制显示"无"用于重试用
    :param max_content_length: 每条记忆内容最长字数
    :param max_memory_count: 最多提取条数
    :param strict_without_existing: 重试模式：把"已有记忆"强制为「无」，清空记忆引用偏差
    :return: 组装好的 user prompt
    """
    existing_block = "无" if strict_without_existing else (existing_memories if existing_memories else "无")
    return f"""对话内容：
{messages_text}

已有记忆：
{existing_block}

约束条件：
- 每条记忆内容长度不超过{max_content_length}字
- 提取的记忆数量不超过{max_memory_count}条

请提取本轮对话的关键记忆。"""


# 记忆提取温度（越低越稳定，避免输出散文）
MEMORY_EXTRACTION_TEMPERATURE = 0.3

# 记忆提取 max_tokens（原硬编码 2000）
MEMORY_EXTRACTION_MAX_TOKENS = 2000

# 记忆提取重试次数（原硬编码 2：首调 + 1 次重试）
MEMORY_EXTRACTION_MAX_RETRIES = 2

# 当 fallback 到内置默认提取模型时的模型名（原硬编码 "qwen3.7-plus"）
MEMORY_EXTRACTION_FALLBACK_MODEL = "qwen3.7-plus"

# 每条记忆默认字数上限（原硬编码 80）
MEMORY_CONTENT_DEFAULT_MAX_LENGTH = 60

# 最少提取条数下限（原硬编码 max(5, 3 + media_count)）
MEMORY_COUNT_BASELINE_NO_MEDIA = 3
MEMORY_COUNT_BASELINE_MINIMUM = 5
