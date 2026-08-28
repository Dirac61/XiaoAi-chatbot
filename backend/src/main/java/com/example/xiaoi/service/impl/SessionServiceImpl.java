package com.example.xiaoi.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.example.xiaoi.entity.Session;
import com.example.xiaoi.entity.SessionDetail;
import com.example.xiaoi.mapper.SessionDetailMapper;
import com.example.xiaoi.mapper.SessionMapper;
import com.example.xiaoi.service.SessionAsyncService;
import com.example.xiaoi.service.SessionService;
import com.example.xiaoi.utils.SnowflakeUtil;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;

@Service
public class SessionServiceImpl implements SessionService {

    private static final Logger logger = LoggerFactory.getLogger(SessionServiceImpl.class);

    @Autowired
    private SessionMapper sessionMapper;

    @Autowired
    private SessionDetailMapper sessionDetailMapper;

    @Autowired
    private StringRedisTemplate redisTemplate;

    @Autowired
    private SnowflakeUtil snowflakeUtil;

    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private SessionAsyncService asyncService;

    @Autowired
    private com.example.xiaoi.service.OSSUploadService ossUploadService;

    private static final String REDIS_KEY_PREFIX = "session:";
    private static final String REDIS_TURN_COUNT_PREFIX = "session:turn:";
    private static final long REDIS_EXPIRE_DAYS = 1;
    private static final int MAX_REDIS_MESSAGES = 20;

    // 摘要触发阈值：第 10 轮开始触发，之后每 5 轮触发一次
    private static final int SUMMARY_TRIGGER_THRESHOLD = 10;
    private static final int SUMMARY_INTERVAL = 5;

    @Override
    public Long createSession(Long userId) {
        Long sessionId = snowflakeUtil.nextId();
        
        Session session = new Session();
        session.setId(sessionId);
        session.setUserId(userId);
        session.setTurnCount(0);
        session.setSummary(null);
        session.setCreatedAt(LocalDateTime.now());
        session.setUpdatedAt(LocalDateTime.now());
        
        int result = sessionMapper.insert(session);
        if (result > 0) {
            logger.info("会话创建成功: sessionId={}, userId={}", sessionId, userId);
        } else {
            logger.error("会话创建失败: sessionId={}, userId={}", sessionId, userId);
        }

        redisTemplate.opsForValue().set(REDIS_TURN_COUNT_PREFIX + sessionId, "0");
        return sessionId;
    }

    @Override
    public List<Session> getSessionsByUserId(Long userId) {
        LambdaQueryWrapper<Session> queryWrapper = new LambdaQueryWrapper<>();
        queryWrapper.eq(Session::getUserId, userId);
        queryWrapper.orderByDesc(Session::getUpdatedAt);
        return sessionMapper.selectList(queryWrapper);
    }

    /**
     * 获取会话消息列表（从 Redis 读取，同时从 MySQL 预热会话元数据）
     * 
     * 预热策略：Redis 数据可能因重启/过期而丢失，每次打开会话时从 MySQL
     * 重新加载 turn_count 和 summary 写入 Redis，确保缓存与持久化数据一致。
     * 消息列表本身由分页接口 getSessionMessagesByPage() 在第一页查询时预热。
     * 
     * @param sessionId 会话 ID
     * @return 包含 messages 的 Map
     */
    @Override
    public Map<String, Object> getSessionMessages(Long sessionId) {
        Map<String, Object> result = new HashMap<>();
        String redisKey = REDIS_KEY_PREFIX + sessionId;
        
        // 从 MySQL 预热会话元数据（turn_count + summary）到 Redis，覆盖已有值
        warmupSessionMeta(sessionId);
        
        List<String> redisMessages = redisTemplate.opsForList().range(redisKey, 0, -1);
        
        if (redisMessages != null && !redisMessages.isEmpty()) {
            redisTemplate.expire(redisKey, REDIS_EXPIRE_DAYS, TimeUnit.DAYS);
            
            try {
                List<Map<String, Object>> messages = new ArrayList<>();
                for (String msgJson : redisMessages) {
                    if (msgJson != null && !msgJson.isEmpty()) {
                        Map<String, Object> msg = objectMapper.readValue(msgJson, new TypeReference<Map<String, Object>>() {});
                        messages.add(msg);
                    }
                }
                result.put("messages", messages);
                return result;
            } catch (JsonProcessingException e) {
                logger.error("解析 Redis 消息失败: sessionId={}, 错误={}", sessionId, e.getMessage());
            }
        }

        result.put("messages", new ArrayList<>());
        return result;
    }

    /**
     * 从 MySQL 加载会话元数据并写入 Redis（缓存预热）
     * 覆盖策略：直接 set，不检查已有值，确保 Redis 与 MySQL 一致
     * @param sessionId 会话 ID
     */
    private void warmupSessionMeta(Long sessionId) {
        try {
            Session session = sessionMapper.selectById(sessionId);
            if (session == null) {
                logger.warn("会话不存在，跳过预热: sessionId={}", sessionId);
                return;
            }
            
            // 写入 turn_count 到 Redis（key: session:turn:{sessionId}）
            Integer turnCount = session.getTurnCount();
            if (turnCount != null) {
                String turnKey = REDIS_TURN_COUNT_PREFIX + sessionId;
                redisTemplate.opsForValue().set(turnKey, String.valueOf(turnCount));
                redisTemplate.expire(turnKey, REDIS_EXPIRE_DAYS, TimeUnit.DAYS);
            }
            
            // 写入 summary 到 Redis（key: session:summary:{sessionId}）
            String summary = session.getSummary();
            if (summary != null && !summary.isEmpty()) {
                String summaryKey = "session:summary:" + sessionId;
                redisTemplate.opsForValue().set(summaryKey, summary);
                redisTemplate.expire(summaryKey, REDIS_EXPIRE_DAYS, TimeUnit.DAYS);
            }
            
            logger.debug("会话元数据预热完成: sessionId={}, turnCount={}, hasSummary={}", 
                sessionId, turnCount, summary != null && !summary.isEmpty());
        } catch (Exception e) {
            logger.error("会话元数据预热失败: sessionId={}, 错误={}", sessionId, e.getMessage());
        }
    }

    /**
     * 保存消息到 Redis 和 MySQL（双层存储）
     * Redis 作为缓存（快速读写，最多保留 20 条），MySQL 作为持久化存储
     * Redis 写入同步完成（毫秒级），MySQL 写入通过 SessionAsyncService 异步执行，不阻塞请求线程
     * 注意：异步方法必须通过独立的 Bean（SessionAsyncService）调用，
     *       因为 Spring @Async 基于 AOP 代理，同类内部方法调用不经过代理会导致 @Async 失效
     * @param sessionId 会话 ID
     * @param message 消息内容（包含 role, content, timestamp, messageType, mediaUrl）
     * @param messageType 消息类型：TEXT/IMAGE/FILE/VOICE
     * @param mediaUrl 媒体文件地址（OSS URL），TEXT和VOICE类型为null
     */
    @Override
    public void saveMessage(Long sessionId, Map<String, Object> message, String messageType, String mediaUrl) {
        try {
            if (!message.containsKey("messageUuid")) {
                message.put("messageUuid", java.util.UUID.randomUUID().toString());
            }
            String messageJson = objectMapper.writeValueAsString(message);
            String redisKey = REDIS_KEY_PREFIX + sessionId;
            
            // Redis 写入（同步，毫秒级，不阻塞）
            redisTemplate.opsForList().rightPush(redisKey, messageJson);
            
            // Redis 超过 20 条时截断，只保留最近的
            Long size = redisTemplate.opsForList().size(redisKey);
            if (size != null && size > MAX_REDIS_MESSAGES) {
                redisTemplate.opsForList().trim(redisKey, size - MAX_REDIS_MESSAGES, -1);
            }
            redisTemplate.expire(redisKey, REDIS_EXPIRE_DAYS, TimeUnit.DAYS);

            String role = (String) message.get("role");
            
            // assistant 消息需要更新轮次和可能触发摘要
            if ("assistant".equals(role)) {
                incrementTurnCount(sessionId);
            }

            // MySQL 写入异步执行，通过独立 Bean 调用确保 @Async 生效
            asyncService.asyncSaveMessageToDb(sessionId, messageJson, messageType, mediaUrl);
        } catch (JsonProcessingException e) {
            logger.error("消息序列化失败: sessionId={}, 错误={}", sessionId, e.getMessage());
        }
    }

    /**
     * 仅保存占位消息到 Redis（不写 MySQL）。
     * 用于 SSE 流开始前预存 assistant 消息，确保 Agent 的 expertTrace 回写能按 UUID 扫到。
     * 不触发 asyncSaveMessageToDb，避免和用户消息的 MySQL INSERT 竞态导致顺序错乱。
     */
    @Override
    public void savePlaceholderToRedis(Long sessionId, Map<String, Object> message) {
        try {
            if (!message.containsKey("messageUuid")) {
                message.put("messageUuid", java.util.UUID.randomUUID().toString());
            }
            String messageJson = objectMapper.writeValueAsString(message);
            String redisKey = REDIS_KEY_PREFIX + sessionId;
            redisTemplate.opsForList().rightPush(redisKey, messageJson);
            Long size = redisTemplate.opsForList().size(redisKey);
            if (size != null && size > MAX_REDIS_MESSAGES) {
                redisTemplate.opsForList().trim(redisKey, size - MAX_REDIS_MESSAGES, -1);
            }
            redisTemplate.expire(redisKey, REDIS_EXPIRE_DAYS, TimeUnit.DAYS);
            logger.debug("[占位消息] 已写入 Redis（跳过 MySQL）: sessionId={}, messageUuid={}", sessionId, message.get("messageUuid"));
        } catch (JsonProcessingException e) {
            logger.error("占位消息序列化失败: sessionId={}, 错误={}", sessionId, e.getMessage());
        }
    }

    /**
     * 递增对话轮次并判断是否触发摘要提取
     * 轮次计数通过 Redis 同步递增（毫秒级），摘要提取通过异步服务执行
     */
    private void incrementTurnCount(Long sessionId) {
        String turnKey = REDIS_TURN_COUNT_PREFIX + sessionId;
        Long turnCount = redisTemplate.opsForValue().increment(turnKey);
        
        if (turnCount == null) {
            logger.error("递增轮次计数器失败: sessionId={}", sessionId);
            return;
        }

        redisTemplate.expire(turnKey, REDIS_EXPIRE_DAYS, TimeUnit.DAYS);
        
        // 异步更新轮次到 MySQL
        asyncService.asyncUpdateTurnCount(sessionId, turnCount);

        // 同步判断是否需要触发摘要，触发则异步执行（避免阻塞请求线程）
        if (shouldTriggerSummary(turnCount)) {
            // 摘要触发只打 DEBUG（每 5 轮一次的固定事件，INFO 价值低且和「摘要已保存」的异步 INFO 重复）
            logger.debug("触发摘要提取: sessionId={}, 轮次={}", sessionId, turnCount);
            // 先同步获取历史消息（从 Redis 读，毫秒级），再传给异步方法
            // 避免在异步线程中再次查询 Redis，也避免循环依赖
            Map<String, Object> sessionMessages = getSessionMessages(sessionId);
            @SuppressWarnings("unchecked")
            List<Map<String, Object>> messages = (List<Map<String, Object>>) sessionMessages.get("messages");
            asyncService.asyncExtractAndSaveSummary(sessionId, messages);
        }
    }

    /**
     * 判断当前轮次是否应该触发摘要提取
     * 规则：第 10 轮开始触发，之后每 5 轮触发一次（第 10、15、20... 轮）
     */
    private boolean shouldTriggerSummary(Long turnCount) {
        return turnCount >= SUMMARY_TRIGGER_THRESHOLD 
            && (turnCount - SUMMARY_TRIGGER_THRESHOLD) % SUMMARY_INTERVAL == 0;
    }

    /**
     * 分页获取会话消息（从 MySQL 读取）
     * 第一页查询时会预热 Redis：消息列表 + 会话元数据（turn_count + summary）
     * @param sessionId 会话 ID
     * @param pageNum 页码，从 1 开始
     * @param pageSize 每页条数
     * @return 分页结果（messages、total、pageNum、pageSize、hasNext）
     */
    @Override
    public Map<String, Object> getSessionMessagesByPage(Long sessionId, Integer pageNum, Integer pageSize) {
        Map<String, Object> result = new HashMap<>();
        String redisKey = REDIS_KEY_PREFIX + sessionId;
        
        // 每次打开会话时从 MySQL 预热 turn_count 和 summary 到 Redis
        warmupSessionMeta(sessionId);
        
        LambdaQueryWrapper<SessionDetail> queryWrapper = new LambdaQueryWrapper<>();
        queryWrapper.eq(SessionDetail::getSessionId, sessionId);
        queryWrapper.orderByDesc(SessionDetail::getCreatedAt);
        
        Page<SessionDetail> page = new Page<>(pageNum, pageSize);
        IPage<SessionDetail> sessionDetailPage = sessionDetailMapper.selectPage(page, queryWrapper);
        
        List<SessionDetail> sessionDetails = sessionDetailPage.getRecords();
        List<Map<String, Object>> messages = new ArrayList<>();
        
        if (sessionDetails != null && !sessionDetails.isEmpty()) {
            for (SessionDetail detail : sessionDetails) {
                if (detail.getMessages() != null && !detail.getMessages().isEmpty()) {
                    try {
                        Map<String, Object> msg = objectMapper.readValue(detail.getMessages(), 
                            new TypeReference<Map<String, Object>>() {});
                        messages.add(msg);
                    } catch (JsonProcessingException e) {
                        logger.error("解析 MySQL 消息失败: sessionId={}, 错误={}", sessionId, e.getMessage());
                    }
                }
            }
            
            // 第一页查询时预热 Redis 缓存
            if (pageNum == 1 && !messages.isEmpty()) {
                redisTemplate.delete(redisKey);
                
                int cacheSize = Math.min(messages.size(), pageSize);
                for (int i = cacheSize - 1; i >= 0; i--) {
                    try {
                        String msgJson = objectMapper.writeValueAsString(messages.get(i));
                        redisTemplate.opsForList().rightPush(redisKey, msgJson);
                    } catch (JsonProcessingException e) {
                        logger.error("序列化消息写入 Redis 失败: {}", e.getMessage());
                    }
                }
                redisTemplate.expire(redisKey, REDIS_EXPIRE_DAYS, TimeUnit.DAYS);
            }
        }
        
        result.put("messages", messages);
        result.put("total", sessionDetailPage.getTotal());
        result.put("pageNum", pageNum);
        result.put("pageSize", pageSize);
        result.put("hasNext", pageNum < sessionDetailPage.getPages());
        
        return result;
    }

    @Override
    public Long getTotalMessageCount(Long sessionId) {
        LambdaQueryWrapper<SessionDetail> queryWrapper = new LambdaQueryWrapper<>();
        queryWrapper.eq(SessionDetail::getSessionId, sessionId);
        return sessionDetailMapper.selectCount(queryWrapper);
    }

    @Override
    public void updateMessageContent(Long sessionId, String messageUuid, String message, String extractedText) {
        // 老 4 参数入口：保持对非扩展调用完全兼容；直接委托给 5 参数新入口（expertTrace 传 null 表示不更新该字段）
        updateMessageContent(sessionId, messageUuid, message, extractedText, null);
    }

    @Override
    public void updateMessageContent(Long sessionId, String messageUuid, String message, String extractedText, String expertTrace) {
        // 统一多字段回写入口：复用现成 /api/message/update-content 通路（已在拦截器白名单，不会 401）。
        // 参数策略：哪个字段非空就更新消息 JSON 里的哪个字段；空(null/"") 不覆盖原值。
        //   - message:        用户提问正文（用户消息 JSON.content）
        //   - extractedText:  图片提取文本（用户消息 JSON.extractedText）
        //   - expertTrace:    专家模式编排+工具执行跟踪（assistant 消息 JSON.expertTrace）
        // 设计好处：原来需要分别调用 update-content + update-expert-trace 导致两次 Redis 扫描+两次 MySQL 异步回写，
        // 现在一次扫描就把所有字段一次性合并，减少 IO；同时 expertTrace 不再需要新增 URL 导致白名单不同步。
        boolean hasMsg = message != null && !message.isEmpty();
        boolean hasExt = extractedText != null && !extractedText.isEmpty();
        boolean hasExp = expertTrace != null && !expertTrace.isEmpty();
        logger.debug("开始更新消息(多字段合并): sessionId={}, messageUuid={}, messageLen={}, extractedLen={}, expertLen={}",
            sessionId, messageUuid,
            hasMsg ? message.length() : 0,
            hasExt ? extractedText.length() : 0,
            hasExp ? expertTrace.length() : 0);

        if (!hasMsg && !hasExt && !hasExp) {
            // 防御：三个字段都空 → 没有任何实际更新意义，直接返回，避免无谓 Redis 扫描
            logger.debug("多字段回写字段全空，跳过: sessionId={}, messageUuid={}", sessionId, messageUuid);
            return;
        }
        // 【消息覆盖防御】根据本次要更新的字段决定"只能命中 role=xxx"：
        //   - extractedText → 用户侧独有字段，必须命中 role=user；
        //   - expertTrace → assistant 侧独有字段，必须命中 role=assistant；
        //   - message → 通用字段（user 正文 / assistant 回复），不限制 role；
        //   - extractedText 和 expertTrace 同时 true → 非法调用，直接 ERROR 返回。
        boolean hasUserOnlyFields = hasExt;
        boolean hasAssistantOnlyFields = hasExp;
        if (hasUserOnlyFields && hasAssistantOnlyFields) {
            logger.error("多字段回写字段组合非法：一次调用同时包含 user侧字段(extractedText) 和 assistant侧字段(expertTrace)，" +
                    "跳过以避免覆盖错位: sessionId={}, messageUuid={}", sessionId, messageUuid);
            return;
        }

        try {
            String redisKey = REDIS_KEY_PREFIX + sessionId;
            List<String> redisMessages = redisTemplate.opsForList().range(redisKey, 0, -1);

            if (redisMessages != null) {
                logger.debug("Redis中找到{}条消息", redisMessages.size());
                boolean matched = false;
                for (int i = 0; i < redisMessages.size(); i++) {
                    try {
                        Map<String, Object> msg = objectMapper.readValue(redisMessages.get(i),
                            new TypeReference<Map<String, Object>>() {});
                        String uuid = (String) msg.get("messageUuid");
                        logger.debug("检查消息[{}]: messageUuid={}", i, uuid);
                        if (messageUuid.equals(uuid)) {
                            // 【role 校验】防止 UUID 对到错误的消息：
                            //  - extractedText 更新 -> role 必须是 "user"；
                            //  - expertTrace 更新 -> role 必须是 "assistant"；
                            //  - message 更新 -> 不限制 role（user 正文 / assistant 回复都可以更新）。
                            String role = (String) msg.get("role");
                            if (hasUserOnlyFields && !"user".equals(role)) {
                                logger.error("按 UUID 命中的消息 role 非法（更新 extractedText 但 role={}），拒绝覆盖: " +
                                        "sessionId={}, messageUuid={}, index={}", role, sessionId, messageUuid, i);
                                break;
                            }
                            if (hasAssistantOnlyFields && !"assistant".equals(role)) {
                                logger.error("按 UUID 命中的消息 role 非法（更新 assistant 侧字段但 role={}），拒绝覆盖: " +
                                        "sessionId={}, messageUuid={}, index={}", role, sessionId, messageUuid, i);
                                break;
                            }
                            // 按非空策略逐个字段更新
                            if (hasMsg) msg.put("content", message);
                            if (hasExt) msg.put("extractedText", extractedText);
                            if (hasExp) {
                                // expertTrace: 先反序列化成对象再塞，避免双重 JSON 转义字符串（与 updateMessageExpertTrace 逻辑一致）
                                Object expertTraceObj;
                                try {
                                    expertTraceObj = objectMapper.readValue(expertTrace, Object.class);
                                } catch (Exception ex) {
                                    logger.warn("[专家模式] expertTrace 不是合法 JSON，降级为字符串保存: {}", ex.getMessage());
                                    expertTraceObj = expertTrace;
                                }
                                msg.put("expertTrace", expertTraceObj);
                            }
                            String updatedJson = objectMapper.writeValueAsString(msg);
                            redisTemplate.opsForList().set(redisKey, i, updatedJson);
                            logger.debug("Redis消息多字段合并更新成功: sessionId={}, messageUuid={}, index={}, fields=message[{}]|ext[{}]|exp[{}]",
                                sessionId, messageUuid, i, hasMsg, hasExt, hasExp);

                            // MySQL：一次异步回写就把三个字段的变更都同步进 DB（替代原来 2~3 次异步回写）
                            asyncService.asyncUpdateMessageContentToDb(sessionId, messageUuid, updatedJson);
                            matched = true;
                            break;
                        }
                    } catch (JsonProcessingException e) {
                        logger.error("解析Redis消息失败: {}", e.getMessage(), e);
                    }
                }
                if (!matched) {
                    logger.warn("Redis中未找到匹配 messageUuid 的消息: sessionId={}, messageUuid={}", sessionId, messageUuid);
                }
            } else {
                logger.warn("Redis中未找到会话消息: sessionId={}", sessionId);
            }
        } catch (Exception e) {
            logger.error("多字段合并更新消息失败: sessionId={}, messageUuid={}, 错误={}", sessionId, messageUuid, e.getMessage(), e);
        }
    }

    @Override
    public void updateMessageSearchResults(Long sessionId, String messageUuid, String searchResults) {
        // 搜索结果回写：每次搜索都会触发一次，降到 DEBUG；真正需要看的证据是 [聊天完成] replyLen/searchLen 汇总行
        // 搜索结果是 assistant 消息的字段（快速模式/专家模式共用），必须命中 role=assistant，避免被误写到用户消息里
        int srLen = searchResults != null ? searchResults.length() : 0;
        logger.debug("开始更新消息搜索结果: sessionId={}, messageUuid={}, searchResultsLength={}",
            sessionId, messageUuid, srLen);

        try {
            String redisKey = REDIS_KEY_PREFIX + sessionId;
            List<String> redisMessages = redisTemplate.opsForList().range(redisKey, 0, -1);

            if (redisMessages != null) {
                boolean matched = false;
                for (int i = 0; i < redisMessages.size(); i++) {
                    try {
                        Map<String, Object> msg = objectMapper.readValue(redisMessages.get(i),
                            new TypeReference<Map<String, Object>>() {});
                        String uuid = (String) msg.get("messageUuid");
                        if (messageUuid.equals(uuid)) {
                            // 【role 防御】搜索结果（searchResults）字段只能存在 assistant 消息里。
                            String role = (String) msg.get("role");
                            if (!"assistant".equals(role)) {
                                logger.error("按 UUID 命中的消息 role 非法（更新 searchResults 但 role={}），拒绝覆盖: " +
                                        "sessionId={}, messageUuid={}, index={}", role, sessionId, messageUuid, i);
                                break;
                            }
                            msg.put("searchResults", searchResults);
                            String updatedJson = objectMapper.writeValueAsString(msg);
                            redisTemplate.opsForList().set(redisKey, i, updatedJson);
                            logger.debug("Redis消息搜索结果更新成功: sessionId={}, messageUuid={}, index={}, searchLen={}",
                                sessionId, messageUuid, i, srLen);
                            asyncService.asyncUpdateMessageContentToDb(sessionId, messageUuid, updatedJson);
                            matched = true;
                            break;
                        }
                    } catch (JsonProcessingException e) {
                        logger.error("解析Redis消息失败: {}", e.getMessage(), e);
                    }
                }
                if (!matched) {
                    logger.warn("Redis中未找到匹配 searchResults 回写的 assistant 消息: sessionId={}, messageUuid={}",
                        sessionId, messageUuid);
                }
            } else {
                logger.warn("Redis中未找到消息: sessionId={}", sessionId);
            }
        } catch (Exception e) {
            logger.error("更新消息搜索结果失败: sessionId={}, messageUuid={}, 错误={}", sessionId, messageUuid, e.getMessage(), e);
        }
    }

    @Override
    public void updateMessageExpertTrace(Long sessionId, String messageUuid, String expertTrace) {
        // 兼容旧 Agent：仍可能调用 /api/message/update-expert-trace 独立 URL。
        // 不再保留独立实现，统一委托给 5 参数的合并入口（expertTrace 非空时更新即可），
        // 既避免"新增 URL 需要新 jar 白名单"的问题，也避免两条实现路径未来不同步。
        updateMessageContent(sessionId, messageUuid, null, null, expertTrace);
    }

    @Override
    public boolean deleteSession(Long sessionId) {
        // 删除会话拆成：开始/汇总各 1 条 INFO；中间每一步（OSS/MySQL 两行/Redis/Qdrant/完成）全部降 DEBUG 或合并，
        // 避免一删会话就 7~8 行 INFO 刷屏。
        logger.info("开始删除会话: sessionId={}", sessionId);
        int deletedMediaCount = 0;
        int failedMediaCount = 0;
        long sessionDetailRows = 0;
        long sessionRows = 0;

        try {
            LambdaQueryWrapper<SessionDetail> queryWrapper = new LambdaQueryWrapper<>();
            queryWrapper.eq(SessionDetail::getSessionId, sessionId);
            List<SessionDetail> sessionDetails = sessionDetailMapper.selectList(queryWrapper);

            for (SessionDetail detail : sessionDetails) {
                String mediaUrl = detail.getMediaUrl();
                if (mediaUrl != null && !mediaUrl.isEmpty()) {
                    // 使用哈希去重删除（引用计数递减，为 0 时自动删除 OSS）
                    boolean deleted = ossUploadService.deleteWithDedup(mediaUrl);
                    if (deleted) {
                        deletedMediaCount++;
                        logger.debug("OSS文件删除成功（哈希去重）: url={}", mediaUrl);
                    } else {
                        failedMediaCount++;
                        logger.warn("OSS文件删除失败: url={}", mediaUrl);
                    }
                }
            }

            sessionDetailRows = sessionDetailMapper.delete(queryWrapper);
            sessionRows = sessionMapper.deleteById(sessionId);

            String sessionKey = REDIS_KEY_PREFIX + sessionId;
            String turnKey = REDIS_TURN_COUNT_PREFIX + sessionId;
            String summaryKey = "session:summary:" + sessionId;
            String duplicateKey = "memory:duplicate:" + sessionId;

            redisTemplate.delete(sessionKey);
            redisTemplate.delete(turnKey);
            redisTemplate.delete(summaryKey);
            redisTemplate.delete(duplicateKey);
            logger.debug("删除Redis会话缓存成功: sessionId={}", sessionId);

            asyncService.asyncDeleteQdrantMemory(sessionId);
            logger.debug("异步删除Qdrant记忆数据: sessionId={}", sessionId);

            logger.info(
                    "会话删除完成: sessionId={} detailRows={} sessionRows={} mediaDeleted={} mediaFailed={}",
                    sessionId, sessionDetailRows, sessionRows, deletedMediaCount, failedMediaCount
            );
            return true;
        } catch (Exception e) {
            logger.error("删除会话失败: sessionId={}, 错误={}", sessionId, e.getMessage(), e);
            return false;
        }
    }

}
