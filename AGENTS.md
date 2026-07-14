# XiaoAi 全局开发规范

## 一、项目架构

`
┌──────────────┐   HTTP / JSON   ┌──────────────┐   OpenAI 兼容协议   ┌──────────────┐
│   前端 (Vue)  │ ──────────────▶ │   后端(Spring) │ ──────────────────▶ │   Agent     │
│              │ ◀────────────── │              │ ◀────────────────── │  (FastAPI)   │
│              │   流式响应 +    │              │      流式响应        │ → 大语言模型  │
│              │  会话/分页接口  │              │                     │              │
└──────────────┘                └──────────────┘                     └──────────────┘
                                      │  │
                                     ┌▼──▼┐
                           Redis (消息缓存+TTL)
                           MySQL (会话+消息持久化)
                                 └────┘
`

**端口约定：**
- 前端：5173
- 后端：8080
- Agent：8000
- Redis：6379
- MySQL：3306

---

## 二、已实现功能与实现方式

### 2.1 聊天对话

**功能描述：** 用户在前端发送消息，经过后端转发到 Agent，Agent 调用大语言模型 API，以流式方式返回响应。

**实现方式：**
- **前端**：ChatView.vue 中用 etch 发送 POST 请求，用 ReadableStream.getReader() + TextDecoder 逐块读取流式响应，实时追加到 bot 消息内容中。
- **后端**：ChatController.java 用 WebClient（非阻塞式）调用 Agent 的 /chat 接口，以 StreamingResponseBody 流式返回给前端。先从 Redis/MySQL 获取最近 20 条历史消息，再保存当前用户消息，再发给 Agent。
- **Agent**：main.py 用 FastAPI 的 StreamingResponse + AsyncOpenAI 客户端，以 stream=True 调用大语言模型 API，sync for 遍历每个 chunk，逐块 yield。
- **关键文件**：ChatView.vue、ChatController.java、SessionServiceImpl.java、gent/main.py

### 2.2 会话管理（多会话）

**功能描述：** 用户可以创建多个独立会话，每个会话有独立的消息历史，会话列表按更新时间排序。

**实现方式：**
- **后端**：SessionController.java 提供 /api/sessions 获取会话列表，SessionServiceImpl.java 用 MyBatis Plus 查询 session 表，按 updated_at 倒序。创建会话时用雪花算法（SnowflakeUtil.java）生成 Long 类型 ID。
- **前端**：ChatView.vue 左侧显示会话列表，点击切换会话，切换时调用分页接口加载消息。
- **关键文件**：SessionController.java、SessionServiceImpl.java、ChatView.vue、entity/Session.java

### 2.3 消息持久化（MySQL + Redis 双层存储）

**功能描述：** 用户消息同时保存到 MySQL（持久化）和 Redis（缓存），读取时优先从 Redis 读取，Redis 无数据时从 MySQL 加载。

**实现方式：**
- **先存 Redis**：saveMessage() 中先 opsForList().rightPush() 把消息 JSON 推入 Redis List，再 expire() 设置 1 天 TTL。
- **再存 MySQL**：把消息 JSON 写入 session_detail 表的 messages 字段，每条记录对应一条消息。
- **截断策略**：Redis List 超过 20 条时用 	rim() 截断，只保留最近 20 条，避免 Redis 内存无限增长。
- **TTL 刷新**：每次调用 getSessionMessages() 时重新设置 TTL，活跃会话永不过期。
- **更新会话时间**：每次保存消息后更新 session 表的 updated_at，用于会话列表排序。
- **关键文件**：SessionServiceImpl.java、entity/SessionDetail.java

### 2.4 历史消息分页查询

**功能描述：** 打开会话时只加载第一页消息（避免一次加载太多），前端上拉时请求下一页。

**实现方式：**
- **后端**：getSessionMessagesByPage() 用 MyBatis Plus 分页插件，按 created_at 倒序查询。查询第一页后如果 Redis 没有缓存，把结果预热到 Redis 中（只存最近 20 条）。
- **分页插件配置**：MyBatisPlusConfig.java 中注册 MybatisPlusInterceptor + PaginationInnerInterceptor。
- **启动类**：XiaoAiApplication.java 添加 @MapperScan("com.example.xiaoi.mapper") 扫描 mapper 接口。
- **前端**：ChatView.vue 监听滚动事件，滚动条到顶部时请求下一页，把消息追加到列表前面。
- **关键文件**：MyBatisPlusConfig.java、SessionServiceImpl.java、SessionController.java、ChatView.vue

### 2.5 上下文历史消息

**功能描述：** 发送新消息时，把最近 20 条历史消息一起发给 Agent，让模型理解对话上下文。

**实现方式：**
- **后端**：ChatController.chat() 中先调用 sessionService.getSessionMessages(sessionId) 从 Redis 读取历史消息，取出最近 20 条放入 history 数组，再保存当前用户消息到 Redis/MySQL。
- **Agent**：main.py 中遍历 history 数组，按顺序拼入 messages（system → history user/assistant → 当前 user message）。
- **关键文件**：ChatController.java、gent/main.py

### 2.6 用户鉴权（Token）

**功能描述：** 前端登录获取 token，后续请求自动携带 token，后端拦截器校验。

**实现方式：**
- **前端**：登录后把 token 存到 localStorage，每次请求在 header 中加入 Authorization。
- **后端**：TokenInterceptor.java 拦截所有 /api/** 请求（除登录接口），校验 token，把用户 ID 存入 UserContext。
- **拦截器注册**：InterceptorConfig.java 实现 WebMvcConfigurer，注册 TokenInterceptor。
- **关键文件**：LoginController.java、TokenInterceptor.java、InterceptorConfig.java、UserContext.java

### 2.7 流式响应优化（WebClient 替代 HttpURLConnection）

**功能描述：** 最初用 HttpURLConnection 出现 "Premature EOF" 错误，改用 Spring WebFlux 的 WebClient 处理流式响应。

**实现方式：**
- **配置**：WebClientConfig.java 创建 WebClient Bean，设置 baseUrl 为 Agent 地址。
- **调用**：ChatController.java 中用 webClient.post().bodyValue().retrieve().bodyToFlux(String.class).subscribe() 接收流式数据。
- **Lambda 变量问题**：sessionId 通过三元运算符一次性赋值，计数器 chunkCount 用 AtomicInteger 避免 "从 lambda 引用的本地变量必须是最终变量" 编译错误。
- **关键文件**：WebClientConfig.java、ChatController.java

---

## 三、前端

### 3.1 技术栈
- Vue 3 + Vite
- Element Plus（UI 组件库）
- Vue Router（路由）
- Axios（HTTP 客户端）

### 3.2 启动方式
`ash
cd frontend
npm install
npm run dev
`

### 3.3 关键页面
- ChatView.vue：聊天主页面，左侧会话列表 + 右侧消息区 + 底部输入框
- LoginView.vue：登录页面（如存在）

---

## 四、后端（Spring Boot）

### 4.1 技术栈
- Spring Boot 3.2.5 + Java 21
- Spring WebFlux（WebClient 用于流式调用）
- MyBatis Plus（ORM + 分页）
- Spring Data Redis（缓存）
- Lombok

### 4.2 启动方式
`ash
cd backend
mvn spring-boot:run
`

### 4.3 关键接口

| 接口 | 方法 | 描述 |
| --- | --- | --- |
| /api/chat | POST | 发送聊天消息，流式响应 |
| /api/sessions | GET | 获取当前用户的会话列表 |
| /api/session/messages | GET | 分页获取会话消息 |
| /api/health | GET | 健康检查 |
| /api/login | POST | 用户登录（如存在） |

---

## 五、Agent（FastAPI）

### 5.1 技术栈
- FastAPI + Uvicorn
- OpenAI Python SDK（AsyncOpenAI，兼容任意 OpenAI 协议 API）
- Pydantic（请求校验）

### 5.2 启动方式
`ash
cd agent
pip install -r requirements.txt
python main.py
`

### 5.3 环境变量
- API_KEY：大语言模型 API Key
- MODEL：模型名称
- API_BASE：API 基地址（默认 OpenAI）

### 5.4 关键接口

| 接口 | 方法 | 描述 |
| --- | --- | --- |
| /health | GET | 健康检查 |
| /chat | POST | 聊天接口，接收 message + history，流式返回 |

---

## 六、代码规范：日志与注释(必须用中文)

### 6.1 必须加日志的位置

| 位置 | 级别 | 示例 |
| --- | --- | --- |
| 接口入口（每个 Controller 方法） | INFO | logger.info("收到聊天请求: sessionId={}, message={}", sessionId, message) |
| 关键 Service 方法入口 | INFO | logger.info("获取会话消息: sessionId={}", sessionId) |
| 关键变量构建完成 | INFO | logger.info("构建 messages 完成，共 {} 条历史消息", history.size()) |
| 外部 API 调用成功 | INFO | logger.info("Agent 响应状态: {}", status) |
| 每个 chunk 收到内容 | INFO/DEBUG | logger.info("Chunk {}: {}", n, content) |
| 流处理完成 | INFO | logger.info("流式传输完成: sessionId={}", sessionId) |
| 收到空结果 | WARNING | logger.warn("Agent 返回空内容: sessionId={}", sessionId) |
| 异常捕获 | ERROR | logger.error("调用 Agent 失败: {}", e.getMessage(), e) |
| 配置加载（启动时） | INFO | logger.info("Redis 连接配置: host={}, port={}", host, port) |
| 循环内细节（history 拼接等） | DEBUG | logger.debug("加入历史消息: role={}, content={}", role, content.substring(0, 50)) |
| 原始 chunk/响应结构 | DEBUG | logger.debug("原始响应: {}", rawChunk) |

> **Java 约定**：用 org.slf4j.Logger，占位符用 {}（不是 %s），避免字符串拼接。

### 6.2 必须加注释的位置

| 位置 | 注释内容 |
| --- | --- |
| 每个类顶部 | 说明类的职责 |
| 每个 public 方法顶部 | 说明方法做什么、入参含义、返回值含义 |
| 构建 messages/context 前 | 说明数据顺序约定 |
| 外部 API 调用前 | 说明参数含义（如 stream=True 的影响） |
| 防御性判断处 | 说明为什么要判断（可能为 null、字段缺失、超过阈值） |
| 关键变量用途 | 说明变量是做什么的（特别当变量名不够自解释时） |
| try/except 边界 | 说明 try 覆盖了哪些可能失败的操作 |
| 复杂业务逻辑处 | 说明设计意图（如 Redis 截断策略、分页预热逻辑） |

### 6.3 反模式（不要这样做）

❌ 不要打印敏感信息（完整 Token/API Key、用户隐私等）
❌ 不要把长文本全打到 INFO（用 substring(0, 50) 截断或放 DEBUG）
❌ 不要用 System.out.println 代替 logger，统一用 SLF4J
❌ 不要写无意义的注释（如 // 加一），只写"为什么"而不是"做什么"
❌ 不要吞异常（空 catch 块），至少 logger.error 记录
❌ 不要在 lambda 中修改外部普通变量，用 AtomicInteger/AtomicReference 或数组

### 6.4 日志级别使用原则

- **ERROR**：程序发生异常，流程无法继续
- **WARNING**：流程能继续，但结果可能不符合预期（空内容、超时重试、Redis 未命中）
- **INFO**：业务正常流转的关键节点（请求入口、调用成功、流结束、保存成功）
- **DEBUG**：排查问题用的细节信息（原始 chunk、每条 history、变量中间值）

---

## 七、开发新功能的流程约定

> **重要：** 任何新增/修改功能前，必须先按下面格式说明，再动手改代码。

### 7.1 开始实现前，先说清楚两点

`
【功能描述】一句话说清楚要做什么
【实现方式】准备怎么实现（涉及哪些文件、用什么技术、关键步骤）
`

**示例：**

`
【功能描述】实现"对话摘要"功能，每 5 轮对话提取一次结构化摘要
【实现方式】
1. 在 session 表增加 summary 字段（TEXT），存储摘要 JSON
2. 在 SessionServiceImpl 加 extractSummary() 方法，判断轮次 ≥ 10 且 (轮次%5==0) 时触发
3. 调用 Agent 的 /chat 接口（新增 summary 模式参数），让 LLM 输出 JSON 格式摘要
4. 用 ThreadPoolExecutor 异步写入 MySQL，不阻塞用户的流式响应
5. 在 agent/main.py 增加 summary 系统提示词模板，输出严格 JSON
6. 在 README.md 中记录摘要 JSON 的结构约定
`

### 7.2 代码修改完成后，要同步更新

1. **README.md 中的「已实现功能」列表**：把刚完成的功能加进去
2. **关键文件路径**：确保在功能说明中标出
3. **日志与注释**：确保新代码按第六部分规范添加

### 7.3 反模式（不要这样做）

❌ 不要上来直接就改代码，事前没有任何说明
❌ 不要只说"我来实现一下"，没有具体方案就动手
❌ 不要实现完就完事了，文档中要同步更新

---

## 八、开发注意事项

1. **雪花 ID**：会话 ID 用 SnowflakeUtil 生成，返回给前端时转字符串（JS Number 精度不足）
2. **Redis TTL**：每次读取会话消息时刷新 TTL，活跃会话不过期
3. **Redis 截断**：最多存 20 条，超过用 	rim() 移除最早的
4. **流式响应**：前端用 ReadableStream 读取，后端用 WebClient + Flux，Agent 用 sync for + yield
5. **Java Lambda**：在 lambda 中修改外部变量要用 Atomic* 类型，或通过数组/对象引用传递
6. **上下文顺序**：发给模型的 messages 必须按 system → user → assistant → user → assistant ... 顺序，最后一条是当前用户消息
7. **CORS**：WebConfig.java 已配置允许前端域名跨域
8. **分页**：MyBatis Plus 需手动注册 PaginationInnerInterceptor，否则分页不生效
