package com.example.xiaoi.config;

import com.example.xiaoi.interceptor.InternalApiInterceptor;
import com.example.xiaoi.interceptor.TokenInterceptor;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

/**
 * 拦截器配置类
 * - TokenInterceptor: 对所有 /api/** 请求进行登录校验（排除内部接口）
 * - InternalApiInterceptor: 对内部接口进行密钥认证（仅 Agent 可调用）
 */
@Configuration
public class InterceptorConfig implements WebMvcConfigurer {

    @Autowired
    private TokenInterceptor tokenInterceptor;

    @Autowired
    private InternalApiInterceptor internalApiInterceptor;

    /**
     * 注册拦截器
     * TokenInterceptor 拦截所有 /api/** 请求，排除登录、健康检查和内部接口
     * InternalApiInterceptor 只拦截内部接口，进行密钥认证
     */
    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        // TokenInterceptor: 用户认证拦截器
        registry.addInterceptor(tokenInterceptor)
                .addPathPatterns("/api/**")
                .excludePathPatterns("/api/login", "/api/health", 
                    "/api/message/update-content", "/api/message/update-search-results",
                    "/api/memory/delete", "/api/session/delete/**");

        // InternalApiInterceptor: 内部接口密钥认证拦截器
        registry.addInterceptor(internalApiInterceptor)
                .addPathPatterns(
                    "/api/message/update-content", 
                    "/api/message/update-search-results",
                    "/api/memory/delete"
                );
    }
}