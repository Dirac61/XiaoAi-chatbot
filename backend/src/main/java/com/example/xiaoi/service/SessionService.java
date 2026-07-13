package com.example.xiaoi.service;

import com.example.xiaoi.entity.Session;

import java.util.List;
import java.util.Map;

/**
 * 会话服务接口
 * 提供会话管理、消息存储、消息查询等核心业务功能
 */
public interface SessionService {

    /**
     * 创建新会话
     * 使用雪花算法生成会话 ID
     * @param userId 用户 ID
     * @return 会话 ID
     */
    Long createSession(Long userId);

    /**
     * 获取用户的会话列表
     * 按更新时间倒序排列
     * @param userId 用户 ID
     * @return 会话列表
     */
    List<Session> getSessionsByUserId(Long userId);

    /**
     * 获取会话的消息列表（从 Redis 读取）
     * 最多返回 20 条，优先从 Redis 缓存读取
     * @param sessionId 会话 ID
     * @return 包含 messages 的 Map
     */
    Map<String, Object> getSessionMessages(Long sessionId);

    /**
     * 保存消息到 Redis 和 MySQL
     * Redis 同步写入（毫秒级），MySQL 通过 @Async 异步写入
     * @param sessionId 会话 ID
     * @param message 消息内容（包含 role、content、timestamp）
     */
    void saveMessage(Long sessionId, Map<String, Object> message);

    /**
     * 分页获取会话消息（从 MySQL 读取）
     * 第一页查询后会预热 Redis 缓存
     * @param sessionId 会话 ID
     * @param pageNum 页码
     * @param pageSize 每页条数
     * @return 分页结果
     */
    Map<String, Object> getSessionMessagesByPage(Long sessionId, Integer pageNum, Integer pageSize);

    /**
     * 获取会话的消息总数
     * @param sessionId 会话 ID
     * @return 消息总数
     */
    Long getTotalMessageCount(Long sessionId);
}