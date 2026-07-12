package com.example.xiaoi.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.example.xiaoi.entity.Session;
import com.example.xiaoi.entity.SessionDetail;
import com.example.xiaoi.mapper.SessionDetailMapper;
import com.example.xiaoi.mapper.SessionMapper;
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

    private static final String REDIS_KEY_PREFIX = "session:";
    private static final long REDIS_EXPIRE_DAYS = 1;
    private static final int MAX_REDIS_MESSAGES = 20;

    @Override
    public Long createSession(Long userId) {
        logger.info("为用户创建新会话: userId={}", userId);
        
        Long sessionId = snowflakeUtil.nextId();
        logger.debug("生成 sessionId: {}", sessionId);
        
        Session session = new Session();
        session.setId(sessionId);
        session.setUserId(userId);
        session.setCreatedAt(LocalDateTime.now());
        session.setUpdatedAt(LocalDateTime.now());
        
        int result = sessionMapper.insert(session);
        if (result > 0) {
            logger.info("会话创建成功: sessionId={}, userId={}", sessionId, userId);
        } else {
            logger.error("会话创建失败: sessionId={}, userId={}", sessionId, userId);
        }

        return sessionId;
    }

    @Override
    public List<Session> getSessionsByUserId(Long userId) {
        logger.debug("获取用户的会话列表: userId={}", userId);
        
        LambdaQueryWrapper<Session> queryWrapper = new LambdaQueryWrapper<>();
        queryWrapper.eq(Session::getUserId, userId);
        queryWrapper.orderByDesc(Session::getUpdatedAt);
        List<Session> sessions = sessionMapper.selectList(queryWrapper);
        
        logger.info("找到 {} 个会话: userId={}", sessions.size(), userId);
        return sessions;
    }

    @Override
    public Map<String, Object> getSessionMessages(Long sessionId) {
        logger.debug("获取会话消息(最近{}条): sessionId={}", MAX_REDIS_MESSAGES, sessionId);
        
        Map<String, Object> result = new HashMap<>();
        String redisKey = REDIS_KEY_PREFIX + sessionId;
        
        List<String> redisMessages = redisTemplate.opsForList().range(redisKey, 0, -1);
        
        if (redisMessages != null && !redisMessages.isEmpty()) {
            logger.info("Redis 中找到 {} 条消息: sessionId={}", redisMessages.size(), sessionId);
            
            redisTemplate.expire(redisKey, REDIS_EXPIRE_DAYS, TimeUnit.DAYS);
            logger.debug("刷新 Redis TTL: {} 天", REDIS_EXPIRE_DAYS);
            
            try {
                List<Map<String, Object>> messages = new ArrayList<>();
                for (String msgJson : redisMessages) {
                    if (msgJson != null && !msgJson.isEmpty()) {
                        Map<String, Object> msg = objectMapper.readValue(msgJson, new TypeReference<Map<String, Object>>() {});
                        messages.add(msg);
                    }
                }
                result.put("messages", messages);
                logger.debug("成功解析 {} 条 Redis 消息", messages.size());
                return result;
            } catch (JsonProcessingException e) {
                logger.error("解析 Redis 消息失败: sessionId={}, 错误={}", sessionId, e.getMessage());
                e.printStackTrace();
            }
        }

        result.put("messages", new ArrayList<>());
        return result;
    }

    @Override
    public void saveMessage(Long sessionId, Map<String, Object> message) {
        logger.debug("保存消息: sessionId={}, role={}", sessionId, message.get("role"));
        
        try {
            String messageJson = objectMapper.writeValueAsString(message);
            logger.trace("消息内容: {}", messageJson);

            String redisKey = REDIS_KEY_PREFIX + sessionId;
            redisTemplate.opsForList().rightPush(redisKey, messageJson);
            
            Long size = redisTemplate.opsForList().size(redisKey);
            if (size != null && size > MAX_REDIS_MESSAGES) {
                redisTemplate.opsForList().trim(redisKey, size - MAX_REDIS_MESSAGES, -1);
                logger.debug("Redis消息超过 {} 条，已截断，移除 {} 条: sessionId={}", MAX_REDIS_MESSAGES, size - MAX_REDIS_MESSAGES, sessionId);
            }
            
            redisTemplate.expire(redisKey, REDIS_EXPIRE_DAYS, TimeUnit.DAYS);
            logger.debug("消息已保存到 Redis，过期时间 {} 天: sessionId={}", REDIS_EXPIRE_DAYS, sessionId);

            SessionDetail sessionDetail = new SessionDetail();
            sessionDetail.setSessionId(sessionId);
            sessionDetail.setMessages(messageJson);
            sessionDetail.setCreatedAt(LocalDateTime.now());
            sessionDetail.setUpdatedAt(LocalDateTime.now());
            
            int result = sessionDetailMapper.insert(sessionDetail);
            if (result > 0) {
                logger.debug("消息已保存到 MySQL: sessionId={}", sessionId);
            } else {
                logger.error("消息保存到 MySQL 失败: sessionId={}", sessionId);
            }

            Session session = new Session();
            session.setId(sessionId);
            session.setUpdatedAt(LocalDateTime.now());
            sessionMapper.updateById(session);
            logger.debug("更新会话更新时间: sessionId={}", sessionId);

            logger.info("消息保存成功: sessionId={}, role={}", sessionId, message.get("role"));
        } catch (JsonProcessingException e) {
            logger.error("消息序列化失败: sessionId={}, 错误={}", sessionId, e.getMessage());
            e.printStackTrace();
        }
    }

    @Override
    public Map<String, Object> getSessionMessagesByPage(Long sessionId, Integer pageNum, Integer pageSize) {
        logger.debug("分页查询会话消息: sessionId={}, pageNum={}, pageSize={}", sessionId, pageNum, pageSize);
        
        Map<String, Object> result = new HashMap<>();
        String redisKey = REDIS_KEY_PREFIX + sessionId;
        
        LambdaQueryWrapper<SessionDetail> queryWrapper = new LambdaQueryWrapper<>();
        queryWrapper.eq(SessionDetail::getSessionId, sessionId);
        queryWrapper.orderByDesc(SessionDetail::getCreatedAt);
        
        Page<SessionDetail> page = new Page<>(pageNum, pageSize);
        IPage<SessionDetail> sessionDetailPage = sessionDetailMapper.selectPage(page, queryWrapper);
        
        List<SessionDetail> sessionDetails = sessionDetailPage.getRecords();
        List<Map<String, Object>> messages = new ArrayList<>();
        
        if (sessionDetails != null && !sessionDetails.isEmpty()) {
            logger.info("MySQL 分页查询找到 {} 条消息: sessionId={}", sessionDetails.size(), sessionId);
            
            for (SessionDetail detail : sessionDetails) {
                if (detail.getMessages() != null && !detail.getMessages().isEmpty()) {
                    try {
                        Map<String, Object> msg = objectMapper.readValue(detail.getMessages(), 
                            new TypeReference<Map<String, Object>>() {});
                        messages.add(msg);
                    } catch (JsonProcessingException e) {
                        logger.error("解析 MySQL 消息失败: sessionId={}, 错误={}", sessionId, e.getMessage());
                        e.printStackTrace();
                    }
                }
            }
            
            if (pageNum == 1 && !messages.isEmpty()) {
                logger.info("第一页查询，预热 Redis: sessionId={}", sessionId);
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
                logger.info("Redis 预热完成，保留最近 {} 条消息", cacheSize);
            }
        }
        
        result.put("messages", messages);
        result.put("total", sessionDetailPage.getTotal());
        result.put("pageNum", pageNum);
        result.put("pageSize", pageSize);
        result.put("hasNext", pageNum < sessionDetailPage.getPages());
        
        logger.debug("分页查询完成: sessionId={}, 返回 {} 条消息", sessionId, messages.size());
        return result;
    }

    @Override
    public Long getTotalMessageCount(Long sessionId) {
        logger.debug("获取消息总数: sessionId={}", sessionId);
        
        LambdaQueryWrapper<SessionDetail> queryWrapper = new LambdaQueryWrapper<>();
        queryWrapper.eq(SessionDetail::getSessionId, sessionId);
        Long count = sessionDetailMapper.selectCount(queryWrapper);
        
        logger.info("消息总数: sessionId={}, count={}", sessionId, count);
        return count;
    }
}