package com.example.xiaoi.dto;

import lombok.Data;

import java.util.List;

/**
 * 聊天请求 DTO
 * 用于接收前端发送的聊天消息（支持多模态：文本、图片、文件、语音）
 */
@Data
public class ChatRequest {
    /** 用户发送的消息内容 */
    private String message;
    /** 会话 ID，为空时创建新会话 */
    private Long sessionId;
    /** 用户 ID（预留字段，实际从 Token 中获取） */
    private Long userId;
    /** 消息类型：TEXT/IMAGE/FILE/VOICE，默认TEXT */
    private String messageType = "TEXT";
    /** 媒体文件地址（OSS URL），IMAGE/FILE类型使用（单文件） */
    private String mediaUrl;
    /** 媒体文件地址列表（支持多文件上传） */
    private List<String> mediaUrls;
    /** 模式：fast（快速模式）/ expert（专家模式），默认fast */
    private String mode = "fast";
}