package com.example.xiaoi.config;

import com.example.xiaoi.interceptor.TokenInterceptor;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

/**
 * 拦截器配置类
 * 注册 Token 拦截器，对所有 /api/** 请求进行登录校验
 */
@Configuration
public class InterceptorConfig implements WebMvcConfigurer {

    @Autowired
    private TokenInterceptor tokenInterceptor;

    /**
     * 注册 Token 拦截器
     * 拦截所有 /api/** 请求，但排除登录接口和健康检查接口
     */
    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        registry.addInterceptor(tokenInterceptor)
                // 拦截所有 /api/** 请求
                .addPathPatterns("/api/**")
                // 排除登录接口、健康检查接口和内部接口（Agent调用）
                .excludePathPatterns("/api/login", "/api/health", "/api/message/update-content", "/api/session/delete/**");
    }
}