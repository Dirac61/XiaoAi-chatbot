package com.example.xiaoi.config;

import org.springframework.boot.web.client.RestTemplateBuilder;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.client.RestTemplate;

import java.time.Duration;

/**
 * RestTemplate 配置类
 * 用于 MCP 插件市场功能调用 Agent (FastAPI) 的同步 HTTP 接口
 * 注意：项目同时使用 WebClient（流式聊天），RestTemplate 仅用于 MCP 同步接口
 */
@Configuration
public class RestConfig {

    /**
     * 创建 RestTemplate Bean
     * 设置连接和读取超时，避免 Agent 异常时长时间阻塞
     *
     * @return RestTemplate 实例
     */
    @Bean
    public RestTemplate restTemplate(RestTemplateBuilder builder) {
        // Spring Boot 3.2+ 将 connectTimeout/readTimeout 重命名为 setConnectTimeout/setReadTimeout
        // 用新方法名保证 3.2.5 编译通过（旧方法名已弃用并在新版移除）
        return builder
                .setConnectTimeout(Duration.ofSeconds(10))
                .setReadTimeout(Duration.ofSeconds(30))
                .build();
    }
}
