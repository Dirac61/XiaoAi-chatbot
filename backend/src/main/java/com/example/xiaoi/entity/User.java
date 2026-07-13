package com.example.xiaoi.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 用户实体类
 * 对应 user 表，存储用户基本信息
 * 密码使用 BCrypt 加密存储
 */
@Data
@TableName("user")
public class User {

    /** 用户 ID，自增 */
    @TableId(type = IdType.AUTO)
    private Long id;

    /** 用户名，唯一标识 */
    @TableField("username")
    private String username;

    /** 密码，BCrypt 加密存储 */
    @TableField("password")
    private String password;

    /** 创建时间 */
    @TableField("created_at")
    private LocalDateTime createdAt;

    /** 更新时间 */
    @TableField("updated_at")
    private LocalDateTime updatedAt;
}