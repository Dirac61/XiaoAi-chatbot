package com.example.xiaoi.interceptor;

import com.example.xiaoi.context.UserContext;
import com.example.xiaoi.entity.User;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.HandlerInterceptor;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.util.HashMap;
import java.util.Map;

@Component
public class TokenInterceptor implements HandlerInterceptor {

    private static final Logger logger = LoggerFactory.getLogger(TokenInterceptor.class);

    @Autowired
    private StringRedisTemplate redisTemplate;

    @Autowired
    private ObjectMapper objectMapper;

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) throws Exception {
        String token = request.getHeader("Authorization");
        
        if (token == null || token.isEmpty()) {
            response.setContentType("application/json;charset=UTF-8");
            response.setStatus(401);
            Map<String, Object> result = new HashMap<>();
            result.put("code", 401);
            result.put("message", "未登录，请先登录");
            response.getWriter().write(objectMapper.writeValueAsString(result));
            return false;
        }

        String userJson = redisTemplate.opsForValue().get("token:" + token);
        
        if (userJson == null) {
            response.setContentType("application/json;charset=UTF-8");
            response.setStatus(401);
            Map<String, Object> result = new HashMap<>();
            result.put("code", 401);
            result.put("message", "登录已过期，请重新登录");
            response.getWriter().write(objectMapper.writeValueAsString(result));
            return false;
        }

        try {
            Map<String, Object> userMap = objectMapper.readValue(userJson, Map.class);
            User user = new User();
            user.setId(((Number) userMap.get("id")).longValue());
            user.setUsername((String) userMap.get("username"));
            UserContext.setUser(user);
            request.setAttribute("userId", user.getId());
        } catch (Exception e) {
            logger.error("用户信息解析失败: {}", e.getMessage(), e);
            response.setContentType("application/json;charset=UTF-8");
            response.setStatus(401);
            Map<String, Object> result = new HashMap<>();
            result.put("code", 401);
            result.put("message", "用户信息解析失败");
            response.getWriter().write(objectMapper.writeValueAsString(result));
            return false;
        }

        return true;
    }

    @Override
    public void afterCompletion(HttpServletRequest request, HttpServletResponse response, Object handler, Exception ex) throws Exception {
        UserContext.clear();
    }
}