package com.example.xiaoi.dto;

import lombok.Data;

/**
 * 聊天请求 DTO
 * 用于接收前端发送的聊天消息
 */
@Data
public class ChatRequest {
    /** 用户发送的消息内容 */
    private String message;
    /** 会话 ID，为空时创建新会话 */
    private Long sessionId;
    /** 用户 ID（预留字段，实际从 Token 中获取） */
    private Long userId;
}