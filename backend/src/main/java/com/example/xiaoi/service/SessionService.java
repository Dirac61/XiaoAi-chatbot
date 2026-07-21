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
     * @param message 消息内容（包含 role、content、timestamp、messageType、mediaUrl）
     * @param messageType 消息类型：TEXT/IMAGE/FILE/VOICE
     * @param mediaUrl 媒体文件地址（OSS URL），TEXT和VOICE类型为null
     */
    void saveMessage(Long sessionId, Map<String, Object> message, String messageType, String mediaUrl);

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

    /**
     * 更新消息内容（用于多模态消息异步提取文本后回写）
     * 通过消息UUID查找并更新消息的content字段，将用户提问和提取信息一起结构化存储
     * @param sessionId 会话 ID
     * @param messageUuid 消息唯一标识（UUID格式）
     * @param message 用户原始提问
     * @param extractedText 提取后的文本内容
     */
    void updateMessageContent(Long sessionId, String messageUuid, String message, String extractedText);

    /**
     * 更新消息的搜索结果（用于快速模式联网搜索后保存结果）
     * 通过消息UUID查找并更新消息的searchResults字段
     * @param sessionId 会话 ID
     * @param messageUuid 消息唯一标识（UUID格式）
     * @param searchResults 搜索结果JSON字符串（包含文章标题和URL）
     */
    void updateMessageSearchResults(Long sessionId, String messageUuid, String searchResults);

    /**
     * 删除会话及所有相关数据
     * 删除内容包括：MySQL中的session和session_detail记录、Redis中的会话缓存、OSS中的媒体文件、Qdrant中的记忆数据
     * @param sessionId 会话 ID
     * @return 删除是否成功
     */
    boolean deleteSession(Long sessionId);
}