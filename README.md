# XiaoAi - 小爱 AI 聊天助手

一个支持快速对话和专家深度分析模式的 AI 聊天应用，具有多模态识别、联网搜索、长期记忆等功能。

## 项目架构

项目采用前后端分离 + AI Agent 的三层架构：

```
XiaoAi/
├── frontend/          # 前端 - Vue 3 + Vite
├── backend/           # 后端 - Java Spring Boot 3
├── agent/             # Agent - Python FastAPI
└── README.md
```

### 技术栈

| 模块 | 技术 |
|------|------|
| 前端 | Vue 3, Vite, Element Plus, Axios, marked |
| 后端 | Spring Boot 3.2.5, MyBatis-Plus, Redis, MySQL, Aliyun OSS |
| Agent | FastAPI, OpenAI SDK, Qdrant, 博查搜索 |

## 功能特性

### 双模式对话

**快速模式**
- 直接调用大模型流式生成回复，响应速度快
- 支持图片/文件内容提取后自动拼入上下文
- 返回的结构化搜索结果以独立面板展示
- 对话内容自动提取记忆并持久化

**专家模式**
- 编排器（Orchestrator）分析用户问题，判断是否需要联网搜索或深度思考
- 最多 3 次迭代循环：每次调用编排器决策 → 执行工具（搜索/深度思考）→ 再次评估
- 搜索时实时返回搜索关键词、搜索结果摘要和搜索用时
- 深度思考时流式输出推理过程，展示逐步骤分析思路
- 编排器基于收集到的信息直接生成最终回复，不经过主模型

### 三层记忆系统

按时间维度分为短期记忆、中期记忆、长期记忆三层，覆盖从当前对话到跨会话的完整记忆范围。

**第一层：短期记忆（当前会话上下文）**
- 保存最近 20 条消息到 Redis（key: `session:{sessionId}`），支持毫秒级读写
- 当前对话中的图片/文件提取内容（extracted_text）直接拼入模型上下文
- 会话打开时自动从 MySQL 预热元数据（turn_count + summary）到 Redis
- Redis 过期时间 1 天，过期后从 MySQL 重新加载

**第二层：中期记忆（会话摘要）**
- 每 10 轮对话自动触发一次摘要提取，之后每 5 轮触发一次（第 10、15、20...轮）
- 调用 Agent 的 `/summarize` 接口，将历史消息和已有摘要发送给模型生成新摘要
- 摘要存储到 MySQL（session.summary 字段）并缓存到 Redis（key: `session:summary:{sessionId}`）
- 摘要长度上限 500 字，可快速回顾整个会话的核心内容
- 首次打开会话时从 MySQL 预热摘要到 Redis

**第三层：长期记忆（向量记忆）**
- 每轮对话完成后，后台异步提取记忆单元并存储到 Qdrant 向量数据库
- **提取**：调用独立的记忆提取模型（如 deepseek-v4-flash）进行语义理解和结构化输出，提取 6 种记忆类型（FACTS、PREFERENCES、ENTITY、RELATION、EVENT、NEEDS），每条附带重要性评分和实体标签，支持从图片/文件提取内容中提取记忆
- **存储**：使用嵌入模型生成文本稠密向量（1024 维），存入 Qdrant 前经两级去重（Redis 字面去重 + 向量余弦相似度去重，阈值 0.85），同时提取 BM25 关键词用于辅助检索
- **检索**：混合搜索策略——稠密向量搜索 + BM25 关键词搜索 + 重要性分数融合，再经交叉编码器 Rerank 重排序，最终结果供给模型作为上下文，实现跨会话记忆

### 多模态与文件

**图片处理**
- 支持单图和多图上传（最多 5 张同时识别）
- 模型调用优先使用 base64（data:image 格式），消除模型下载图片的延迟
- OSS 上传使用哈希去重（MD5），相同图片不重复上传

**图片识别**
- 支持批量提取：多张图片并行调用 OCR 模型识别
- 提取结果格式化为"图N：描述内容"的清晰结构
- OCR 模型使用独立的多模态模型（如 qwen3.6-flash），支持图文理解
- 提取结果持久化到 MySQL，后续对话可直接引用

**文件处理**
- 支持上传图片（≤10MB）和通用文件（≤50MB）
- 图片提取文字/视觉信息，文件读取文本内容
- 支持 .docx（python-docx）和 .pdf（PyPDF2）格式解析
- 存储采用 MD5 哈希去重 + 引用计数管理，引用归零时自动删除 OSS 文件

**语音识别**
- 集成阿里云 ASR（自动语音识别）
- 录制音频后上传识别为文本

### 联网搜索
- 集成博查搜索 API，支持多关键词组合搜索
- 配置最大搜索结果数和摘要长度
- 快速模式：搜索结果在消息中以独立可折叠面板展示，标题带超链接
- 专家模式：实时展示搜索状态（蓝色背景搜索中 → 绿色搜索完成），搜索结果供编排器决策

### 会话管理
- 基于雪花算法（Snowflake）生成会话 ID，返回前端时转为字符串避免 JS 精度丢失
- Redis 缓存最近的 20 条消息，MySQL 持久化全部消息
- 会话打开时自动从 MySQL 预热元数据（turn_count + summary）到 Redis
- 每 10 轮自动触发一次摘要提取，之后每 5 轮触发一次
- 删除会话时同步清理 MySQL、Redis、OSS、Qdrant 所有关联数据
- 分页加载历史消息，第一页查询时预热 Redis

### 流式响应
- 全程使用 SSE (Server-Sent Events) 推流
- 中间具有"搜索中"、"思考中"、"正式回复"三阶段状态流转，互斥显示
- 每段 JSON chunk 包含 type 字段（content / search_results / 状态信息）
- 前端按行缓冲解析，处理粘包问题

### Markdown 渲染
- 使用 marked 库在前端渲染 Markdown 格式
- 支持加粗、列表、代码块、标题等常见格式
- 后端回复固定编码为 UTF-8，确保中文正常显示

### 用户认证
- 基于 Token 的登录认证
- 用户会话隔离，不同用户记忆互不干扰
- 内部接口使用 X-Internal-Secret 签名认证

## 快速开始

### 环境要求

- Node.js >= 18
- JDK >= 21
- Python >= 3.10
- MySQL >= 8.0
- Redis
- Qdrant（向量数据库）

### 1. 启动 Agent 服务

```bash
cd agent

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
# 编辑 .env 文件配置模型 API Key、Qdrant 连接等

# 启动服务
python main.py
# 默认运行在 http://localhost:8000
```

### 2. 启动后端服务

```bash
cd backend

# 使用 Maven 编译
mvn clean install

# 启动 Spring Boot 应用
mvn spring-boot:run
# 默认运行在 http://localhost:8080
```

### 3. 启动前端服务

```bash
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev
# 默认运行在 http://localhost:5173
```

## 环境变量配置

### Agent (.env)

| 配置项 | 说明 |
|--------|------|
| `AGENT_PORT` | Agent 服务端口 |
| `BACKEND_URL` | 后端 URL |
| `INTERNAL_SECRET` | 内部接口认证密钥 |
| `API_KEY` / `MODEL` / `API_BASE` | 文本模型配置 |
| `MULTIMODAL_MODEL` / `MULTIMODAL_API_KEY` | 多模态模型配置 |
| `OCR_MODEL` / `OCR_API_KEY` | OCR 图片提取模型 |
| `ORCHESTRATION_MODEL` | 编排器模型 |
| `QDRANT_HOST` / `QDRANT_PORT` | Qdrant 向量数据库 |
| `SEARCH_API_KEY` / `SEARCH_API_BASE` | 博查搜索 API |
| `EXPERT_MODE_ENABLED` | 专家模式开关 |
| `EXPERT_ORCHESTRATION_MODEL` | 专家模式编排器模型 |
| `EXPERT_DEEP_THINKING_MODEL` | 专家模式深度思考模型 |

### Backend (application.yml)

| 配置项 | 说明 |
|--------|------|
| `DB_USERNAME` / `DB_PASSWORD` | MySQL 数据库账号密码 |
| `ALIYUN_OSS_BUCKET` | OSS 存储桶名称 |
| `ALIYUN_OSS_KEY_ID` / `ALIYUN_OSS_SECRET` | OSS 访问密钥 |
| `ALIYUN_ASR_KEY_ID` / `ALIYUN_ASR_SECRET` | 语音识别密钥 |

## 专家模式工作流程

1. **编排器分析**：分析用户问题，判断是否需要联网搜索或深度思考
2. **工具调用循环**：最多 3 次迭代，依次执行搜索、深度思考
3. **生成回复**：编排器基于收集到的信息直接生成最终回复
4. **记忆持久化**：将对话内容提取并存储到 Qdrant

## 数据库表结构

- **user**：用户表
- **session**：会话表
- **session_detail**：会话详情（消息记录）
- **file_hash**：文件哈希去重表

## 开发说明

- 前端使用 Vite 开发服务器，支持热更新
- Agent 支持 `--reload` 模式，代码修改自动生效
- 后端使用 MyBatis-Plus，SQL 日志默认开启
- 会话 ID 以字符串形式传递，避免 JavaScript Number 精度丢失
