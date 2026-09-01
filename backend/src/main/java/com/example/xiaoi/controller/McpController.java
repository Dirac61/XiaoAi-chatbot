package com.example.xiaoi.controller;

import com.example.xiaoi.common.Result;
import com.example.xiaoi.context.UserContext;
import com.example.xiaoi.service.McpInstallService;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.client.RestTemplate;

import java.util.Map;

/**
 * MCP 插件市场控制器
 * 提供插件市场浏览、安装、卸载、启用/禁用、环境变量管理接口
 * 市场列表和详情代理调用 Agent (localhost:8000/mcp/market) 获取
 * 安装/卸载等操作委托 McpInstallService 完成（内部联动 Agent + MySQL）
 */
@RestController
@RequestMapping("/api/mcp")
public class McpController {

    private static final Logger logger = LoggerFactory.getLogger(McpController.class);

    @Autowired
    private McpInstallService mcpInstallService;

    @Autowired
    private RestTemplate restTemplate;

    @Autowired
    private ObjectMapper objectMapper;

    /** Agent 服务地址，默认 http://localhost:8000 */
    @Value("${agent.url:http://localhost:8000}")
    private String agentUrl;

    /**
     * 获取 MCP 市场列表
     * 代理调用 Agent /mcp/market，返回市场全量插件信息
     *
     * @return 市场列表
     */
    @GetMapping("/market")
    public Result<?> getMarket() {
        String url = agentUrl + "/mcp/market";
        logger.info("获取 MCP 市场列表: url={}", url);
        try {
            ResponseEntity<String> response = restTemplate.getForEntity(url, String.class);
            if (response.getStatusCode().is2xxSuccessful() && response.getBody() != null) {
                // 解析为 Object 透传，避免 Agent 原始 JSON 被二次转义
                Object data = objectMapper.readValue(response.getBody(), Object.class);
                logger.info("获取 MCP 市场列表成功");
                return Result.success(data);
            }
            logger.error("获取 MCP 市场列表失败: status={}", response.getStatusCode());
            return Result.error("获取市场列表失败");
        } catch (Exception e) {
            logger.error("调用 Agent 市场列表接口异常: {}", e.getMessage());
            return Result.error("获取市场列表异常: " + e.getMessage());
        }
    }

    /**
     * 获取单个 MCP 插件详情
     *
     * @param mcpId MCP 插件标识
     * @return 插件详情
     */
    @GetMapping("/market/{mcpId}")
    public Result<?> getMarketDetail(@PathVariable("mcpId") String mcpId) {
        String url = agentUrl + "/mcp/market/" + mcpId;
        logger.info("获取 MCP 插件详情: url={}, mcpId={}", url, mcpId);
        try {
            ResponseEntity<String> response = restTemplate.getForEntity(url, String.class);
            if (response.getStatusCode().is2xxSuccessful() && response.getBody() != null) {
                Object data = objectMapper.readValue(response.getBody(), Object.class);
                logger.info("获取 MCP 插件详情成功: mcpId={}", mcpId);
                return Result.success(data);
            }
            logger.error("获取 MCP 插件详情失败: mcpId={}, status={}", mcpId, response.getStatusCode());
            return Result.error("获取插件详情失败");
        } catch (Exception e) {
            logger.error("调用 Agent 插件详情接口异常: mcpId={}, 错误={}", mcpId, e.getMessage());
            return Result.error("获取插件详情异常: " + e.getMessage());
        }
    }

    /**
     * 安装 MCP 插件
     * 请求体：{mcpId, envValues}
     * userId 从 UserContext（Token 拦截器解析）获取
     *
     * @param request 请求体，包含 mcpId 和 envValues
     * @return 安装结果
     */
    @PostMapping("/install")
    public Result<?> install(@RequestBody Map<String, Object> request) {
        Long userId = UserContext.getUserId();
        String mcpId = (String) request.get("mcpId");
        @SuppressWarnings("unchecked")
        Map<String, String> envValues = (Map<String, String>) request.get("envValues");
        logger.info("收到 MCP 安装请求: userId={}, mcpId={}", userId, mcpId);
        if (mcpId == null || mcpId.isEmpty()) {
            return Result.error("mcpId 不能为空");
        }
        return mcpInstallService.install(userId, mcpId, envValues);
    }

    /**
     * 卸载 MCP 插件
     *
     * @param mcpId MCP 插件标识
     * @return 卸载结果
     */
    @DeleteMapping("/{mcpId}")
    public Result<?> uninstall(@PathVariable("mcpId") String mcpId) {
        Long userId = UserContext.getUserId();
        logger.info("收到 MCP 卸载请求: userId={}, mcpId={}", userId, mcpId);
        return mcpInstallService.uninstall(userId, mcpId);
    }

    /**
     * 更新 MCP 插件环境变量（如 Token）
     * 请求体：{envValues}
     *
     * @param mcpId   MCP 插件标识
     * @param request 请求体，包含 envValues
     * @return 更新结果
     */
    @PutMapping("/{mcpId}/env")
    public Result<?> updateEnv(@PathVariable("mcpId") String mcpId, @RequestBody Map<String, Object> request) {
        Long userId = UserContext.getUserId();
        @SuppressWarnings("unchecked")
        Map<String, String> envValues = (Map<String, String>) request.get("envValues");
        logger.info("收到 MCP 环境变量更新请求: userId={}, mcpId={}", userId, mcpId);
        return mcpInstallService.updateEnv(userId, mcpId, envValues);
    }

    /**
     * 启用 MCP 插件
     *
     * @param mcpId MCP 插件标识
     * @return 启用结果
     */
    @PutMapping("/{mcpId}/enable")
    public Result<?> enable(@PathVariable("mcpId") String mcpId) {
        Long userId = UserContext.getUserId();
        logger.info("收到 MCP 启用请求: userId={}, mcpId={}", userId, mcpId);
        return mcpInstallService.enable(userId, mcpId);
    }

    /**
     * 禁用 MCP 插件
     *
     * @param mcpId MCP 插件标识
     * @return 禁用结果
     */
    @PutMapping("/{mcpId}/disable")
    public Result<?> disable(@PathVariable("mcpId") String mcpId) {
        Long userId = UserContext.getUserId();
        logger.info("收到 MCP 禁用请求: userId={}, mcpId={}", userId, mcpId);
        return mcpInstallService.disable(userId, mcpId);
    }

    /**
     * 获取当前用户已安装的 MCP 插件列表
     *
     * @return 已安装列表
     */
    @GetMapping("/installed")
    public Result<?> getInstalled() {
        Long userId = UserContext.getUserId();
        logger.info("查询已安装 MCP 列表: userId={}", userId);
        return mcpInstallService.getInstalledList(userId);
    }

    /**
     * 内部接口：Agent 查询用户已安装 MCP 列表（用 X-Internal-Secret 认证，不走 Token）
     * 供 Agent 懒加载时调用：用户首次发消息时 Agent 从这里拿安装记录
     *
     * @param userId 用户ID（query 参数）
     * @return 已安装列表
     */
    @GetMapping("/internal/installed")
    public Result<?> internalGetInstalled(@RequestParam("userId") Long userId,
                                          @RequestHeader("X-Internal-Secret") String secret) {
        logger.info("[内部接口] Agent 查询用户已安装 MCP: userId={}", userId);
        return mcpInstallService.getInstalledList(userId);
    }
}
