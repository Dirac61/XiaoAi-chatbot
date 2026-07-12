package com.example.xiaoi.controller;

import com.example.xiaoi.context.UserContext;
import com.example.xiaoi.dto.ChatRequest;
import com.example.xiaoi.service.SessionService;
import com.example.xiaoi.utils.SnowflakeUtil;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.core.io.buffer.DataBuffer;
import org.springframework.core.io.buffer.DataBufferUtils;
import org.springframework.http.MediaType;
import org.springframework.http.client.reactive.ClientHttpResponse;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.reactive.function.BodyInserters;
import org.springframework.web.reactive.function.client.ClientResponse;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.servlet.mvc.method.annotation.StreamingResponseBody;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

@RestController
@RequestMapping("/api")
public class ChatController {

    private static final Logger logger = LoggerFactory.getLogger(ChatController.class);

    @Autowired
    private SessionService sessionService;

    @Autowired
    private SnowflakeUtil snowflakeUtil;

    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private WebClient webClient;

    @PostMapping(value = "/chat", produces = MediaType.TEXT_PLAIN_VALUE)
    public StreamingResponseBody chat(@RequestBody ChatRequest request, HttpServletResponse response) {
        Long userId = UserContext.getUserId();
        logger.info("收到聊天请求 - userId: {}, 消息: '{}', sessionId: {}", 
            userId, request.getMessage(), request.getSessionId());

        Long sessionId = request.getSessionId() != null ? request.getSessionId() : sessionService.createSession(userId);
        if (request.getSessionId() == null) {
            logger.info("创建新会话: {}", sessionId);
        }
        response.setHeader("X-Session-Id", sessionId.toString());

        Map<String, Object> userMessage = new HashMap<>();
        userMessage.put("role", "user");
        userMessage.put("content", request.getMessage());
        userMessage.put("timestamp", System.currentTimeMillis());
        sessionService.saveMessage(sessionId, userMessage);

        Map<String, Object> sessionMessages = sessionService.getSessionMessages(sessionId);
        List<Map<String, Object>> history = (List<Map<String, Object>>) sessionMessages.get("messages");
        
        int historySize = history != null ? history.size() : 0;
        if (history != null && history.size() > 10) {
            history = history.subList(history.size() - 10, history.size());
            logger.debug("历史消息从 {} 条裁剪到 {} 条", historySize, history.size());
        }
        logger.info("发送 {} 条历史消息给 agent", history != null ? history.size() : 0);

        Map<String, Object> requestBody = new HashMap<>();
        requestBody.put("message", request.getMessage());
        requestBody.put("history", history);

        return outputStream -> {
            StringBuilder responseBuilder = new StringBuilder();
            CountDownLatch latch = new CountDownLatch(1);

            try {
                String jsonBody = objectMapper.writeValueAsString(requestBody);
                logger.debug("发送给 agent 的请求体: {}", jsonBody);

                AtomicInteger chunkCount = new AtomicInteger(0);

                Mono<ClientResponse> clientResponseMono = webClient.post()
                        .uri("/chat")
                        .contentType(MediaType.APPLICATION_JSON)
                        .accept(MediaType.TEXT_EVENT_STREAM)
                        .body(BodyInserters.fromValue(jsonBody))
                        .exchange();

                clientResponseMono.flatMapMany(clientResponse -> {
                    logger.info("Agent 响应状态码: {}", clientResponse.statusCode());
                    return clientResponse.bodyToFlux(DataBuffer.class);
                }).subscribe(
                    dataBuffer -> {
                        try {
                            byte[] bytes = new byte[dataBuffer.readableByteCount()];
                            dataBuffer.read(bytes);
                            DataBufferUtils.release(dataBuffer);
                            
                            String chunk = new String(bytes, StandardCharsets.UTF_8);
                            int currentCount = chunkCount.incrementAndGet();
                            
                            logger.info("收到 agent 数据块 {}: '{}'", currentCount, chunk);
                            
                            responseBuilder.append(chunk);
                            outputStream.write(bytes);
                            outputStream.flush();
                            
                            logger.debug("数据块已写入输出流，当前累计响应长度: {} 字符", responseBuilder.length());
                        } catch (IOException e) {
                            logger.error("写入输出流失败: {}", e.getMessage());
                        }
                    },
                    error -> {
                        logger.error("agent 流错误: {}", error.getMessage());
                        latch.countDown();
                    },
                    () -> {
                        logger.info("流传输完成，收到 {} 个数据块，总响应长度: {} 字符", chunkCount.get(), responseBuilder.length());
                        latch.countDown();
                    }
                );

                boolean completed = latch.await(120, TimeUnit.SECONDS);
                if (!completed) {
                    logger.warn("流超时，超过 120 秒");
                }
            } catch (Exception e) {
                logger.error("流式传输错误: {}", e.getMessage(), e);
            }

            Map<String, Object> assistantMessage = new HashMap<>();
            assistantMessage.put("role", "assistant");
            assistantMessage.put("content", responseBuilder.toString());
            assistantMessage.put("timestamp", System.currentTimeMillis());
            sessionService.saveMessage(sessionId, assistantMessage);
            
            logger.info("聊天请求完成 - sessionId: {}, 响应长度: {} 字符", 
                sessionId, responseBuilder.length());
        };
    }
}