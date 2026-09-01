# -*- coding: utf-8 -*-
"""
MCP 插件数据模型。
定义市场元数据、传输配置、工具描述、连接池条目等数据结构。
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any


@dataclass
class EnvField:
    """环境变量模板（用户安装时需要填写的配置项）"""
    key: str           # 环境变量名，如 TUSHARE_TOKEN
    label: str         # 前端显示标签
    required: bool = True
    type: str = "text"  # text | password
    help: str = ""      # 帮助文字


@dataclass
class Transport:
    """MCP 传输配置"""
    type: str          # builtin_sdk | stdio | sse | http
    command: str = ""        # stdio 专用：启动命令
    args: List[str] = field(default_factory=list)  # stdio 专用：命令参数
    url: str = ""            # sse/http 专用：远程地址
    package: str = ""        # builtin_sdk 专用：Python 包名
    env_template: List[EnvField] = field(default_factory=list)

    def build_headers(self, env_values: Dict[str, str]) -> Dict[str, str]:
        """根据模板和用户填的值，构造 HTTP 请求头（SSE 类型用）"""
        headers = {}
        for f in self.env_template:
            val = env_values.get(f.key, "")
            if val:
                headers[f.key] = f"Bearer {val}" if f.key.lower().endswith("token") else val
        return headers


@dataclass
class ToolMeta:
    """MCP 工具元数据（市场元数据里声明）"""
    name: str                  # 工具原名（如 stock_summary）
    description: str           # 工具描述
    params_template: str = ""  # 参数模板字符串


@dataclass
class McpMeta:
    """MCP 插件完整元数据（市场注册表里一条记录）"""
    mcp_id: str                # 唯一标识，如 tushare
    name: str                  # 显示名
    version: str = "1.0.0"
    author: str = ""
    category: str = ""         # 分类，如 finance / development
    description: str = ""
    icon: str = "📦"
    homepage: str = ""
    risk_level: str = "low"   # low | medium | high
    transport: Optional[Transport] = None
    tools: List[ToolMeta] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "McpMeta":
        """从 JSON 字典构造 McpMeta"""
        transport_data = data.get("transport", {})
        env_list = [
            EnvField(
                key=f["key"],
                label=f["label"],
                required=f.get("required", True),
                type=f.get("type", "text"),
                help=f.get("help", "")
            )
            for f in transport_data.get("env_template", [])
        ]
        transport = Transport(
            type=transport_data.get("type", "stdio"),
            command=transport_data.get("command", ""),
            args=transport_data.get("args", []),
            url=transport_data.get("url", ""),
            package=transport_data.get("package", ""),
            env_template=env_list
        )
        tools = [
            ToolMeta(
                name=t["name"],
                description=t["description"],
                params_template=t.get("params_template", "")
            )
            for t in data.get("tools", [])
        ]
        return cls(
            mcp_id=data["mcp_id"],
            name=data.get("name", data["mcp_id"]),
            version=data.get("version", "1.0.0"),
            author=data.get("author", ""),
            category=data.get("category", ""),
            description=data.get("description", ""),
            icon=data.get("icon", "📦"),
            homepage=data.get("homepage", ""),
            risk_level=data.get("risk_level", "low"),
            transport=transport,
            tools=tools
        )


@dataclass
class ToolDesc:
    """动态工具描述（注入编排器 system prompt 用）"""
    tool_name: str       # 带命名空间的工具名，如 tushare__stock_summary
    description: str
    params_template: str = ""
    mcp_id: str = ""     # 所属 MCP 的 mcp_id
    original_name: str = ""  # 工具原名（如 stock_summary）


@dataclass
class SessionEntry:
    """连接池条目（一个 MCP 子进程/SDK 实例的运行时状态）"""
    session: Any = None             # MCP ClientSession 或 SDK 客户端实例
    ref_count: int = 0               # 引用计数（多少用户在用）
    user_ids: set = field(default_factory=set)  # 哪些用户在用
    mcp_meta: Optional[McpMeta] = None  # 市场元数据
    env_values: Dict[str, str] = field(default_factory=dict)  # 当前 Token 配置
    last_used: float = 0.0         # 最后调用时间（LRU 淘汰用）
    started: bool = False           # 是否已初始化
