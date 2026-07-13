package com.example.xiaoi.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Redis 配置类
 * 配置 JSON 序列化器，用于消息在 Redis 中的存储和读取
 */
@Configuration
public class RedisConfig {

    /**
     * 创建 ObjectMapper Bean
     * 注册 JavaTimeModule 支持 Java 8 日期时间类型，禁用时间戳格式输出
     * @return ObjectMapper 实例
     */
    @Bean
    public ObjectMapper objectMapper() {
        ObjectMapper mapper = new ObjectMapper();
        // 注册 JavaTimeModule 支持 LocalDateTime、LocalDate 等 Java 8 日期类型
        mapper.registerModule(new JavaTimeModule());
        // 禁用日期转时间戳，输出 ISO-8601 格式字符串
        mapper.disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);
        return mapper;
    }
}