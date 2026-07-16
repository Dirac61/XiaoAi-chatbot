package com.example.xiaoi.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 会话详情实体类
 * 对应 session_detail 表，存储每条消息的详细内容
 * 每条记录对应一条消息（JSON 格式），支持分页查询历史消息
 */
@Data
@TableName("session_detail")
public class SessionDetail {

    /** 主键 ID，自增 */
    @TableId(type = IdType.AUTO)
    private Long id;

    /** 会话 ID，关联 session 表 */
    @TableField("session_id")
    private Long sessionId;

    /** 消息内容，JSON 格式存储（包含 role、content、timestamp、messageType、mediaUrl） */
    @TableField("messages")
    private String messages;

    /** 消息类型：TEXT/IMAGE/FILE/VOICE */
    @TableField("message_type")
    private String messageType;

    /** 媒体文件地址（OSS URL），TEXT和VOICE类型为NULL */
    @TableField("media_url")
    private String mediaUrl;

    /** 创建时间 */
    @TableField("created_at")
    private LocalDateTime createdAt;

    /** 更新时间 */
    @TableField("updated_at")
    private LocalDateTime updatedAt;
}