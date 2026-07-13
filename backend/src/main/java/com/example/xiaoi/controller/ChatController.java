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
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.reactive.function.BodyInserters;
import org.springframework.web.reactive.function.client.ClientResponse;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.servlet.mvc.method.annotation.StreamingResponseBody;
import reactor.core.Disposable;
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

    /**
     * 聊天接口 - 流式响应
     * 架构说明：
     *   前端 → Spring MVC Controller → WebClient(异步) → Agent(FastAPI) → LLM
     *   由于 Spring MVC 的 StreamingResponseBody 是阻塞式回调，而 WebClient 是响应式异步调用，
     *   需要用 CountDownLatch 将异步流桥接到阻塞的 Servlet 线程中。
     *   Disposable 用于在中断/异常时正确释放 reactive subscription，避免资源泄漏。
     * @param request 聊天请求（包含 sessionId 和 message）
     * @param response HTTP 响应对象，用于设置自定义 header
     * @return StreamingResponseBody 流式响应体
     */
    @PostMapping(value = "/chat", produces = MediaType.TEXT_PLAIN_VALUE)
    public StreamingResponseBody chat(@RequestBody ChatRequest request, HttpServletResponse response) {
        Long userId = UserContext.getUserId();
        logger.info("收到聊天请求 - userId: {}, 消息: '{}', sessionId: {}", 
            userId, request.getMessage(), request.getSessionId());

        final Long sessionId;
        if (request.getSessionId() != null) {
            sessionId = request.getSessionId();
        } else {
            sessionId = sessionService.createSession(userId);
            logger.info("创建新会话: {}", sessionId);
        }
        response.setHeader("X-Session-Id", sessionId.toString());

        Map<String, Object> sessionMessages = sessionService.getSessionMessages(sessionId);
        List<Map<String, Object>> history = (List<Map<String, Object>>) sessionMessages.get("messages");
        
        int maxHistorySize = 20;
        int historySize = history != null ? history.size() : 0;
        if (history != null && history.size() > maxHistorySize) {
            history = history.subList(history.size() - maxHistorySize, history.size());
            logger.debug("历史消息从 {} 条裁剪到 {} 条", historySize, history.size());
        }
        logger.info("发送 {} 条历史消息给 agent", history != null ? history.size() : 0);

        Map<String, Object> userMessage = new HashMap<>();
        userMessage.put("role", "user");
        userMessage.put("content", request.getMessage());
        userMessage.put("timestamp", System.currentTimeMillis());
        sessionService.saveMessage(sessionId, userMessage);

        Map<String, Object> requestBody = new HashMap<>();
        requestBody.put("message", request.getMessage());
        requestBody.put("history", history);
        requestBody.put("user_id", userId);
        requestBody.put("session_id", sessionId);

        return outputStream -> {
            StringBuilder responseBuilder = new StringBuilder();
            CountDownLatch latch = new CountDownLatch(1);
            Disposable disposable = null;

            try {
                String jsonBody = objectMapper.writeValueAsString(requestBody);

                AtomicInteger chunkCount = new AtomicInteger(0);

                Mono<ClientResponse> clientResponseMono = webClient.post()
                        .uri("/chat")
                        .contentType(MediaType.APPLICATION_JSON)
                        .accept(MediaType.TEXT_EVENT_STREAM)
                        .body(BodyInserters.fromValue(jsonBody))
                        .exchange();

                disposable = clientResponseMono.flatMapMany(clientResponse -> {
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
                            
                            logger.debug("收到 agent 数据块 {}: '{}'", currentCount, chunk);
                            
                            responseBuilder.append(chunk);
                            outputStream.write(bytes);
                            outputStream.flush();
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
            } catch (InterruptedException e) {
                logger.warn("流式传输被中断: sessionId={}", sessionId);
                Thread.currentThread().interrupt();
            } catch (Exception e) {
                logger.error("流式传输错误: {}", e.getMessage(), e);
            } finally {
                if (disposable != null && !disposable.isDisposed()) {
                    disposable.dispose();
                    logger.debug("已释放 reactive subscription");
                }
            }

            if (responseBuilder.length() > 0) {
                Map<String, Object> assistantMessage = new HashMap<>();
                assistantMessage.put("role", "assistant");
                assistantMessage.put("content", responseBuilder.toString());
                assistantMessage.put("timestamp", System.currentTimeMillis());
                sessionService.saveMessage(sessionId, assistantMessage);
                logger.info("聊天请求完成 - sessionId: {}, 响应长度: {} 字符", 
                    sessionId, responseBuilder.length());
            } else {
                logger.warn("聊天请求无有效响应 - sessionId: {}", sessionId);
            }
        };
    }
}