package com.example.xiaoi.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.example.xiaoi.common.Result;
import com.example.xiaoi.entity.McpInstallRecord;
import com.example.xiaoi.mapper.McpInstallRecordMapper;
import com.example.xiaoi.service.McpInstallService;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.client.RestTemplate;

import java.time.LocalDateTime;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * MCP 插件安装管理服务实现
 * 安装/卸载/更新环境变量：先调用 Agent 维护堆内存映射，再操作 MySQL
 * enable/disable/列表查询：直接操作 MySQL
 * 环境变量明文仅用于调用 Agent，MySQL 中只存 Agent 加密返回的 env_encrypted
 */
@Service
public class McpInstallServiceImpl implements McpInstallService {

    private static final Logger logger = LoggerFactory.getLogger(McpInstallServiceImpl.class);

    @Autowired
    private McpInstallRecordMapper mcpInstallRecordMapper;

    @Autowired
    private RestTemplate restTemplate;

    @Autowired
    private ObjectMapper objectMapper;

    /** Agent 服务地址，默认 http://localhost:8000 */
    @Value("${agent.url:http://localhost:8000}")
    private String agentUrl;

    /**
     * 安装 MCP 插件
     * 流程：1. 检查是否已安装（已存在则走更新）2. 调 Agent /mcp/install 建堆内存映射
     *      3. 用 Agent 返回的 fingerprint 和 env_encrypted 写入 MySQL
     *
     * @param userId    用户 ID
     * @param mcpId     MCP 插件标识
     * @param envValues 环境变量（如 API Key）
     * @return 安装结果
     */
    @Override
    @Transactional(rollbackFor = Exception.class)
    public Result<?> install(Long userId, String mcpId, Map<String, String> envValues) {
        logger.info("开始安装 MCP 插件: userId={}, mcpId={}", userId, mcpId);

        // 先检查是否已存在安装记录（一个用户对同一 mcp 只能有一条记录）
        McpInstallRecord existing = findRecord(userId, mcpId);

        // 调用 Agent /mcp/install 让 Agent 建堆内存映射，返回 fingerprint 和 env_encrypted
        Map<String, Object> agentResp;
        try {
            agentResp = callAgent("/mcp/install", userId, mcpId, null, envValues);
        } catch (Exception e) {
            // Agent 调用失败直接返回错误，不写 MySQL，避免脏数据
            logger.error("调用 Agent 安装接口失败: userId={}, mcpId={}, 错误={}", userId, mcpId, e.getMessage());
            return Result.error("Agent 安装接口调用失败: " + e.getMessage());
        }

        String fingerprint = (String) agentResp.get("fingerprint");
        String envEncrypted = (String) agentResp.get("env_encrypted");
        String version = agentResp.get("version") != null ? agentResp.get("version").toString() : null;
        logger.info("Agent 安装成功返回指纹: userId={}, mcpId={}, fingerprint={}", userId, mcpId, fingerprint);

        LocalDateTime now = LocalDateTime.now();
        if (existing != null) {
            // 已存在则更新：刷新指纹、加密环境变量、版本、启用状态
            existing.setFingerprint(fingerprint);
            existing.setEnvValues(envEncrypted);
            existing.setMcpVersion(version);
            existing.setEnabled(1);
            existing.setUpdatedAt(now);
            mcpInstallRecordMapper.updateById(existing);
            logger.info("MCP 插件安装记录已更新: userId={}, mcpId={}", userId, mcpId);
            return Result.success(existing);
        }

        // 不存在则新增
        McpInstallRecord record = new McpInstallRecord();
        record.setUserId(userId);
        record.setMcpId(mcpId);
        record.setMcpVersion(version);
        record.setFingerprint(fingerprint);
        record.setEnvValues(envEncrypted);
        record.setEnabled(1);
        record.setInstalledAt(now);
        record.setUpdatedAt(now);
        mcpInstallRecordMapper.insert(record);
        logger.info("MCP 插件安装记录已新增: userId={}, mcpId={}", userId, mcpId);
        return Result.success(record);
    }

    /**
     * 卸载 MCP 插件
     * 流程：1. 调 Agent /mcp/uninstall 释放堆内存映射 2. 删除 MySQL 记录
     *
     * @param userId 用户 ID
     * @param mcpId  MCP 插件标识
     * @return 卸载结果
     */
    @Override
    @Transactional(rollbackFor = Exception.class)
    public Result<?> uninstall(Long userId, String mcpId) {
        logger.info("开始卸载 MCP 插件: userId={}, mcpId={}", userId, mcpId);

        McpInstallRecord record = findRecord(userId, mcpId);
        if (record == null) {
            logger.warn("卸载失败，未找到安装记录: userId={}, mcpId={}", userId, mcpId);
            return Result.error("未找到该插件的安装记录");
        }

        // 先调 Agent 卸载（用指纹定位堆内存映射）
        try {
            callAgent("/mcp/uninstall", userId, mcpId, record.getFingerprint(), null);
        } catch (Exception e) {
            // Agent 卸载失败仍删除 MySQL 记录，避免脏数据残留（日志告警）
            logger.error("调用 Agent 卸载接口失败，仍清理 MySQL 记录: userId={}, mcpId={}, 错误={}",
                    userId, mcpId, e.getMessage());
        }

        mcpInstallRecordMapper.deleteById(record.getId());
        logger.info("MCP 插件卸载完成: userId={}, mcpId={}", userId, mcpId);
        return Result.success();
    }

    /**
     * 更新环境变量（如 Token）
     * 流程：1. 调 Agent /mcp/update-env 拿新 fingerprint 和 env_encrypted 2. 更新 MySQL
     *
     * @param userId    用户 ID
     * @param mcpId     MCP 插件标识
     * @param envValues 新的环境变量
     * @return 更新结果
     */
    @Override
    @Transactional(rollbackFor = Exception.class)
    public Result<?> updateEnv(Long userId, String mcpId, Map<String, String> envValues) {
        logger.info("开始更新 MCP 插件环境变量: userId={}, mcpId={}", userId, mcpId);

        McpInstallRecord record = findRecord(userId, mcpId);
        if (record == null) {
            logger.warn("更新环境变量失败，未找到安装记录: userId={}, mcpId={}", userId, mcpId);
            return Result.error("未找到该插件的安装记录");
        }

        // 调 Agent 更新环境变量，拿回新指纹和加密环境变量
        Map<String, Object> agentResp;
        try {
            agentResp = callAgent("/mcp/update-env", userId, mcpId, record.getFingerprint(), envValues);
        } catch (Exception e) {
            logger.error("调用 Agent 更新环境变量接口失败: userId={}, mcpId={}, 错误={}",
                    userId, mcpId, e.getMessage());
            return Result.error("Agent 更新环境变量接口调用失败: " + e.getMessage());
        }

        String fingerprint = (String) agentResp.get("fingerprint");
        String envEncrypted = (String) agentResp.get("env_encrypted");
        record.setFingerprint(fingerprint);
        record.setEnvValues(envEncrypted);
        record.setUpdatedAt(LocalDateTime.now());
        mcpInstallRecordMapper.updateById(record);
        logger.info("MCP 插件环境变量已更新: userId={}, mcpId={}", userId, mcpId);
        return Result.success(record);
    }

    /**
     * 启用 MCP 插件（仅更新 MySQL enabled 字段）
     *
     * @param userId 用户 ID
     * @param mcpId  MCP 插件标识
     * @return 启用结果
     */
    @Override
    @Transactional(rollbackFor = Exception.class)
    public Result<?> enable(Long userId, String mcpId) {
        logger.info("启用 MCP 插件: userId={}, mcpId={}", userId, mcpId);
        return toggleEnabled(userId, mcpId, 1);
    }

    /**
     * 禁用 MCP 插件（仅更新 MySQL enabled 字段）
     *
     * @param userId 用户 ID
     * @param mcpId  MCP 插件标识
     * @return 禁用结果
     */
    @Override
    @Transactional(rollbackFor = Exception.class)
    public Result<?> disable(Long userId, String mcpId) {
        logger.info("禁用 MCP 插件: userId={}, mcpId={}", userId, mcpId);
        return toggleEnabled(userId, mcpId, 0);
    }

    /**
     * 获取用户已安装的 MCP 插件列表
     *
     * @param userId 用户 ID
     * @return 已安装列表
     */
    @Override
    public Result<?> getInstalledList(Long userId) {
        logger.info("查询已安装 MCP 插件列表: userId={}", userId);
        LambdaQueryWrapper<McpInstallRecord> queryWrapper = new LambdaQueryWrapper<>();
        queryWrapper.eq(McpInstallRecord::getUserId, userId);
        queryWrapper.orderByDesc(McpInstallRecord::getInstalledAt);
        List<McpInstallRecord> list = mcpInstallRecordMapper.selectList(queryWrapper);
        return Result.success(list);
    }

    // ===== 以下是内部辅助方法 =====

    /**
     * 按 userId + mcpId 查询单条安装记录
     * 设计意图：一个用户对同一 MCP 只允许一条记录，用唯一索引 + 这里二次校验
     *
     * @param userId 用户 ID
     * @param mcpId  MCP 插件标识
     * @return 安装记录，不存在返回 null
     */
    private McpInstallRecord findRecord(Long userId, String mcpId) {
        LambdaQueryWrapper<McpInstallRecord> queryWrapper = new LambdaQueryWrapper<>();
        queryWrapper.eq(McpInstallRecord::getUserId, userId);
        queryWrapper.eq(McpInstallRecord::getMcpId, mcpId);
        return mcpInstallRecordMapper.selectOne(queryWrapper);
    }

    /**
     * 切换启用状态
     *
     * @param userId  用户 ID
     * @param mcpId   MCP 插件标识
     * @param enabled 1 启用 / 0 禁用
     * @return 操作结果
     */
    private Result<?> toggleEnabled(Long userId, String mcpId, Integer enabled) {
        McpInstallRecord record = findRecord(userId, mcpId);
        if (record == null) {
            logger.warn("切换启用状态失败，未找到安装记录: userId={}, mcpId={}", userId, mcpId);
            return Result.error("未找到该插件的安装记录");
        }
        record.setEnabled(enabled);
        record.setUpdatedAt(LocalDateTime.now());
        mcpInstallRecordMapper.updateById(record);
        logger.info("MCP 插件启用状态已切换: userId={}, mcpId={}, enabled={}", userId, mcpId, enabled);
        return Result.success(record);
    }

    /**
     * 调用 Agent 的 MCP 管理接口
     * 请求体：{user_id, mcp_id, fingerprint?, env_values?}
     * 响应体：{fingerprint, env_encrypted, version?}
     * 字段名使用 snake_case 与 Agent (Python) 约定一致
     *
     * @param path        Agent 接口路径，如 /mcp/install
     * @param userId      用户 ID
     * @param mcpId       MCP 插件标识
     * @param fingerprint 已有指纹（uninstall/update-env 时传入定位堆内存映射；install 传 null）
     * @param envValues   环境变量明文（install/update-env 时传入；uninstall 传 null）
     * @return Agent 返回的 JSON Map
     */
    @SuppressWarnings("unchecked")
    private Map<String, Object> callAgent(String path, Long userId, String mcpId,
                                          String fingerprint, Map<String, String> envValues) {
        // 组装请求体：snake_case 与 Agent (Python) 约定一致
        Map<String, Object> body = new HashMap<>();
        body.put("user_id", userId);
        body.put("mcp_id", mcpId);
        if (fingerprint != null) {
            body.put("fingerprint", fingerprint);
        }
        if (envValues != null) {
            body.put("env_values", envValues);
        }

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        HttpEntity<Map<String, Object>> request = new HttpEntity<>(body, headers);

        String url = agentUrl + path;
        logger.info("调用 Agent 接口: url={}, mcpId={}", url, mcpId);

        ResponseEntity<String> response = restTemplate.postForEntity(url, request, String.class);
        if (!response.getStatusCode().is2xxSuccessful() || response.getBody() == null) {
            logger.error("Agent 接口返回非 2xx: url={}, status={}", url, response.getStatusCode());
            throw new RuntimeException("Agent 接口返回异常状态: " + response.getStatusCode());
        }

        try {
            return objectMapper.readValue(response.getBody(), new TypeReference<Map<String, Object>>() {});
        } catch (Exception e) {
            // 长文本截断打印，避免日志膨胀
            String bodyPreview = response.getBody() != null
                    ? response.getBody().substring(0, Math.min(200, response.getBody().length())) : "null";
            logger.error("解析 Agent 响应失败: url={}, body={}", url, bodyPreview);
            throw new RuntimeException("解析 Agent 响应失败: " + e.getMessage());
        }
    }
}
