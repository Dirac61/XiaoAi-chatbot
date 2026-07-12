package com.example.xiaoi.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
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
        List<Session> sessions = sessionMapper.selectList(queryWrapper);
        
        logger.info("找到 {} 个会话: userId={}", sessions.size(), userId);
        return sessions;
    }

    @Override
    public Map<String, Object> getSessionMessages(Long sessionId) {
        logger.debug("获取会话消息: sessionId={}", sessionId);
        
        Map<String, Object> result = new HashMap<>();
        String redisKey = REDIS_KEY_PREFIX + sessionId;
        
        List<String> redisMessages = redisTemplate.opsForList().range(redisKey, 0, -1);
        
        if (redisMessages != null && !redisMessages.isEmpty()) {
            logger.info("Redis 中找到 {} 条消息: sessionId={}", redisMessages.size(), sessionId);
            
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
        } else {
            logger.info("Redis 中未找到消息，降级到 MySQL 查询: sessionId={}", sessionId);
        }

        LambdaQueryWrapper<SessionDetail> queryWrapper = new LambdaQueryWrapper<>();
        queryWrapper.eq(SessionDetail::getSessionId, sessionId);
        queryWrapper.orderByAsc(SessionDetail::getCreatedAt);
        List<SessionDetail> sessionDetails = sessionDetailMapper.selectList(queryWrapper);
        
        List<Map<String, Object>> messages = new ArrayList<>();
        if (sessionDetails != null && !sessionDetails.isEmpty()) {
            logger.info("MySQL 中找到 {} 条消息: sessionId={}", sessionDetails.size(), sessionId);
            
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
            
            if (!messages.isEmpty()) {
                logger.info("将 {} 条 MySQL 消息写入 Redis: sessionId={}", messages.size(), sessionId);
                for (Map<String, Object> msg : messages) {
                    try {
                        String msgJson = objectMapper.writeValueAsString(msg);
                        redisTemplate.opsForList().rightPush(redisKey, msgJson);
                    } catch (JsonProcessingException e) {
                        logger.error("序列化消息写入 Redis 失败: {}", e.getMessage());
                    }
                }
                redisTemplate.expire(redisKey, REDIS_EXPIRE_DAYS, TimeUnit.DAYS);
                logger.info("设置 Redis 过期时间: {} 天", REDIS_EXPIRE_DAYS);
            }
        } else {
            logger.info("MySQL 中也未找到消息: sessionId={}", sessionId);
        }
        
        result.put("messages", messages);
        logger.debug("返回 {} 条消息: sessionId={}", messages.size(), sessionId);
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

            logger.info("消息保存成功: sessionId={}, role={}", sessionId, message.get("role"));
        } catch (JsonProcessingException e) {
            logger.error("消息序列化失败: sessionId={}, 错误={}", sessionId, e.getMessage());
            e.printStackTrace();
        }
    }
}