package com.example.xiaoi.interceptor;

import com.fasterxml.jackson.databind.ObjectMapper;
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

        String userId = redisTemplate.opsForValue().get("token:" + token);
        
        if (userId == null) {
            response.setContentType("application/json;charset=UTF-8");
            response.setStatus(401);
            Map<String, Object> result = new HashMap<>();
            result.put("code", 401);
            result.put("message", "登录已过期，请重新登录");
            response.getWriter().write(objectMapper.writeValueAsString(result));
            return false;
        }

        request.setAttribute("userId", userId);
        return true;
    }
}