package com.example.xiaoi.interceptor;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.HandlerInterceptor;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.util.HashMap;
import java.util.Map;

/**
 * 内部接口认证拦截器
 * 用于保护 Agent 调用的内部接口，防止外部直接调用
 * 验证方式：请求头中必须携带 X-Internal-Secret，且值与配置的 INTERNAL_SECRET 一致
 * 
 * 内部接口列表（由 Agent 调用）：
 * - /api/message/update-content
 * - /api/message/update-search-results
 * - /api/memory/delete
 */
@Component
public class InternalApiInterceptor implements HandlerInterceptor {

    private static final Logger logger = LoggerFactory.getLogger(InternalApiInterceptor.class);

    @Value("${internal.secret:xiaoi-internal-api-secret-2026}")
    private String internalSecret;

    private static final String SECRET_HEADER = "X-Internal-Secret";

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) throws Exception {
        String requestSecret = request.getHeader(SECRET_HEADER);
        
        if (requestSecret == null || requestSecret.isEmpty()) {
            logger.warn("内部接口调用缺少认证头: url={}, ip={}", request.getRequestURI(), getClientIp(request));
            response.setContentType("application/json;charset=UTF-8");
            response.setStatus(403);
            Map<String, Object> result = new HashMap<>();
            result.put("code", 403);
            result.put("message", "未授权的内部接口调用");
            response.getWriter().write(new ObjectMapper().writeValueAsString(result));
            return false;
        }

        if (!internalSecret.equals(requestSecret)) {
            logger.warn("内部接口调用认证失败: url={}, ip={}", request.getRequestURI(), getClientIp(request));
            response.setContentType("application/json;charset=UTF-8");
            response.setStatus(403);
            Map<String, Object> result = new HashMap<>();
            result.put("code", 403);
            result.put("message", "内部接口认证失败");
            response.getWriter().write(new ObjectMapper().writeValueAsString(result));
            return false;
        }

        logger.debug("内部接口调用认证成功: url={}, ip={}", request.getRequestURI(), getClientIp(request));
        return true;
    }

    /**
     * 获取客户端真实 IP（支持代理）
     * @param request HTTP 请求
     * @return 客户端 IP 地址
     */
    private String getClientIp(HttpServletRequest request) {
        String ip = request.getHeader("X-Forwarded-For");
        if (ip == null || ip.isEmpty() || "unknown".equalsIgnoreCase(ip)) {
            ip = request.getHeader("X-Real-IP");
        }
        if (ip == null || ip.isEmpty() || "unknown".equalsIgnoreCase(ip)) {
            ip = request.getRemoteAddr();
        }
        // 如果是多个代理，取第一个 IP
        if (ip != null && ip.contains(",")) {
            ip = ip.split(",")[0].trim();
        }
        return ip;
    }
}