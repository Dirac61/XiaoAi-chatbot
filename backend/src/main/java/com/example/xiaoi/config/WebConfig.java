package com.example.xiaoi.config;

import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.CorsRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

/**
 * Web 配置类
 * 配置跨域访问（CORS），允许前端从 localhost:5173 访问后端接口
 */
@Configuration
public class WebConfig implements WebMvcConfigurer {
    
    /**
     * 配置跨域规则
     * 允许前端 Vue 开发服务器访问后端 API
     * exposedHeaders 暴露 X-Session-Id，用于前端获取新创建的会话 ID
     */
    @Override
    public void addCorsMappings(CorsRegistry registry) {
        registry.addMapping("/api/**")
                // 允许前端开发服务器域名访问
                .allowedOrigins("http://localhost:5173")
                // 允许的 HTTP 方法
                .allowedMethods("GET", "POST", "PUT", "DELETE", "OPTIONS")
                // 允许所有请求头
                .allowedHeaders("*")
                // 暴露自定义响应头，供前端获取新会话 ID
                .exposedHeaders("X-Session-Id")
                // 允许携带凭证（Cookie、Authorization 等）
                .allowCredentials(true);
    }
}