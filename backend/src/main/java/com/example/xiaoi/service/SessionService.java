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
     * 仅保存占位消息到 Redis（不写 MySQL）。
     * 用于 SSE 流开始前预存 assistant 消息，确保 Agent 的 expertTrace 回写能扫到 UUID。
     * 流结束后调用 saveMessage 或 updateMessageContent 完成正式持久化。
     * @param sessionId 会话 ID
     * @param message 消息内容（含 role/content/messageUuid 等）
     */
    void savePlaceholderToRedis(Long sessionId, Map<String, Object> message);

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
     * 更新消息的多字段统一入口（复用现成内部接口 /api/message/update-content 的扩展版，解决 expertTrace 新 URL 白名单未同步导致 401 的问题）。
     * 参数可选策略：哪个字段传入非空就更新哪个；支持一次只更新 expertTrace。
     *  - message 非空 → 更新 msg.content（用户提问正文）
     *  - extractedText 非空 → 更新 msg.extractedText（图片提取文本）
     *  - expertTrace 非空 → 更新 msg.expertTrace（专家模式编排+工具执行跟踪）
     * 老调用兼容：继续传 expertTrace=null 时行为与 4 参数版本完全一致。
     * @param sessionId 会话 ID
     * @param messageUuid 消息唯一标识（UUID格式）
     * @param message 用户原始提问（可 null，为 null 不覆盖）
     * @param extractedText 提取后的文本内容（可 null，为 null 不覆盖）
     * @param expertTrace 专家模式跟踪 JSON 字符串（可 null，为 null 不覆盖）
     */
    void updateMessageContent(Long sessionId, String messageUuid, String message, String extractedText, String expertTrace);

    /**
     * 更新消息的搜索结果（用于快速模式联网搜索后保存结果）
     * 通过消息UUID查找并更新消息的searchResults字段
     * @param sessionId 会话 ID
     * @param messageUuid 消息唯一标识（UUID格式）
     * @param searchResults 搜索结果JSON字符串（包含文章标题和URL）
     */
    void updateMessageSearchResults(Long sessionId, String messageUuid, String searchResults);

    /**
     * 更新消息的专家模式跟踪数据（expertTrace）
     * expertTrace 包括：编排器每次 analysis、单步计划、每次工具调用完整执行结果（不摘要）。
     * 直接写入 assistant 消息 JSON 的顶层字段 expertTrace，保持 Redis 与 MySQL session_detail.messages
     * 中的结构一致（不需要改表结构）。
     * 写入流程：Redis LIST 中按 messageUuid 定位元素 → 塞 expertTrace → 同步覆盖写回 Redis →
     *          @Async 异步回写 MySQL session_detail.messages。
     * @param sessionId 会话 ID
     * @param messageUuid 助手回复消息的唯一标识（UUID）
     * @param expertTrace 专家模式跟踪 JSON 字符串（由 Agent 侧序列化）
     */
    void updateMessageExpertTrace(Long sessionId, String messageUuid, String expertTrace);

    /**
     * 删除会话及所有相关数据
     * 删除内容包括：MySQL中的session和session_detail记录、Redis中的会话缓存、OSS中的媒体文件、Qdrant中的记忆数据
     * @param sessionId 会话 ID
     * @return 删除是否成功
     */
    boolean deleteSession(Long sessionId);
}