package com.example.xiaoi.service;

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

    private static final String REDIS_SUMMARY_PREFIX = "session:summary:";
    private static final long REDIS_EXPIRE_DAYS = 1;
    private static final int MAX_SUMMARY_LENGTH = 500;

    /**
     * 异步保存消息到 MySQL 并更新会话时间
     * MySQL 写入相对较慢，异步执行避免阻塞请求线程
     * @param sessionId 会话 ID
     * @param messageJson 消息 JSON 字符串
     */
    @Async("summaryExecutor")
    public void asyncSaveMessageToDb(Long sessionId, String messageJson) {
        try {
            SessionDetail sessionDetail = new SessionDetail();
            sessionDetail.setSessionId(sessionId);
            sessionDetail.setMessages(messageJson);
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
