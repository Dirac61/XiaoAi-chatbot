package com.example.xiaoi.controller;

import com.example.xiaoi.context.UserContext;
import com.example.xiaoi.entity.Session;
import com.example.xiaoi.service.SessionService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api")
public class SessionController {

    @Autowired
    private SessionService sessionService;

    @PostMapping("/session/new")
    public Map<String, Object> createSession() {
        Map<String, Object> result = new HashMap<>();
        Long userId = UserContext.getUserId();
        
        Long sessionId = sessionService.createSession(userId);
        
        result.put("code", 200);
        result.put("message", "创建成功");
        result.put("data", Map.of("sessionId", sessionId));
        
        return result;
    }

    @GetMapping("/sessions")
    public Map<String, Object> getSessions() {
        Map<String, Object> result = new HashMap<>();
        Long userId = UserContext.getUserId();
        
        List<Session> sessions = sessionService.getSessionsByUserId(userId);
        
        List<Map<String, Object>> sessionList = new ArrayList<>();
        for (Session session : sessions) {
            Map<String, Object> sessionMap = new HashMap<>();
            sessionMap.put("id", String.valueOf(session.getId()));
            sessionMap.put("userId", String.valueOf(session.getUserId()));
            sessionMap.put("createdAt", session.getCreatedAt());
            sessionMap.put("updatedAt", session.getUpdatedAt());
            sessionList.add(sessionMap);
        }
        
        result.put("code", 200);
        result.put("message", "获取成功");
        result.put("data", sessionList);
        
        return result;
    }

    @GetMapping("/session/messages")
    public Map<String, Object> getSessionMessages(@RequestParam("sessionId") Long sessionId) {
        Map<String, Object> result = new HashMap<>();
        
        Map<String, Object> messages = sessionService.getSessionMessages(sessionId);
        
        result.put("code", 200);
        result.put("message", "获取成功");
        result.put("data", messages);
        
        return result;
    }

    @GetMapping("/session/messages/page")
    public Map<String, Object> getSessionMessagesByPage(
            @RequestParam("sessionId") Long sessionId,
            @RequestParam(value = "pageNum", defaultValue = "1") Integer pageNum,
            @RequestParam(value = "pageSize", defaultValue = "20") Integer pageSize) {
        
        Map<String, Object> result = new HashMap<>();
        
        Map<String, Object> pageResult = sessionService.getSessionMessagesByPage(sessionId, pageNum, pageSize);
        
        result.put("code", 200);
        result.put("message", "获取成功");
        result.put("data", pageResult);
        
        return result;
    }

    @GetMapping("/session/messages/count")
    public Map<String, Object> getMessageCount(@RequestParam("sessionId") Long sessionId) {
        Map<String, Object> result = new HashMap<>();
        
        Long count = sessionService.getTotalMessageCount(sessionId);
        
        result.put("code", 200);
        result.put("message", "获取成功");
        result.put("data", Map.of("count", count));
        
        return result;
    }
}