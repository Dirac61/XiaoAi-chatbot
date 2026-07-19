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
                .allowedOrigins("http://localhost:5173", "http://localhost:5174")
                .allowedMethods("GET", "POST", "PUT", "DELETE", "OPTIONS")
                .allowedHeaders("*")
                .exposedHeaders("X-Session-Id")
                .allowCredentials(true)
                .maxAge(3600);
    }
}