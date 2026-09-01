-- MCP 插件安装记录表
-- 用途：持久化用户安装的 MCP 插件配置（Token 加密存储）
CREATE TABLE IF NOT EXISTS mcp_install_record (
  id            BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '主键ID',
  user_id       BIGINT       NOT NULL COMMENT '用户ID',
  mcp_id        VARCHAR(128) NOT NULL COMMENT 'MCP插件标识',
  mcp_version   VARCHAR(32)  NOT NULL DEFAULT '1.0.0' COMMENT '安装时的MCP版本',
  fingerprint   VARCHAR(16)  NOT NULL COMMENT '配置指纹（SHA256前16位，用于连接复用）',
  env_values    TEXT         DEFAULT NULL COMMENT 'AES加密的环境变量（Token等）',
  enabled       TINYINT(1)   DEFAULT 1 COMMENT '0=禁用 1=启用',
  installed_at  DATETIME     DEFAULT CURRENT_TIMESTAMP COMMENT '安装时间',
  updated_at    DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  UNIQUE KEY uk_user_mcp (user_id, mcp_id) COMMENT '用户+插件唯一索引',
  INDEX idx_fingerprint (fingerprint) COMMENT '配置指纹索引（连接复用查询用）'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='MCP插件安装记录';
