package com.example.xiaoi.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 会话实体类
 * 对应 session 表，存储会话的基本信息
 */
@Data
@TableName("session")
public class Session {

    /** 会话 ID，使用雪花算法生成（Long 类型） */
    @TableId(type = IdType.INPUT)
    private Long id;

    /** 用户 ID，关联 user 表 */
    @TableField("user_id")
    private Long userId;

    /** 对话轮次，每收到一条 assistant 消息递增 */
    @TableField("turn_count")
    private Integer turnCount;

    /** 对话摘要，每 5 轮自动提取一次（从第 10 轮开始） */
    @TableField("summary")
    private String summary;

    /** 创建时间 */
    @TableField("created_at")
    private LocalDateTime createdAt;

    /** 更新时间，每次保存消息后更新 */
    @TableField("updated_at")
    private LocalDateTime updatedAt;
}