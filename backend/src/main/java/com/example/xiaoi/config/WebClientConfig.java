package com.example.xiaoi.config;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.reactive.function.client.WebClient;

@Configuration
public class WebClientConfig {
    
    @Value("${agent.url:http://localhost:8000}")
    private String agentUrl;
    
    @Bean
    public WebClient webClient() {
        return WebClient.builder()
                .baseUrl(agentUrl)
                .build();
    }
}