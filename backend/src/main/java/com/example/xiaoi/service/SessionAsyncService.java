package com.example.xiaoi.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.example.xiaoi.entity.Session;
import com.example.xiaoi.entity.SessionDetail;
import com.example.xiaoi.mapper.SessionDetailMapper;
import com.example.xiaoi.mapper.SessionMapper;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;

import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.time.LocalDateTime;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;

/**
 * 会话相关异步操作服务
 * 独立成类的目的：Spring @Async 基于 AOP 代理实现，同类内部方法调用不经过代理会导致 @Async 失效。
 * 必须将异步方法放在独立的 Bean 中，通过依赖注入调用才能让 @Async 真正生效。
 */
@Service
public class SessionAsyncService {

    private static final Logger logger = LoggerFactory.getLogger(SessionAsyncService.class);

    @Autowired
    private SessionMapper sessionMapper;

    @Autowired
    private SessionDetailMapper sessionDetailMapper;

    @Autowired
    private StringRedisTemplate redisTemplate;

    @Autowired
    private ObjectMapper objectMapper;

    @Value("${agent.url:http://localhost:8000}")
    private String agentUrl;

    @Value("${internal.secret:xiaoi-internal-api-secret-2026}")
    private String internalSecret;

    private static final String REDIS_SUMMARY_PREFIX = "session:summary:";
    /** 会话被删除时在 Redis 立的墓碑 key 前缀（与 SessionServiceImpl 保持一致） */
    private static final String REDIS_DELETED_TOMBSTONE_PREFIX = "session:deleted:";
    private static final long REDIS_EXPIRE_DAYS = 1;
    private static final int MAX_SUMMARY_LENGTH = 500;

    /**
     * 判断会话是否已被删除（通过 Redis 墓碑标记）。
     * 异步线程的入口双保险：因为异步任务是在 @Async 提交时就已经"脱离"了同步线程的墓碑判断，
     * 在实际写入前再查一次墓碑，能覆盖"提交任务→会话被删→线程池调度执行"这种延迟窗口。
     *
     * @param sessionId 会话 ID
     * @return true=会话已删除，应跳过本次异步写入
     */
    private boolean isSessionDeleted(Long sessionId) {
        if (sessionId == null) {
            return true;
        }
        String tombstoneKey = REDIS_DELETED_TOMBSTONE_PREFIX + sessionId;
        Boolean exists = redisTemplate.hasKey(tombstoneKey);
        return Boolean.TRUE.equals(exists);
    }

    /**
     * 异步保存消息到 MySQL 并更新会话时间
     * MySQL 写入相对较慢，异步执行避免阻塞请求线程
     * @param sessionId 会话 ID
     * @param messageJson 消息 JSON 字符串
     * @param messageType 消息类型：TEXT/IMAGE/FILE/VOICE
     * @param mediaUrl 媒体文件地址（OSS URL），TEXT和VOICE类型为null
     */
    @Async("summaryExecutor")
    public void asyncSaveMessageToDb(Long sessionId, String messageJson, String messageType, String mediaUrl) {
        // 【墓碑双保险】异步线程实际执行前，再次确认会话未被删除；命中则不写孤儿 session_detail 行
        if (isSessionDeleted(sessionId)) {
            logger.warn("[墓碑命中-asyncSaveMessageToDb] 会话已删除，跳过异步持久化: sessionId={}", sessionId);
            return;
        }
        try {
            SessionDetail sessionDetail = new SessionDetail();
            sessionDetail.setSessionId(sessionId);
            sessionDetail.setMessages(messageJson);
            sessionDetail.setMessageType(messageType != null ? messageType : "TEXT");
            sessionDetail.setMediaUrl(mediaUrl);
            sessionDetail.setCreatedAt(LocalDateTime.now());
            sessionDetail.setUpdatedAt(LocalDateTime.now());
            
            sessionDetailMapper.insert(sessionDetail);

            Session session = new Session();
            session.setId(sessionId);
            session.setUpdatedAt(LocalDateTime.now());
            sessionMapper.updateById(session);
        } catch (Exception e) {
            logger.error("异步保存消息到 MySQL 失败: sessionId={}, 错误={}", sessionId, e.getMessage());
        }
    }

    /**
     * 异步递增对话轮次到 MySQL
     * 使用 SQL SET turn_count = turn_count + 1 原子递增，避免用 Redis 数据覆盖 MySQL
     * 防止因 Redis 数据丢失/重置导致 MySQL 轮次被错误回退
     * @param sessionId 会话 ID
     * @param turnCount Redis 中的当前轮次（仅用于日志，不直接写入 MySQL）
     */
    @Async("summaryExecutor")
    public void asyncUpdateTurnCount(Long sessionId, Long turnCount) {
        // 【墓碑双保险】异步线程执行前再次确认会话存活：会话删了递增轮次已无意义，还会 updateById 触碰被删会话的 update（虽然行已没了，但少一次 DB 访问）
        if (isSessionDeleted(sessionId)) {
            logger.warn("[墓碑命中-asyncUpdateTurnCount] 会话已删除，跳过异步轮次递增: sessionId={}", sessionId);
            return;
        }
        try {
            // 用 setSql("turn_count = turn_count + 1") 实现数据库端原子递增
            // 不读取 MySQL 当前值再写入，避免并发问题或 Redis 脏数据覆盖
            LambdaUpdateWrapper<Session> updateWrapper = new LambdaUpdateWrapper<>();
            updateWrapper.eq(Session::getId, sessionId);
            updateWrapper.setSql("turn_count = turn_count + 1");
            updateWrapper.set(Session::getUpdatedAt, LocalDateTime.now());
            int rows = sessionMapper.update(null, updateWrapper);
            
            if (rows > 0) {
                logger.debug("轮次递增成功: sessionId={}, Redis值={}", sessionId, turnCount);
            } else {
                logger.warn("会话不存在，轮次递增无影响行: sessionId={}", sessionId);
            }
        } catch (Exception e) {
            logger.error("异步递增对话轮次失败: sessionId={}, 错误={}", sessionId, e.getMessage());
        }
    }

    /**
     * 异步提取并保存对话摘要
     * 内部会调用 Agent 的 /summarize 接口（HTTP 阻塞调用，最长 60s），必须异步执行
     * @param sessionId 会话 ID
     * @param messages 当前会话的历史消息列表（从 Redis 获取后传入，避免循环依赖）
     */
    @Async("summaryExecutor")
    public void asyncExtractAndSaveSummary(Long sessionId, List<Map<String, Object>> messages) {
        // 【墓碑双保险】会话已删除，再调 Agent 的 /summarize 接口是纯浪费（60s 阻塞 + 不会写回 DB）
        if (isSessionDeleted(sessionId)) {
            logger.warn("[墓碑命中-asyncExtractAndSaveSummary] 会话已删除，跳过摘要提取: sessionId={}", sessionId);
            return;
        }
        try {
            String existingSummary = redisTemplate.opsForValue().get(REDIS_SUMMARY_PREFIX + sessionId);

            Map<String, Object> requestBody = new HashMap<>();
            requestBody.put("messages", messages);
            requestBody.put("existing_summary", existingSummary);

            String jsonBody = objectMapper.writeValueAsString(requestBody);
            String summary = callAgentSummary(jsonBody);

            if (summary != null && !summary.isEmpty()) {
                if (summary.length() > MAX_SUMMARY_LENGTH) {
                    summary = summary.substring(0, MAX_SUMMARY_LENGTH);
                }

                redisTemplate.opsForValue().set(REDIS_SUMMARY_PREFIX + sessionId, summary);
                redisTemplate.expire(REDIS_SUMMARY_PREFIX + sessionId, REDIS_EXPIRE_DAYS, TimeUnit.DAYS);
                logger.info("摘要已保存: sessionId={}, 长度={}", sessionId, summary.length());

                // 此处同类内部调用 asyncUpdateSummary，@Async 不会生效（不经过代理）
                // 但由于当前方法本身已在 summaryExecutor 线程中异步执行，
                // asyncUpdateSummary 会在当前异步线程中同步完成，不会阻塞请求线程，符合预期
                asyncUpdateSummary(sessionId, summary);
            } else {
                logger.warn("Agent 返回空摘要: sessionId={}", sessionId);
            }
        } catch (Exception e) {
            logger.error("提取摘要失败: sessionId={}, 错误={}", sessionId, e.getMessage());
        }
    }

    /**
     * 异步更新对话摘要到 MySQL
     * @param sessionId 会话 ID
     * @param summary 摘要内容
     */
    @Async("summaryExecutor")
    public void asyncUpdateSummary(Long sessionId, String summary) {
        try {
            Session session = sessionMapper.selectById(sessionId);
            if (session != null) {
                session.setSummary(summary);
                session.setUpdatedAt(LocalDateTime.now());
                sessionMapper.updateById(session);
            } else {
                logger.warn("会话不存在，跳过摘要更新: sessionId={}", sessionId);
            }
        } catch (Exception e) {
            logger.error("异步更新对话摘要失败: sessionId={}, 错误={}", sessionId, e.getMessage());
        }
    }

    /**
     * 异步更新消息内容到 MySQL
     * 通过消息UUID精确定位消息记录，解析messages字段中的JSON找到匹配的messageUuid
     * @param sessionId 会话 ID
     * @param messageUuid 消息唯一标识
     * @param updatedJson 更新后的消息JSON
     */
    @Async("summaryExecutor")
    public void asyncUpdateMessageContentToDb(Long sessionId, String messageUuid, String updatedJson) {
        // 【墓碑双保险】最关键：此处存在"找不到匹配行自动 INSERT"的 upsert 逻辑，
        // 一旦会话被删除且 detail 表先被清空，这里会插入一行孤儿 session_detail（session_id 指向不存在的会话）。
        // 入口查墓碑，从源头阻止这种孤儿行产生。
        if (isSessionDeleted(sessionId)) {
            logger.warn("[墓碑命中-asyncUpdateMessageContentToDb] 会话已删除，跳过异步回写: sessionId={}, messageUuid={}",
                    sessionId, messageUuid);
            return;
        }
        try {
            LambdaQueryWrapper<SessionDetail> queryWrapper = new LambdaQueryWrapper<>();
            queryWrapper.eq(SessionDetail::getSessionId, sessionId);
            queryWrapper.orderByDesc(SessionDetail::getId);
            
            java.util.List<SessionDetail> sessionDetails = sessionDetailMapper.selectList(queryWrapper);
            if (sessionDetails != null && !sessionDetails.isEmpty()) {
                boolean found = false;
                for (SessionDetail detail : sessionDetails) {
                    if (detail.getMessages() != null) {
                        try {
                            java.util.Map<String, Object> msg = objectMapper.readValue(detail.getMessages(), 
                                new com.fasterxml.jackson.core.type.TypeReference<java.util.Map<String, Object>>() {});
                            String uuid = (String) msg.get("messageUuid");
                            if (messageUuid.equals(uuid)) {
                                detail.setMessages(updatedJson);
                                detail.setUpdatedAt(LocalDateTime.now());
                                sessionDetailMapper.updateById(detail);
                                // 媒体提取、搜索结果、expertTrace 每类消息各一次回写，每次用户消息 3+ 条
                                // 统一降 DEBUG；失败/找不到保持 WARN/ERROR
                                logger.debug("MySQL消息内容更新成功: sessionId={}, messageUuid={}", sessionId, messageUuid);
                                found = true;
                                break;
                            }
                        } catch (com.fasterxml.jackson.core.JsonProcessingException e) {
                            logger.debug("解析消息JSON失败: {}", e.getMessage());
                        }
                    }
                }
                if (!found) {
                    // 占位消息只在 Redis 有、MySQL 没有对应行 → 自动 INSERT（upsert 语义）
                    logger.info("[MySQL upsert] 未找到匹配记录，自动插入: sessionId={}, messageUuid={}", sessionId, messageUuid);
                    SessionDetail newDetail = new SessionDetail();
                    newDetail.setSessionId(sessionId);
                    newDetail.setMessages(updatedJson);
                    newDetail.setMessageType("TEXT");
                    newDetail.setMediaUrl(null);
                    newDetail.setCreatedAt(LocalDateTime.now());
                    newDetail.setUpdatedAt(LocalDateTime.now());
                    sessionDetailMapper.insert(newDetail);
                }
            } else {
                logger.warn("会话不存在或无消息: sessionId={}", sessionId);
            }
        } catch (Exception e) {
            logger.error("异步更新消息内容到MySQL失败: sessionId={}, messageUuid={}, 错误={}", 
                sessionId, messageUuid, e.getMessage());
        }
    }

    

    /**
     * 异步删除 Qdrant 中的记忆数据
     * 调用 Agent 的删除记忆接口
     * @param sessionId 会话 ID
     */
    @Async("summaryExecutor")
    public void asyncDeleteQdrantMemory(Long sessionId) {
        try {
            Map<String, Object> requestBody = new HashMap<>();
            // session_id 必须以字符串形式传递，与 Qdrant 中存储的格式保持一致
            // 避免因类型不匹配导致删除失败（字符串 "123" 与整数 123 在 Qdrant MatchValue 中不匹配）
            requestBody.put("session_id", String.valueOf(sessionId));
            
            String jsonBody = objectMapper.writeValueAsString(requestBody);
            String urlStr = agentUrl + "/memory/delete";
            
            URL url = new URL(urlStr);
            HttpURLConnection conn = (HttpURLConnection) url.openConnection();
            conn.setRequestMethod("DELETE");
            conn.setRequestProperty("Content-Type", "application/json");
            conn.setRequestProperty("Accept", "application/json");
            conn.setRequestProperty("X-Internal-Secret", internalSecret);
            conn.setDoOutput(true);
            conn.setConnectTimeout(30000);
            conn.setReadTimeout(60000);
            
            try (java.io.OutputStream os = conn.getOutputStream()) {
                byte[] input = jsonBody.getBytes(StandardCharsets.UTF_8);
                os.write(input, 0, input.length);
            }
            
            int status = conn.getResponseCode();
            conn.disconnect();
            
            if (status == 200) {
                logger.info("Qdrant记忆删除成功: sessionId={}", sessionId);
            } else {
                logger.warn("Qdrant记忆删除失败: sessionId={}, status={}", sessionId, status);
            }
            
            logger.debug("删除请求体: {}", jsonBody);
        } catch (Exception e) {
            logger.error("异步删除Qdrant记忆失败: sessionId={}, 错误={}", sessionId, e.getMessage());
        }
    }

    /**
     * 调用 Agent 的摘要提取接口
     * 使用 HttpURLConnection 同步调用，最长阻塞 60 秒
     * @param jsonBody 请求体 JSON
     * @return 摘要字符串，失败返回 null
     */
    private String callAgentSummary(String jsonBody) {
        try {
            URL url = new URL(agentUrl + "/summarize");
            HttpURLConnection conn = (HttpURLConnection) url.openConnection();
            conn.setRequestMethod("POST");
            conn.setRequestProperty("Content-Type", "application/json");
            conn.setRequestProperty("Accept", "application/json");
            conn.setDoOutput(true);
            conn.setConnectTimeout(30000);
            conn.setReadTimeout(60000);

            try (java.io.OutputStream os = conn.getOutputStream()) {
                byte[] input = jsonBody.getBytes(StandardCharsets.UTF_8);
                os.write(input, 0, input.length);
            }

            int status = conn.getResponseCode();

            InputStream is = status >= 400 ? conn.getErrorStream() : conn.getInputStream();
            StringBuilder responseBuilder = new StringBuilder();
            byte[] buffer = new byte[1024];
            int read;
            while ((read = is.read(buffer)) != -1) {
                responseBuilder.append(new String(buffer, 0, read, StandardCharsets.UTF_8));
            }
            is.close();
            conn.disconnect();

            String response = responseBuilder.toString();

            if (status == 200) {
                Map<String, Object> result = objectMapper.readValue(response, new TypeReference<Map<String, Object>>() {});
                return (String) result.get("summary");
            } else {
                logger.error("Agent 摘要接口返回错误: status={}", status);
                return null;
            }
        } catch (Exception e) {
            logger.error("调用 Agent 摘要接口失败: {}", e.getMessage());
            return null;
        }
    }
}
