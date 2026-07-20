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

/**
 * 会话管理控制器
 * 提供会话的创建、列表查询、消息查询等接口
 * 会话 ID 使用雪花算法生成，返回给前端时转为字符串（JS Number 精度不足）
 */
@RestController
@RequestMapping("/api")
public class SessionController {

    @Autowired
    private SessionService sessionService;

    /**
     * 创建新会话
     * 使用雪花算法生成 Long 类型的会话 ID
     * @return 创建结果，包含 sessionId
     */
    @PostMapping("/session/new")
    public Map<String, Object> createSession() {
        Map<String, Object> result = new HashMap<>();
        Long userId = UserContext.getUserId();
        
        Long sessionId = sessionService.createSession(userId);
        
        result.put("code", 200);
        result.put("message", "创建成功");
        result.put("data", Map.of("sessionId", String.valueOf(sessionId)));
        
        return result;
    }

    /**
     * 获取当前用户的会话列表
     * 按更新时间倒序排列，最新的会话排在前面
     * @return 会话列表，每条包含 id、userId、createdAt、updatedAt
     */
    @GetMapping("/sessions")
    public Map<String, Object> getSessions() {
        Map<String, Object> result = new HashMap<>();
        Long userId = UserContext.getUserId();
        
        List<Session> sessions = sessionService.getSessionsByUserId(userId);
        
        List<Map<String, Object>> sessionList = new ArrayList<>();
        for (Session session : sessions) {
            Map<String, Object> sessionMap = new HashMap<>();
            // 会话 ID 转为字符串，避免 JS Number 精度丢失
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

    /**
     * 获取会话的消息列表（从 Redis 读取，最多 20 条）
     * 优先从 Redis 读取，Redis 无数据时返回空列表
     * @param sessionId 会话 ID
     * @return 消息列表
     */
    @GetMapping("/session/messages")
    public Map<String, Object> getSessionMessages(@RequestParam("sessionId") Long sessionId) {
        Map<String, Object> result = new HashMap<>();
        
        Map<String, Object> messages = sessionService.getSessionMessages(sessionId);
        
        result.put("code", 200);
        result.put("message", "获取成功");
        result.put("data", messages);
        
        return result;
    }

    /**
     * 分页获取会话消息（从 MySQL 读取）
     * 第一页查询后会预热 Redis 缓存
     * @param sessionId 会话 ID
     * @param pageNum 页码，从 1 开始
     * @param pageSize 每页条数，默认 20
     * @return 分页结果，包含 messages、total、pageNum、pageSize、hasNext
     */
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

    /**
     * 获取会话的消息总数
     * @param sessionId 会话 ID
     * @return 消息总数
     */
    @GetMapping("/session/messages/count")
    public Map<String, Object> getMessageCount(@RequestParam("sessionId") Long sessionId) {
        Map<String, Object> result = new HashMap<>();
        
        Long count = sessionService.getTotalMessageCount(sessionId);
        
        result.put("code", 200);
        result.put("message", "获取成功");
        result.put("data", Map.of("count", count));
        
        return result;
    }

    /**
     * 删除会话及所有相关数据
     * 删除内容包括：MySQL中的session和session_detail记录、Redis中的会话缓存、OSS中的媒体文件、Qdrant中的记忆数据
     * @param sessionId 会话 ID
     * @return 删除结果
     */
    @DeleteMapping("/session/delete/{sessionId}")
    public Map<String, Object> deleteSession(@PathVariable("sessionId") Long sessionId) {
        Map<String, Object> result = new HashMap<>();
        
        boolean success = sessionService.deleteSession(sessionId);
        
        if (success) {
            result.put("code", 200);
            result.put("message", "删除成功");
        } else {
            result.put("code", 500);
            result.put("message", "删除失败");
        }
        
        return result;
    }
}