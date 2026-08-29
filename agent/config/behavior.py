# -*- coding: utf-8 -*-
"""
config.behavior：行为参数 / 阈值 / 温度 / 截断长度 / 重试次数 / 权重 等"小配置"。
和 config.settings（只放环境变量读取的服务地址/密钥/模型名）严格区分：
    - settings.py：密钥、端口、URL、模型名（来自 os.getenv / .env）
    - behavior.py：纯业务调参（温度、top_k、长度上限、重试、权重），不需要环境变量

⚠ 修改本文件必须同步验证：
   - 长度/截断：main.py 各处切片上限、memory.py 文本约束
   - 温度 / max_tokens：各模型调用处 temperature / max_tokens
   - 混合搜索权重：memory_service.py 混合打分公式；若调权记得改注释说明效果
"""

# ==========================================
# 1. 文本截断长度（字符级）
# ==========================================

# 图片/文件提取文本（DOCX/PDF/TXT/多图 OCR）统一截断上限
# 原硬编码：[:3000] 出现多处（main.py L569 / L637 / L680 / L706 / L1688）
MEDIA_EXTRACTED_MAX_LEN = 3000

# 快速模式编排器的 context_text（上下文）截断上限
# 原硬编码：main.py L1332 / L1400 [:2000]
FAST_ORCH_CONTEXT_MAX_LEN = 2000

# 单条历史消息在「喂给编排器 / reply_directly」时的单条截断上限
# 原硬编码：main.py L1610 / L1985 [:500]
HISTORY_SNIPPET_MAX_LEN_EACH = 500

# 编排器 / 专家模式日志里 analysis 的打印截断字数
# 原硬编码：main.py L2277 [:80]
LOG_ANALYSIS_TRUNCATE_LEN = 80

# 请求入口日志里，用户消息打印字数上限（避免刷屏）
# 原硬编码：main.py L933 / L1562 [:100]
LOG_USER_MESSAGE_TRUNCATE_LEN = 100


# ==========================================
# 2. 模型调用：温度 / max_tokens / 重试 / 超时
# ==========================================

# --- OCR / 文件提取模型 ---
OCR_TEMPERATURE = 0.3  # 原 main.py L762 / L893

# --- 快速模式编排器（need_search 判断）---
FAST_ORCH_TEMPERATURE = 0.3         # 原 main.py L1351
FAST_ORCH_MAX_RETRIES = 2           # 原 main.py L1336 / L1698：首次 stream，失败后非流式重试

# --- 专家模式编排器（单步决策）---
EXPERT_ORCH_TEMPERATURE = 0.7       # 原 main.py L1713
EXPERT_ORCH_MAX_TOKENS = 3000       # 原 main.py L1714
EXPERT_ORCH_MAX_RETRIES = 2         # 原 main.py L1698

# --- 深度思考模型（FINAL）---
DEEP_THINKING_TEMPERATURE = 0.3     # 原 main.py L1910（与 prompts/deep_thinking.py 保持同步，双保险）

# --- reply_directly 简易回复模型 ---
REPLY_DIRECTLY_TEMPERATURE = 0.7    # 原 main.py L2011
REPLY_DIRECTLY_MAX_TOKENS = 2000    # 原 main.py L2012

# --- /summarize 摘要生成 ---
SUMMARIZE_TEMPERATURE = 0.3         # 原 main.py L2470

# --- 记忆提取模型 ---
MEMORY_EXTRACTION_TEMPERATURE = 0.3       # 原 memory_service.py L367
MEMORY_EXTRACTION_MAX_TOKENS = 2000       # 原 memory_service.py L368
MEMORY_EXTRACTION_MAX_RETRIES = 2         # 原 memory_service.py L358

# 记忆提取 fallback 模型名（extraction_client 未配置时的默认模型）
MEMORY_EXTRACTION_FALLBACK_MODEL = "qwen3.7-plus"   # 原 memory_service.py L346

# 记忆内容字数上限 / 条数（约束）
MEMORY_CONTENT_DEFAULT_MAX_LENGTH = 80    # 原 memory_service.py L326
MEMORY_COUNT_BASELINE_NO_MEDIA = 3        # 原 memory_service.py L325 max(5, 3 + media_count)
MEMORY_COUNT_BASELINE_MINIMUM = 5


# 通用 httpx / AsyncOpenAI timeout（避免多个 client 各写各的数字）
# 读取主模型/多模态/OCR：30s；编排器 JSON 输出快：15s；深度思考生成慢：60s；connect 固定 5s
CLIENT_TIMEOUT_READ_GENERAL = 30.0
CLIENT_TIMEOUT_CONNECT_DEFAULT = 5.0
CLIENT_TIMEOUT_READ_ORCHESTRATION = 15.0
CLIENT_TIMEOUT_READ_DEEP_THINKING = 60.0

# --- Agent → 后端回写接口 HTTP 超时 ---
# 原 main.py L1506 / L1537 timeout=30.0；L2206 httpx.Timeout(10.0, connect=3.0)
# 统一收敛：读超时 30s（避免 JVM GC / DB 慢时回写丢数据），连接超时 3s（快速感知后端挂了）
BACKEND_INTERNAL_API_TIMEOUT = 30.0
BACKEND_INTERNAL_API_CONNECT_TIMEOUT = 3.0

# --- 搜索服务（博查 HTTP）超时 ---
SEARCH_HTTP_TIMEOUT = 30.0          # 原 services/search_service.py L43


# ==========================================
# 3. 记忆 / 搜索：top_k / 条数 / 权重
# ==========================================

# --- 记忆检索（快速模式 / 专家模式 INIT / memory_search 工具）共用 top_k ---
MEMORY_SEARCH_DEFAULT_TOP_K = 5     # 原 main.py L450 / L965 / L2228  top_k=5

# Qdrant 混合搜索：稠密向量召回候选上限（同时也是单次 qdrant query_points limit）
MEMORY_QDRANT_INITIAL_LIMIT_RATIO = 1  # 目前实现是 limit=top_k（留常量便于之后改扩召回）

# BM25 算法参数（memory_service._calculate_bm25）
BM25_K1 = 1.2                        # 原 memory_service.py L185
BM25_B = 0.75                        # 原 memory_service.py L186
BM25_AVG_DOC_LEN_HINT = 100          # 原简化 BM25 里 "100" 字面量（memory_service.py L190 / b*len/100）

# 关键词打印截断字数（调试日志关键词展示上限）
BM25_LOG_KEYWORDS_TOP_N = 5          # 原 memory_service.py L617 keywords[:5]、L648 keywords[:5]

# 混合打分权重（memory_service.search_memories 合并公式）
# score_combined = dense * DENSE_SCORE_WEIGHT + bm25_contrib * BM25_WEIGHT + importance * IMPORTANCE_WEIGHT
# 原实现：
#   DENSE 分在初始化时已作为 result_dict[id]["score"] 入字典（1.0 倍）；
#   BM25 叠加：point.score * bm25_scores[keyword] * 0.3
#   importance 叠加：importance_score * 0.1
# → 实际语义是 "1.0 基础 dense + 0.3 BM25 + 0.1 importance"
HYBRID_DENSE_BASE_WEIGHT = 1.0
HYBRID_BM25_WEIGHT = 0.3
HYBRID_IMPORTANCE_WEIGHT = 0.1

# Rerank 过滤阈值（memory_service.search_memories 返回值的截断过滤阈值）
# 原代码未启用（保留作后续扩展钩子，目前只重排不取阈值过滤）
HYBRID_RERANK_MIN_SCORE = 0.0


# ==========================================
# 4. 状态机 / 协议参数
# ==========================================

# 专家模式 collect_tools 最大迭代次数（超过强制 FINAL deep_thinking）
# 原 main.py L2208 使用 EXPERT_MAX_ITERATIONS（走 settings / env；但 Python dataclass ExpertState 还声明了一个默认值 2 给兜底）
EXPERT_STATE_DEFAULT_MAX_ITERATIONS = 2

# ExpertState 构造时的 history 默认值（不要在 dataclass 里直接用可变默认值 []，这里放常量）
EXPERT_STATE_DEFAULT_HISTORY: list = []  # 仅作语义常量（实际代码用 list(history or []) 保证每请求新列表）


# ==========================================
# 5. 分词 / 停用词（memory_service._tokenize）
# ==========================================

# 停用词集合（中文 + 常见中文语气词 + 英文常见停用词的核心子集）
# 原硬编码：memory_service.py L162
STOPWORDS = {
    # ---- 中文 ----
    '的', '了', '是', '在', '我', '有', '和', '就', '不', '人', '都',
    '一', '一个', '上', '也', '很', '到', '说', '要', '去', '你', '会',
    '着', '没有', '看', '好', '自己', '这', '那', '那是',
    '但是', '所以', '因为', '如果', '虽然', '而且', '或者', '还是',
    '的话', '吗', '呢', '啊', '哦', '嗯', '吧', '呀', '哇', '哈',
    '嘿', '哼', '唉', '咦', '唔',
    # ---- 英文常见停用词 ----
    'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
    'and', 'or', 'but', 'if', 'then', 'else', 'of', 'to', 'in', 'on',
    'at', 'by', 'for', 'with', 'about', 'as', 'into', 'through',
    'this', 'that', 'these', 'those', 'i', 'you', 'he', 'she', 'it',
    'we', 'they', 'what', 'which', 'who', 'whom', 'how', 'when', 'where',
    'why', 'not', 'no', 'do', 'does', 'did', 'have', 'has', 'had',
    'will', 'would', 'can', 'could', 'should', 'may', 'might', 'must',
}

# 分词后单 token 最小长度（小于则过滤；原硬编码 len(token) >= 2）
TOKEN_MIN_LEN = 2


# ==========================================
# 6. 文件提取后缀白名单（纯文本类型列表）
#    main.py L796 硬编码扩展名数组
# ==========================================

# 支持直接 response.text 读取的纯文本扩展名
PLAIN_TEXT_EXTENSIONS = (".txt", ".md", ".json", ".csv", ".xml")

# 所有受支持的文件扩展名集合（FILE 类型校验时使用：docx / pdf + plain text）
SUPPORTED_FILE_EXTENSIONS = (".docx", ".pdf") + PLAIN_TEXT_EXTENSIONS


# ==========================================
# 7. URL 前缀判断（媒体 URL 合法性校验）
#    main.py L739 / L744 / L786 字面量
# ==========================================

# data URI 前缀（base64 内嵌图片）
URL_PREFIX_DATA_IMAGE = "data:image"
# 远程 http/https 图片/文件前缀
URL_PREFIX_HTTP = "http"
