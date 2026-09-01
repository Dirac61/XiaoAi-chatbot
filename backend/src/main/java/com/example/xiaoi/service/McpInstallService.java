package com.example.xiaoi.service;

import com.example.xiaoi.common.Result;

import java.util.Map;

/**
 * MCP 插件安装管理服务
 * 负责插件的安装、卸载、环境变量更新、启用/禁用及已安装列表查询
 * 安装/卸载/更新环境变量会先调用 Agent 维护堆内存映射，再操作 MySQL
 */
public interface McpInstallService {

    /**
     * 安装 MCP 插件
     * 调用 Agent 建堆内存映射，并将 Agent 返回的 fingerprint 和 env_encrypted 存入 MySQL
     * 若已存在安装记录则更新，否则新增
     *
     * @param userId    用户 ID
     * @param mcpId     MCP 插件标识
     * @param envValues 环境变量（如 API Key 等）
     * @return 安装结果
     */
    Result<?> install(Long userId, String mcpId, Map<String, String> envValues);

    /**
     * 卸载 MCP 插件
     * 先调 Agent 释放堆内存映射，再删除 MySQL 记录
     *
     * @param userId 用户 ID
     * @param mcpId  MCP 插件标识
     * @return 卸载结果
     */
    Result<?> uninstall(Long userId, String mcpId);

    /**
     * 更新环境变量（如 Token）
     * 先调 Agent 更新堆内存映射，拿回新的 fingerprint 和 env_encrypted 更新 MySQL
     *
     * @param userId    用户 ID
     * @param mcpId     MCP 插件标识
     * @param envValues 新的环境变量
     * @return 更新结果
     */
    Result<?> updateEnv(Long userId, String mcpId, Map<String, String> envValues);

    /**
     * 启用 MCP 插件（仅更新 MySQL enabled 字段）
     *
     * @param userId 用户 ID
     * @param mcpId  MCP 插件标识
     * @return 启用结果
     */
    Result<?> enable(Long userId, String mcpId);

    /**
     * 禁用 MCP 插件（仅更新 MySQL enabled 字段）
     *
     * @param userId 用户 ID
     * @param mcpId  MCP 插件标识
     * @return 禁用结果
     */
    Result<?> disable(Long userId, String mcpId);

    /**
     * 获取用户已安装的 MCP 插件列表
     *
     * @param userId 用户 ID
     * @return 已安装列表
     */
    Result<?> getInstalledList(Long userId);
}
