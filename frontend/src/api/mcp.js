// ============================================================
// MCP 插件市场 API 封装
// 统一基于 ./index 的 axios 实例（自带 baseURL=/api + Token 拦截器）
// 所有方法返回 Promise（response.data 已被响应拦截器解包）
// ============================================================
import service from './index'

/**
 * 获取市场列表
 * @param {string} category - 分类筛选（可空）
 * @param {string} keyword  - 关键词搜索（可空）
 */
export function getMarketList(category, keyword) {
  return service.get('/mcp/market', { params: { category, keyword } })
}

/**
 * 获取单个 MCP 详情
 * @param {string} mcpId - 插件唯一标识
 */
export function getMcpDetail(mcpId) {
  return service.get(`/mcp/market/${mcpId}`)
}

/**
 * 安装 MCP（带环境变量配置）
 * @param {string} mcpId
 * @param {Object} envValues - { KEY: VALUE } 由 env_template 渲染出的表单值
 */
export function installMcp(mcpId, envValues) {
  return service.post('/mcp/install', { mcpId, envValues })
}

/**
 * 卸载 MCP
 * @param {string} mcpId
 */
export function uninstallMcp(mcpId) {
  return service.delete(`/mcp/${mcpId}`)
}

/**
 * 更新已安装 MCP 的环境变量
 * @param {string} mcpId
 * @param {Object} envValues
 */
export function updateMcpEnv(mcpId, envValues) {
  return service.put(`/mcp/${mcpId}/env`, { envValues })
}

/**
 * 启用 MCP
 * @param {string} mcpId
 */
export function enableMcp(mcpId) {
  return service.put(`/mcp/${mcpId}/enable`)
}

/**
 * 禁用 MCP
 * @param {string} mcpId
 */
export function disableMcp(mcpId) {
  return service.put(`/mcp/${mcpId}/disable`)
}

/**
 * 获取当前用户已安装的 MCP 列表
 */
export function getInstalledList() {
  return service.get('/mcp/installed')
}
