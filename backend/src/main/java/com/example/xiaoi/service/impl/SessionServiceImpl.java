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
     * @param message 消息内容（包含 role, content, timestamp）
     */
    @Override
    public void saveMessage(Long sessionId, Map<String, Object> message) {
        try {
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
            asyncService.asyncSaveMessageToDb(sessionId, messageJson);
        } catch (JsonProcessingException e) {
            logger.error("消息序列化失败: sessionId={}, 错误={}", sessionId, e.getMessage());
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
            logger.info("触发摘要提取: sessionId={}, 轮次={}", sessionId, turnCount);
            // 先同步获取历史消息（从 Redis 读，毫秒级），再传给异步方法
            // 避免在异步线程中再次查询 Redis，也避免循环依赖
            Map<String, Object> sessionMessages = getSessionMessages(sessionId);
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
}
