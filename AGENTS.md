# XiaoAi 全局开发规范

## 一、项目架构

**三层架构：** 前端(Vue) → 后端(Spring) → Agent(FastAPI)

**端口约定：**
| 服务 | 端口 |
| --- | --- |
| 前端 | 5173 |
| 后端 | 8080 |
| Agent | 8000 |
| Redis | 6379 |
| MySQL | 3306 |

**数据存储：**
- Redis：消息缓存（最近20条）+ Token存储 + TTL刷新（活跃会话永不过期）
- MySQL：会话持久化 + 消息历史分页存储

---

## 二、已实现功能

| 功能 | 关键文件 |
| --- | --- |
| 聊天对话（流式响应） | ChatView.vue、ChatController.java、agent/main.py |
| 会话管理（多会话） | SessionController.java、SessionServiceImpl.java、ChatView.vue |
| 消息持久化（Redis+MySQL） | SessionServiceImpl.java、entity/SessionDetail.java |
| 历史消息分页查询 | MyBatisPlusConfig.java、SessionServiceImpl.java |
| 上下文历史消息（最近20条） | ChatController.java、agent/main.py |
| 用户鉴权（Token） | TokenInterceptor.java、InterceptorConfig.java、UserContext.java |
| 对话摘要 | agent/main.py (summarize接口) |
| 长期记忆（向量检索+BM25） | agent/services/memory_service.py |

---

## 三、技术栈

**前端：** Vue 3 + Vite + Element Plus + Vue Router + Axios

**后端：** Spring Boot 3.2.5 + Java 21 + Spring WebFlux + MyBatis Plus + Spring Data Redis + Lombok

**Agent：** FastAPI + Uvicorn + AsyncOpenAI + Qdrant + Redis + jieba

---

## 四、代码规范：日志与注释(必须用中文,一定要记得添加日志和注释)

### 4.1 日志级别
- **ERROR**：异常，流程中断
- **WARNING**：流程继续但结果异常（空内容、超时重试）
- **INFO**：关键节点（请求入口、调用成功、流结束）
- **DEBUG**：排查细节（原始chunk、每条history）

### 4.2 日志规范
- 用 SLF4J（Java）/ logging（Python），不要用 System.out.println
- 占位符用 `{}`（不是 %s），避免字符串拼接
- 长文本用 `substring(0, 50)` 截断或放 DEBUG
- 不要打印完整 Token/API Key/隐私信息

### 4.3 注释规范
- 每个类/方法顶部：说明职责、入参、返回值
- 复杂逻辑处：说明设计意图（如 Redis 截断策略）
- 防御性判断处：说明为什么要判断
- 不要写无意义注释（如 // 加一）

### 4.4 反模式
- ❌ 不要吞异常（空 catch 块）
- ❌ 不要在 lambda 中修改外部普通变量（用 Atomic*）
- ❌ 不要上来直接改代码，先说明方案

---

## 五、开发流程约定

**实现前：** 先说明「功能描述」和「实现方式」

**实现后：** 更新文档、添加日志与注释

**关键注意事项：**
1. 会话ID用雪花算法生成，返回前端转字符串
2. 上下文顺序：system → history → 当前user message
3. MyBatis Plus需手动注册PaginationInnerInterceptor