package com.example.xiaoi.controller;

import com.example.xiaoi.context.UserContext;
import com.example.xiaoi.dto.ChatRequest;
import com.example.xiaoi.service.ASRService;
import com.example.xiaoi.service.OSSUploadService;
import com.example.xiaoi.service.SessionService;
import com.example.xiaoi.utils.SnowflakeUtil;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.core.io.buffer.DataBuffer;
import org.springframework.core.io.buffer.DataBufferUtils;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.reactive.function.BodyInserters;
import org.springframework.web.reactive.function.client.ClientResponse;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.servlet.mvc.method.annotation.StreamingResponseBody;
import reactor.core.Disposable;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
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

    @Autowired
    private OSSUploadService ossUploadService;

    @Autowired
    private ASRService asrService;

    private static final long MAX_IMAGE_SIZE = 10 * 1024 * 1024;
    private static final long MAX_FILE_SIZE = 50 * 1024 * 1024;
    
    private static final String[] ALLOWED_IMAGE_TYPES = {
        "image/jpeg", "image/jpg", "image/png", "image/gif", "image/webp"
    };
    
    private static final String[] ALLOWED_FILE_TYPES = {
        "application/pdf", "application/msword", 
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/plain", "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    };

    @PostMapping(value = "/chat", produces = MediaType.TEXT_PLAIN_VALUE)
    public StreamingResponseBody chat(@RequestBody ChatRequest request, HttpServletResponse response) {
        Long userId = UserContext.getUserId();
        String messageType = request.getMessageType() != null ? request.getMessageType() : "TEXT";
        logger.info("收到聊天请求 - userId: {}, messageType: {}, sessionId: {}", 
            userId, messageType, request.getSessionId());

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
        String messageUuid = java.util.UUID.randomUUID().toString();
        userMessage.put("role", "user");
        userMessage.put("content", request.getMessage());
        userMessage.put("messageType", messageType);
        userMessage.put("mediaUrl", request.getMediaUrl());
        userMessage.put("timestamp", System.currentTimeMillis());
        userMessage.put("messageUuid", messageUuid);
        sessionService.saveMessage(sessionId, userMessage, messageType, request.getMediaUrl());

        Map<String, Object> requestBody = new HashMap<>();
        requestBody.put("message", request.getMessage());
        requestBody.put("history", history);
        requestBody.put("user_id", userId);
        requestBody.put("session_id", sessionId);
        requestBody.put("message_type", messageType);
        requestBody.put("media_url", request.getMediaUrl());
        requestBody.put("message_uuid", messageUuid);

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
                assistantMessage.put("messageType", "TEXT");
                assistantMessage.put("mediaUrl", null);
                assistantMessage.put("timestamp", System.currentTimeMillis());
                sessionService.saveMessage(sessionId, assistantMessage, "TEXT", null);
                logger.info("聊天请求完成 - sessionId: {}, 响应长度: {} 字符", 
                    sessionId, responseBuilder.length());
            } else {
                logger.warn("聊天请求无有效响应 - sessionId: {}", sessionId);
            }
        };
    }

    @PostMapping("/upload/image")
    public ResponseEntity<Map<String, Object>> uploadImage(@RequestParam("file") MultipartFile file) {
        Map<String, Object> result = new HashMap<>();
        
        try {
            if (!isValidImageType(file.getContentType())) {
                result.put("code", 400);
                result.put("message", "不支持的图片格式，仅支持JPG、PNG、GIF、WebP");
                return ResponseEntity.badRequest().body(result);
            }
            
            if (file.getSize() > MAX_IMAGE_SIZE) {
                result.put("code", 400);
                result.put("message", "图片大小超过限制（最大10MB）");
                return ResponseEntity.badRequest().body(result);
            }

            String url = ossUploadService.uploadImage(file);
            result.put("code", 200);
            result.put("data", url);
            return ResponseEntity.ok(result);
        } catch (IOException e) {
            logger.error("图片上传失败: {}", e.getMessage());
            result.put("code", 500);
            result.put("message", "图片上传失败: " + e.getMessage());
            return ResponseEntity.internalServerError().body(result);
        }
    }

    @PostMapping("/upload/file")
    public ResponseEntity<Map<String, Object>> uploadFile(@RequestParam("file") MultipartFile file) {
        Map<String, Object> result = new HashMap<>();
        
        try {
            if (!isValidFileType(file.getContentType())) {
                result.put("code", 400);
                result.put("message", "不支持的文件格式，仅支持PDF、DOC、DOCX、TXT、XLS、XLSX");
                return ResponseEntity.badRequest().body(result);
            }
            
            if (file.getSize() > MAX_FILE_SIZE) {
                result.put("code", 400);
                result.put("message", "文件大小超过限制（最大50MB）");
                return ResponseEntity.badRequest().body(result);
            }

            String url = ossUploadService.uploadFile(file);
            result.put("code", 200);
            result.put("data", url);
            return ResponseEntity.ok(result);
        } catch (IOException e) {
            logger.error("文件上传失败: {}", e.getMessage());
            result.put("code", 500);
            result.put("message", "文件上传失败: " + e.getMessage());
            return ResponseEntity.internalServerError().body(result);
        }
    }

    private boolean isValidImageType(String contentType) {
        if (contentType == null) return false;
        for (String type : ALLOWED_IMAGE_TYPES) {
            if (type.equalsIgnoreCase(contentType)) {
                return true;
            }
        }
        return false;
    }

    private boolean isValidFileType(String contentType) {
        if (contentType == null) return false;
        for (String type : ALLOWED_FILE_TYPES) {
            if (type.equalsIgnoreCase(contentType)) {
                return true;
            }
        }
        return false;
    }

    @PostMapping("/speech-to-text")
    public ResponseEntity<Map<String, Object>> speechToText(@RequestParam("audio") MultipartFile audioFile) {
        Map<String, Object> result = new HashMap<>();
        
        try {
            byte[] audioData = audioFile.getBytes();
            String text = asrService.speechToText(audioData);
            
            if (text != null && !text.isEmpty()) {
                result.put("code", 200);
                result.put("data", text);
                return ResponseEntity.ok(result);
            } else {
                result.put("code", 500);
                result.put("message", "语音转文本失败");
                return ResponseEntity.internalServerError().body(result);
            }
        } catch (IOException e) {
            logger.error("语音转文本失败: {}", e.getMessage());
            result.put("code", 500);
            result.put("message", "语音转文本失败: " + e.getMessage());
            return ResponseEntity.internalServerError().body(result);
        }
    }

    @PostMapping("/message/update-content")
    public ResponseEntity<Map<String, Object>> updateMessageContent(@RequestBody Map<String, Object> request) {
        Map<String, Object> result = new HashMap<>();
        
        try {
            Long sessionId = Long.parseLong(request.get("session_id").toString());
            String messageUuid = (String) request.get("message_uuid");
            String message = (String) request.get("message");
            String extractedText = (String) request.get("extracted_text");
            
            sessionService.updateMessageContent(sessionId, messageUuid, message, extractedText);
            
            result.put("code", 200);
            result.put("message", "消息内容更新成功");
            return ResponseEntity.ok(result);
        } catch (Exception e) {
            logger.error("更新消息内容失败: {}", e.getMessage());
            result.put("code", 500);
            result.put("message", "更新消息内容失败: " + e.getMessage());
            return ResponseEntity.internalServerError().body(result);
        }
    }

    @DeleteMapping("/upload/delete")
    public ResponseEntity<Map<String, Object>> deleteFile(@RequestBody Map<String, Object> request) {
        Map<String, Object> result = new HashMap<>();
        
        try {
            String url = (String) request.get("url");
            if (url == null || url.isEmpty()) {
                result.put("code", 400);
                result.put("message", "URL不能为空");
                return ResponseEntity.badRequest().body(result);
            }
            
            // 调用哈希去重删除（引用计数递减，为 0 时自动删除 OSS）
            boolean success = ossUploadService.deleteWithDedup(url);
            
            if (success) {
                result.put("code", 200);
                result.put("message", "文件删除成功");
                return ResponseEntity.ok(result);
            } else {
                result.put("code", 500);
                result.put("message", "文件删除失败");
                return ResponseEntity.internalServerError().body(result);
            }
        } catch (Exception e) {
            logger.error("删除文件失败: {}", e.getMessage());
            result.put("code", 500);
            result.put("message", "删除文件失败: " + e.getMessage());
            return ResponseEntity.internalServerError().body(result);
        }
    }
}
