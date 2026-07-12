package com.example.xiaoi.service;

import com.example.xiaoi.entity.Session;

import java.util.List;
import java.util.Map;

public interface SessionService {

    Long createSession(Long userId);

    List<Session> getSessionsByUserId(Long userId);

    Map<String, Object> getSessionMessages(Long sessionId);

    void saveMessage(Long sessionId, Map<String, Object> message);
}