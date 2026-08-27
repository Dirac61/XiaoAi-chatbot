package com.example.xiaoi.controller;

import com.example.xiaoi.context.UserContext;
import com.example.xiaoi.dto.ChatRequest;
import com.example.xiaoi.service.ASRService;
import com.example.xiaoi.service.OSSUploadService;
import com.example.xiaoi.service.SessionService;
import com.example.xiaoi.utils.SnowflakeUtil;
import com.fasterxml.jackson.core.type.TypeReference;
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
import java.util.concurrent.atomic.AtomicLong;

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

    @PostMapping(value = "/chat", produces = "text/event-stream;charset=UTF-8")
    public StreamingResponseBody chat(@RequestBody ChatRequest request, HttpServletResponse response) {
        Long userId = UserContext.getUserId();
        String messageType = request.getMessageType() != null ? request.getMessageType() : "TEXT";

        final Long sessionId;
        if (request.getSessionId() != null) {
            sessionId = request.getSessionId();
        } else {
            sessionId = sessionService.createSession(userId);
            logger.info("[会话] 创建新会话 sessionId={}", sessionId);
        }
        response.setHeader("X-Session-Id", sessionId.toString());

        Map<String, Object> sessionMessages = sessionService.getSessionMessages(sessionId);
        List<Map<String, Object>> history = (List<Map<String, Object>>) sessionMessages.get("messages");

        int maxHistorySize = 20;
        int historySize = history != null ? history.size() : 0;
        if (history != null && history.size() > maxHistorySize) {
            history = history.subList(history.size() - maxHistorySize, history.size());
            logger.debug("[历史] 从 {} 条裁剪到 {} 条 sessionId={}", historySize, history.size(), sessionId);
        }
        // 入口只保留 1 行汇总 INFO；之前那条「收到聊天请求」和「发送N条历史」两条重复 INFO 直接删掉（和本行重复）
        logger.info(
                "[聊天请求] userId={} sessionId={} mode={} type={} history={} msgLen={}",
                userId, sessionId,
                (request.getMode() != null ? request.getMode() : "fast"),
                messageType,
                (history != null ? history.size() : 0),
                (request.getMessage() != null ? Math.min(request.getMessage().length(), 120) : 0)
        );

        Map<String, Object> userMessage = new HashMap<>();
        // 【修复消息覆盖Bug】user 和 assistant 必须各自独立 UUID：
        // 之前两者共享一个 messageUuid，导致"按 UUID 回写"时两条消息会互相覆盖：
        //  - expertTrace（属于 assistant）被写入用户消息 → 你看到"第二条用户消息里有工具调用链"
        //  - searchResults（属于 assistant）按 UUID 命中 assistant，但 expertTrace 异步命中用户消息 → 错位
        // 现在独立生成两个 UUID：userMessageUuid 对应 role=user；assistantMessageUuid 对应 role=assistant
        final String userMessageUuid = java.util.UUID.randomUUID().toString();
        final String assistantMessageUuid = java.util.UUID.randomUUID().toString();
        userMessage.put("role", "user");
        userMessage.put("content", request.getMessage());
        userMessage.put("messageType", messageType);
        userMessage.put("mediaUrl", request.getMediaUrl());
        if (request.getMediaUrls() != null && !request.getMediaUrls().isEmpty()) {
            userMessage.put("mediaUrls", request.getMediaUrls());
        }
        userMessage.put("timestamp", System.currentTimeMillis());
        userMessage.put("messageUuid", userMessageUuid);
        
        String firstMediaUrl = request.getMediaUrl();
        if (firstMediaUrl == null && request.getMediaUrls() != null && !request.getMediaUrls().isEmpty()) {
            firstMediaUrl = request.getMediaUrls().get(0);
        }
        sessionService.saveMessage(sessionId, userMessage, messageType, firstMediaUrl);

        Map<String, Object> requestBody = new HashMap<>();
        requestBody.put("message", request.getMessage());
        requestBody.put("history", history);
        requestBody.put("user_id", userId);
        requestBody.put("session_id", String.valueOf(sessionId));
        requestBody.put("message_type", messageType);
        requestBody.put("media_url", firstMediaUrl);
        if (request.getMediaUrls() != null && !request.getMediaUrls().isEmpty()) {
            requestBody.put("media_urls", request.getMediaUrls());
        }
        // message_uuid：保持向后兼容（更新用户消息正文/提取文本用，历史链路/快速模式都用它）
        requestBody.put("message_uuid", userMessageUuid);
        // assistant_message_uuid：新增（Agent 写 assistant 侧字段时使用：expertTrace / searchResults）
        requestBody.put("assistant_message_uuid", assistantMessageUuid);
        requestBody.put("mode", request.getMode() != null ? request.getMode() : "fast");

        return outputStream -> {
            StringBuilder responseBuilder = new StringBuilder();
            StringBuilder searchResultsBuilder = new StringBuilder();
            StringBuilder lineBuffer = new StringBuilder();
            CountDownLatch latch = new CountDownLatch(1);
            Disposable disposable = null;
            // SSE汇总：流式 onComplete 写、外层 finally 统一打日志（和聊天完成合并一条）
            java.util.concurrent.atomic.AtomicReference<String> sseSummary = new java.util.concurrent.atomic.AtomicReference<>("");
            // 超时标志：try 内 latch.await 赋值，try 外 [聊天完成] 汇总使用
            final java.util.concurrent.atomic.AtomicBoolean timedOut = new java.util.concurrent.atomic.AtomicBoolean(false);

            try {
                String jsonBody = objectMapper.writeValueAsString(requestBody);

                AtomicInteger chunkCount = new AtomicInteger(0);
                // 日志汇总：每行分类计数（解决原来每 chunk 打原文、搜索结果每块打 length 的重复刷屏）
                AtomicInteger jsonLines = new AtomicInteger(0);
                AtomicInteger plainLines = new AtomicInteger(0);
                AtomicInteger contentLines = new AtomicInteger(0);
                AtomicInteger searchLines = new AtomicInteger(0);
                AtomicLong contentChars = new AtomicLong(0);
                final long agentStartNs = System.nanoTime();

                Mono<ClientResponse> clientResponseMono = webClient.post()
                        .uri("/chat")
                        .contentType(MediaType.APPLICATION_JSON)
                        .accept(MediaType.TEXT_EVENT_STREAM)
                        .body(BodyInserters.fromValue(jsonBody))
                        .exchange();

                disposable = clientResponseMono.flatMapMany(clientResponse -> {
                    // Agent HTTP 状态降 DEBUG：正常 200 无信息价值，错误会在 error 回调里打 ERROR
                    logger.debug("[Agent] 响应状态 sessionId={} status={}", sessionId, clientResponse.statusCode());
                    return clientResponse.bodyToFlux(DataBuffer.class);
                }).subscribe(
                    dataBuffer -> {
                        try {
                            byte[] bytes = new byte[dataBuffer.readableByteCount()];
                            dataBuffer.read(bytes);
                            DataBufferUtils.release(dataBuffer);

                            String chunk = new String(bytes, StandardCharsets.UTF_8);
                            chunkCount.incrementAndGet();

                            // 【降噪】每块原文只打 DEBUG（之前默认级别会被大量 SSE 分块刷屏）
                            logger.debug("[Agent] 接收分块 sessionId={} bytes={}", sessionId, bytes.length);

                            lineBuffer.append(chunk);
                            String bufferStr = lineBuffer.toString();
                            lineBuffer.setLength(0);
                            int newlineIdx = bufferStr.indexOf('\n');

                            while (newlineIdx >= 0) {
                                String line = bufferStr.substring(0, newlineIdx).trim();
                                bufferStr = bufferStr.substring(newlineIdx + 1);
                                newlineIdx = bufferStr.indexOf('\n');

                                if (!line.isEmpty()) {
                                    String contentToWrite = line;
                                    if (line.startsWith("{")) {
                                        jsonLines.incrementAndGet();
                                        try {
                                            Map<String, Object> jsonChunk = objectMapper.readValue(line,
                                                    new TypeReference<Map<String, Object>>() {});
                                            String type = (String) jsonChunk.get("type");
                                            if ("content".equals(type)) {
                                                String content = (String) jsonChunk.get("data");
                                                if (content != null) {
                                                    contentLines.incrementAndGet();
                                                    contentChars.addAndGet(content.length());
                                                    responseBuilder.append(content);
                                                }
                                            } else if ("search_results".equals(type)) {
                                                searchLines.incrementAndGet();
                                                Object data = jsonChunk.get("data");
                                                String searchResults = objectMapper.writeValueAsString(data);
                                                searchResultsBuilder.append(searchResults);
                                                // 【降噪】搜索结果只打 DEBUG，保留长度；结束时会打汇总 INFO
                                                logger.debug("[搜索] 提取分段 sessionId={} len={}", sessionId, searchResults.length());
                                            }
                                        } catch (Exception e) {
                                            logger.debug("[Agent] 解析JSON line失败按普通内容 sessionId={} err={}", sessionId, e.getMessage());
                                            responseBuilder.append(line);
                                        }
                                    } else {
                                        plainLines.incrementAndGet();
                                        responseBuilder.append(line);
                                    }

                                    outputStream.write(line.getBytes(StandardCharsets.UTF_8));
                                    outputStream.write('\n');
                                    outputStream.flush();
                                }
                            }

                            lineBuffer.append(bufferStr);
                        } catch (IOException e) {
                            logger.error("[Agent] 写入输出流失败 sessionId={} err={}", sessionId, e.getMessage());
                        }
                    },
                    error -> {
                        // 异常：统一加 sessionId + 分类前缀，便于和正常请求日志关联
                        logger.error("[Agent] 流异常 sessionId={} err={}", sessionId, error.getMessage(), error);
                        latch.countDown();
                    },
                    () -> {
                        String remaining = lineBuffer.toString().trim();
                        if (!remaining.isEmpty()) {
                            if (remaining.startsWith("{")) {
                                try {
                                    Map<String, Object> jsonChunk = objectMapper.readValue(remaining,
                                            new TypeReference<Map<String, Object>>() {});
                                    String type = (String) jsonChunk.get("type");
                                    if ("content".equals(type)) {
                                        String content = (String) jsonChunk.get("data");
                                        if (content != null) {
                                            contentLines.incrementAndGet();
                                            contentChars.addAndGet(content.length());
                                            responseBuilder.append(content);
                                        }
                                    } else if ("search_results".equals(type)) {
                                        searchLines.incrementAndGet();
                                        Object data = jsonChunk.get("data");
                                        String searchResults = objectMapper.writeValueAsString(data);
                                        searchResultsBuilder.append(searchResults);
                                    }
                                } catch (Exception e) {
                                    logger.debug("[Agent] 解析剩余JSON失败 sessionId={} err={}", sessionId, e.getMessage());
                                    responseBuilder.append(remaining);
                                }
                            } else {
                                plainLines.incrementAndGet();
                                responseBuilder.append(remaining);
                            }

                            try {
                                outputStream.write(remaining.getBytes(StandardCharsets.UTF_8));
                                outputStream.write('\n');
                                outputStream.flush(); // 【修复】最后一块也强制 flush，避免最后一行没换行被缓存导致前端丢失
                            } catch (IOException e) {
                                throw new RuntimeException(e);
                            }
                        }
                        // 【合并汇总】SSE完成 与 聊天完成 合并成一条 INFO，避免同一请求两行汇总。
                        // 用 Atomic 引用在流式 onComplete 里写汇总值，外层 finally 读出后只打一次。
                        double ms = (System.nanoTime() - agentStartNs) / 1_000_000.0;
                        sseSummary.set(
                            String.format(
                                "rawChunks=%d jsonLines=%d plainLines=%d contentLines=%d searchLines=%d bufferRemaining=%d sseMs=%.1f",
                                chunkCount.get(), jsonLines.get(), plainLines.get(),
                                contentLines.get(), searchLines.get(),
                                (lineBuffer != null ? lineBuffer.length() : 0), ms
                            )
                        );
                        latch.countDown();
                    }
                );

                boolean completed = latch.await(120, TimeUnit.SECONDS);
                if (!completed) {
                    timedOut.set(true);
                    // 超时：明确打出已积累的字数和 lineBuffer 残留，便于定位"Agent 返回了但前端没看到"这类场景
                    // WARN 级别保留（是异常场景）
                    logger.warn(
                            "[SSE超时] 超过120秒 sessionId={} replyLen={} lineBuffer={} chunks={}",
                            sessionId, responseBuilder.length(),
                            (lineBuffer != null ? lineBuffer.length() : 0), chunkCount.get()
                    );
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
                assistantMessage.put("messageUuid", assistantMessageUuid);

                int searchLen = 0;
                if (searchResultsBuilder.length() > 0) {
                    String searchResults = searchResultsBuilder.toString();
                    assistantMessage.put("searchResults", searchResults);
                    searchLen = searchResults.length();
                }
                // 【关键时序】先 saveMessage，确保 Redis/DB 里 assistant 消息已经存在。
                // 否则 Agent 的 update_backend_expert_trace（asyncio.create_task 触发）可能比这里 saveMessage 更早执行，
                // 导致按 assistantMessageUuid 在 Redis 里 scan 不到 → 匹配到同 session 里的其它消息（可能是 user 消息）。
                sessionService.saveMessage(sessionId, assistantMessage, "TEXT", null);

                // 【只保留 1 条汇总 INFO】合并：请求概览 + SSE细节 + 最终结果
                // 同时打印 userUuid/assistantUuid，便于和 Agent 回写日志对齐
                logger.info(
                        "[聊天完成] sessionId={} userUuid={} assistantUuid={} replyLen={} searchLen={} timeout={} {}",
                        sessionId, userMessageUuid, assistantMessageUuid,
                        responseBuilder.length(), searchLen,
                        timedOut.get() ? "Y" : "N",
                        (sseSummary.get() != null && !sseSummary.get().isEmpty() ? sseSummary.get() : "sse=<none>")
                );
            } else {
                // 无有效响应：WARN 级别保留（异常场景），附带 SSE 摘要便于定位
                logger.warn("[聊天完成] 无有效响应 sessionId={} userUuid={} assistantUuid={} timeout={} {}",
                        sessionId, userMessageUuid, assistantMessageUuid,
                        timedOut.get() ? "Y" : "N",
                        (sseSummary.get() != null && !sseSummary.get().isEmpty() ? sseSummary.get() : "sse=<none>")
                );
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

    @PostMapping("/upload/images")
    public ResponseEntity<Map<String, Object>> uploadImages(@RequestParam("files") MultipartFile[] files) {
        Map<String, Object> result = new HashMap<>();
        
        try {
            if (files == null || files.length == 0) {
                result.put("code", 400);
                result.put("message", "请选择要上传的图片");
                return ResponseEntity.badRequest().body(result);
            }
            
            List<String> urls = new java.util.ArrayList<>();
            for (MultipartFile file : files) {
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
                urls.add(url);
            }
            
            result.put("code", 200);
            result.put("data", urls);
            return ResponseEntity.ok(result);
        } catch (IOException e) {
            logger.error("批量图片上传失败: {}", e.getMessage());
            result.put("code", 500);
            result.put("message", "图片上传失败: " + e.getMessage());
            return ResponseEntity.internalServerError().body(result);
        }
    }

    @PostMapping("/upload/files")
    public ResponseEntity<Map<String, Object>> uploadFiles(@RequestParam("files") MultipartFile[] files) {
        Map<String, Object> result = new HashMap<>();
        
        try {
            if (files == null || files.length == 0) {
                result.put("code", 400);
                result.put("message", "请选择要上传的文件");
                return ResponseEntity.badRequest().body(result);
            }
            
            List<String> urls = new java.util.ArrayList<>();
            for (MultipartFile file : files) {
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
                urls.add(url);
            }
            
            result.put("code", 200);
            result.put("data", urls);
            return ResponseEntity.ok(result);
        } catch (IOException e) {
            logger.error("批量文件上传失败: {}", e.getMessage());
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

    /**
     * 内部接口：Agent → 后端，复用现成白名单的 /api/message/update-content 统一回写 assistant 消息。
     * 设计意图（避免再次出现 expertTrace 401）：
     *  - 不新增 URL（否则需要同步 InterceptorConfig 白名单 + 重新编译 jar，用户当前旧 jar 没白名单就会 401）
     *  - 统一走已注册的 update-content 通路：Token 拦截器排除 + Internal 密钥校验，两重都已命中
     *  - 参数全部可选：message / extracted_text / expert_trace，哪个字段非空就更新哪个；允许一次只更新 expert_trace
     *  - 对老调用完全兼容（4参数 case：只传 message + extracted_text，不传 expert_trace 行为不变）
     */
    @PostMapping("/message/update-content")
    public ResponseEntity<Map<String, Object>> updateMessageContent(@RequestBody Map<String, Object> request) {
        Map<String, Object> result = new HashMap<>();

        try {
            Long sessionId = Long.parseLong(request.get("session_id").toString());
            String messageUuid = (String) request.get("message_uuid");
            String message = request.get("message") != null ? (String) request.get("message") : null;
            String extractedText = request.get("extracted_text") != null ? (String) request.get("extracted_text") : null;
            String expertTrace = request.get("expert_trace") != null ? (String) request.get("expert_trace") : null;

            sessionService.updateMessageContent(sessionId, messageUuid, message, extractedText, expertTrace);

            result.put("code", 200);
            result.put("message", "消息内容更新成功");
            return ResponseEntity.ok(result);
        } catch (Exception e) {
            logger.error("更新消息内容失败: {}", e.getMessage(), e);
            result.put("code", 500);
            result.put("message", "更新消息内容失败: " + e.getMessage());
            return ResponseEntity.internalServerError().body(result);
        }
    }

    @PostMapping("/message/update-search-results")
    public ResponseEntity<Map<String, Object>> updateMessageSearchResults(@RequestBody Map<String, Object> request) {
        Map<String, Object> result = new HashMap<>();
        
        try {
            Long sessionId = Long.parseLong(request.get("session_id").toString());
            String messageUuid = (String) request.get("message_uuid");
            String searchResults = (String) request.get("search_results");
            
            sessionService.updateMessageSearchResults(sessionId, messageUuid, searchResults);
            
            result.put("code", 200);
            result.put("message", "消息搜索结果更新成功");
            return ResponseEntity.ok(result);
        } catch (Exception e) {
            logger.error("更新消息搜索结果失败: {}", e.getMessage());
            result.put("code", 500);
            result.put("message", "更新消息搜索结果失败: " + e.getMessage());
            return ResponseEntity.internalServerError().body(result);
        }
    }

    /**
     * 内部接口：Agent → 后端，回写专家模式编排+工具执行跟踪数据（expertTrace）
     * 把 expertTrace 塞到 assistant 消息 JSON 的顶层字段，Redis 同步覆盖 + MySQL 异步回写 session_detail.messages。
     * （完全沿用 update-search-results 风格的内部接口；鉴权风格同样照抄现有内部接口，不额外加硬门禁）
     */
    @PostMapping("/message/update-expert-trace")
    public ResponseEntity<Map<String, Object>> updateMessageExpertTrace(@RequestBody Map<String, Object> request) {
        Map<String, Object> result = new HashMap<>();
        try {
            Long sessionId = Long.parseLong(request.get("session_id").toString());
            String messageUuid = (String) request.get("message_uuid");
            String expertTrace = (String) request.get("expert_trace");
            // 每条专家请求可能 2~3 次回写，统一降 DEBUG；需要排查时看 DEBUG 级即可
            logger.debug("[专家模式] 收到回写 expertTrace 请求: sessionId={}, messageUuid={}, length={}",
                sessionId, messageUuid, expertTrace != null ? expertTrace.length() : 0);

            sessionService.updateMessageExpertTrace(sessionId, messageUuid, expertTrace);

            result.put("code", 200);
            result.put("message", "专家模式跟踪数据更新成功");
            return ResponseEntity.ok(result);
        } catch (Exception e) {
            logger.error("[专家模式] 更新 expertTrace 失败: {}", e.getMessage(), e);
            result.put("code", 500);
            result.put("message", "更新专家模式跟踪数据失败: " + e.getMessage());
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
