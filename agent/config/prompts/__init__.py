# -*- coding: utf-8 -*-
"""
config.prompts 子包：存放所有「硬编码大段 prompt / 模板」
按功能拆分为独立文件，避免 main.py 里上千行 prompt 字面量堆在一起难以维护。

模块划分原则（一个场景一个文件，文件语义清晰）：
  - persona.py           : 主模型 / 回复模型共用的人设设定（爱尔奎特·布伦史塔德）
  - ocr.py               : 单图 OCR、多图批量 OCR 的 system prompt + 用户侧提问文本
  - orchestrator_fast.py : 快速模式编排器（need_search 决策）system/user prompt 模板
  - orchestrator_expert.py: 专家模式编排器（单步 collect_tools / deep / reply 决策）system/user prompt 模板
  - deep_thinking.py     : 深度思考 FINAL 阶段的 system prompt + 提示块文本
  - reply_directly.py    : 专家 reply_directly 简易路径 system/user prompt 模板
  - summarize.py         : /summarize 接口对话摘要生成的 system/user prompt 模板
  - memory_extraction.py : MemoryService.extract_memory_units 的 system/user prompt 模板
  - context.py           : 构造最终回答消息用的上下文模板（全局上下文块、长期记忆块、搜索块）

使用方式：
  from config.prompts.persona import PERSONA_SYSTEM_PROMPT
  from config.prompts.context import (
      build_global_context_text, build_memory_context_block, build_search_context_block,
  )
"""
