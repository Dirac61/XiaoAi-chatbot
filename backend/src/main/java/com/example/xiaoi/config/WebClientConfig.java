package com.example.xiaoi.config;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.reactive.function.client.WebClient;

/**
 * WebClient 配置类
 * 用于调用 Agent (FastAPI) 的流式接口
 * 注意：WebClient 是响应式异步客户端，与 Spring MVC 的阻塞模型需要通过 CountDownLatch 桥接
 */
@Configuration
public class WebClientConfig {
    
    @Value("${agent.url:http://localhost:8000}")
    private String agentUrl;
    
    /**
     * 创建 WebClient Bean
     * 配置 baseUrl 为 Agent 服务地址，避免每次调用重复指定 URL
     * @return WebClient 实例
     */
    @Bean
    public WebClient webClient() {
        return WebClient.builder()
                .baseUrl(agentUrl)
                .build();
    }
}