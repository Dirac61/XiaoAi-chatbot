package com.example.xiaoi.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.example.xiaoi.entity.User;
import com.example.xiaoi.mapper.UserMapper;
import com.example.xiaoi.service.UserService;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.HashMap;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.TimeUnit;

@Service
public class UserServiceImpl implements UserService {

    private static final Logger logger = LoggerFactory.getLogger(UserServiceImpl.class);

    @Autowired
    private UserMapper userMapper;

    @Autowired
    private StringRedisTemplate redisTemplate;

    @Autowired
    private ObjectMapper objectMapper;

    private final BCryptPasswordEncoder passwordEncoder = new BCryptPasswordEncoder();

    @Override
    public Map<String, Object> login(String username, String password) {
        Map<String, Object> result = new HashMap<>();
        
        LambdaQueryWrapper<User> queryWrapper = new LambdaQueryWrapper<>();
        queryWrapper.eq(User::getUsername, username);
        User user = userMapper.selectOne(queryWrapper);

        if (user == null) {
            user = new User();
            user.setUsername(username);
            user.setPassword(passwordEncoder.encode(password));
            user.setCreatedAt(LocalDateTime.now());
            user.setUpdatedAt(LocalDateTime.now());
            userMapper.insert(user);
            logger.info("注册新用户: username={}", username);
        } else {
            if (!passwordEncoder.matches(password, user.getPassword())) {
                result.put("code", 401);
                result.put("message", "密码错误");
                return result;
            }
            logger.info("用户登录成功: username={}", username);
        }

        String token = UUID.randomUUID().toString().replace("-", "");
        
        Map<String, Object> userInfo = new HashMap<>();
        userInfo.put("id", user.getId());
        userInfo.put("username", user.getUsername());
        userInfo.put("token", token);
        
        Map<String, Object> redisUser = new HashMap<>();
        redisUser.put("id", user.getId());
        redisUser.put("username", user.getUsername());
        
        try {
            String userJson = objectMapper.writeValueAsString(redisUser);
            redisTemplate.opsForValue().set("token:" + token, userJson, 24, TimeUnit.HOURS);
            logger.info("Token 缓存成功: username={}, token={}", username, token.substring(0, 8));
        } catch (Exception e) {
            logger.error("Token 缓存失败: username={}, 错误={}", username, e.getMessage(), e);
        }
        
        result.put("code", 200);
        result.put("message", "登录成功");
        result.put("data", userInfo);
        
        return result;
    }
}