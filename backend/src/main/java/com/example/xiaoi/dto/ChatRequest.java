package com.example.xiaoi.dto;

import lombok.Data;

@Data
public class ChatRequest {
    private String message;
    private Long sessionId;
    private Long userId;
}