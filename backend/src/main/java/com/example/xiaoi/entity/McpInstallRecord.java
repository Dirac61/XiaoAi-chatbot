package com.example.xiaoi.entity;

import com.baomidou.mybatisplus.annotation.FieldFill;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;

/**
 * MCP 插件安装记录实体类
 * 对应 mcp_install_record 表，存储用户安装的 MCP 插件信息
 * fingerprint 和 env_values 由 Agent 加密返回，后端不存储明文密钥
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
@TableName("mcp_install_record")
public class McpInstallRecord {

    /** 主键 ID，自增 */
    @TableId(type = IdType.AUTO)
    private Long id;

    /** 用户 ID，关联 user 表 */
    @TableField("user_id")
    private Long userId;

    /** MCP 插件唯一标识 */
    @TableField("mcp_id")
    private String mcpId;

    /** MCP 插件版本号 */
    @TableField("mcp_version")
    private String mcpVersion;

    /** Agent 返回的内存映射指纹，用于卸载/更新时定位堆内存映射 */
    @TableField("fingerprint")
    private String fingerprint;

    /** Agent 加密返回的环境变量（含 Token 等敏感信息），后端不存储明文 */
    @TableField("env_values")
    private String envValues;

    /** 是否启用：1 启用，0 禁用 */
    @TableField("enabled")
    private Integer enabled;

    /** 安装时间，插入时自动填充 */
    @TableField(value = "installed_at", fill = FieldFill.INSERT)
    private LocalDateTime installedAt;

    /** 更新时间，插入和更新时自动填充 */
    @TableField(value = "updated_at", fill = FieldFill.INSERT_UPDATE)
    private LocalDateTime updatedAt;
}
