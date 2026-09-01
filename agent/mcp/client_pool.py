# -*- coding: utf-8 -*-
"""
MCP 连接池（核心模块）。
按配置指纹复用，懒加载，LRU 淘汰。
Phase 1：TuShare 走 builtin_sdk 直连（不走子进程协议）。
"""
import os
import json
import time
import hashlib
import asyncio
import logging
from typing import Dict, List, Optional, Tuple, Any

import httpx

from mcp.models import McpMeta, Transport, ToolDesc, SessionEntry
from mcp.registry import mcp_registry
from mcp import crypto

logger = logging.getLogger(__name__)

# ===== 常量 =====
MAX_PROCESSES = 50           # 全局最多 50 个 SDK 实例/子进程
IDLE_TIMEOUT_S = 600         # 10 分钟无调用自动关闭
CALL_TIMEOUT_S = 30           # 单次调用超时

# 后端服务地址（通过后端 HTTP API 查询安装记录，不走 MySQL 直连）
_BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8080").rstrip("/")
_INTERNAL_SECRET = os.getenv("INTERNAL_SECRET", "")


def config_fingerprint(mcp_meta: McpMeta, env_values: Dict[str, str]) -> str:
    """根据 MCP 配置生成指纹。
    相同指纹 = 可以复用同一个 SDK 实例/子进程。

    入参：
      mcp_meta   市场元数据（command/args/transport）
      env_values 用户填的 Token 等环境变量
    返回：
      16 位 hex 字符串
    """
    transport = mcp_meta.transport
    raw = {
        "mcp_id": mcp_meta.mcp_id,
        "type": transport.type if transport else "unknown",
        "command": transport.command if transport else "",
        "args": transport.args if transport else [],
        "url": transport.url if transport else "",
        "package": transport.package if transport else "",
        "env": {
            k: str(env_values.get(k, "") or "")
            for k in sorted(env_values.keys())
        }
    }
    return hashlib.sha256(
        json.dumps(raw, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:16]


async def _query_install_records(user_id: int) -> List[dict]:
    """通过后端 HTTP API 查询用户已安装且启用的 MCP 列表（用内部密钥认证，非用户 Token）"""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{_BACKEND_URL}/api/mcp/internal/installed",
                headers={"X-Internal-Secret": _INTERNAL_SECRET},
                # 后端 @RequestParam("userId") 期望驼峰参数名，传下划线会 400
                params={"userId": str(user_id)}
            )
            if resp.status_code == 200:
                return resp.json().get("data", [])
            logger.warning(f"[MCP][查询] 后端返回 {resp.status_code}")
            return []
    except Exception as e:
        logger.error(f"[MCP][查询] 查询安装记录失败: {e}")
        return []


async def _query_install_record(user_id: int, mcp_id: str) -> Optional[dict]:
    """通过后端 HTTP API 查询单条安装记录"""
    records = await _query_install_records(user_id)
    for r in records:
        # 后端 McpInstallRecord 实体序列化为驼峰字段名（mcpId/...）
        if (r.get("mcpId") or r.get("mcp_id")) == mcp_id:
            return r
    return None


class McpClientPool:
    """按配置指纹复用的 MCP 连接池。

    设计要点：
    1. 不按 user_id 隔离，按配置指纹复用（相同 Token 共用一个实例）
    2. 懒加载：阶段A 加载安装记录不启动实例，阶段B 调工具时才启动
    3. LRU 淘汰：空闲 10 分钟的实例自动关闭
    4. 改 Token 时平滑切换：先起新实例，再删旧的
    """

    def __init__(self):
        self._sessions: Dict[str, SessionEntry] = {}  # 指纹 → 会话条目
        self._user_map: Dict[Tuple[int, str], str] = {}  # (user_id, mcp_id) → 指纹
        self._loaded_users: set = set()  # 已从 MySQL 加载过安装记录的用户

    async def load_user_installed(self, user_id: int):
        """阶段A：从 MySQL 加载用户安装记录到堆内存（不启动实例）

        触发时机：用户发消息时，编排器启动前
        作用：知道用户装了哪些 MCP，拿工具列表注入 prompt
        """
        if user_id in self._loaded_users:
            return  # 已加载过，跳过

        try:
            records = await _query_install_records(user_id)
            for record in records:
                # 后端 McpInstallRecord 实体序列化为驼峰字段名（mcpId/userId/...）
                mcp_id = record.get("mcpId") or record.get("mcp_id")
                fingerprint = record.get("fingerprint", "")
                if mcp_id and fingerprint:
                    self._user_map[(user_id, mcp_id)] = fingerprint
            self._loaded_users.add(user_id)
            logger.info(f"[MCP][懒加载] 用户 {user_id} 已安装 {len(records)} 个 MCP 插件")
        except Exception as e:
            logger.error(f"[MCP][懒加载] 加载用户 {user_id} 安装记录失败: {e}")
            self._loaded_users.add(user_id)  # 标记已加载避免重复查询

    def get_user_tools(self, user_id: int) -> List[ToolDesc]:
        """获取用户已装 MCP 的工具列表（从市场元数据拿，不启动实例）"""
        tools: List[ToolDesc] = []
        for (uid, mcp_id), _fp in self._user_map.items():
            if uid != user_id:
                continue
            meta = mcp_registry.get(mcp_id)
            if not meta or not meta.tools:
                continue
            for t in meta.tools:
                tools.append(ToolDesc(
                    tool_name=f"{mcp_id}__{t.name}",
                    description=t.description,
                    params_template=t.params_template,
                    mcp_id=mcp_id,
                    original_name=t.name
                ))
        return tools

    async def call_tool(self, user_id: int, tool_name: str, args: dict) -> dict:
        """阶段B：调用工具（首次调用时才启动实例）

        触发时机：编排器决定调某工具时
        返回：{"summary": str, "data": list, "context_text": str, "duration_ms": int}
        """
        # 解析命名空间
        if "__" not in tool_name:
            return {"summary": "工具名格式错误", "data": [], "context_text": "", "duration_ms": 0}

        mcp_id, original_name = tool_name.split("__", 1)
        fp = self._user_map.get((user_id, mcp_id))
        if not fp:
            return {"summary": f"用户未安装 {mcp_id}", "data": [], "context_text": "", "duration_ms": 0}

        # 懒启动：实例还没启动
        if fp not in self._sessions or not self._sessions[fp].started:
            await self._start_instance(fp, user_id, mcp_id)

        entry = self._sessions[fp]
        entry.last_used = time.time()
        entry.user_ids.add(user_id)

        # 调用工具（超时控制）
        try:
            result = await asyncio.wait_for(
                self._invoke_tool(entry, original_name, args),
                timeout=CALL_TIMEOUT_S
            )
            return result
        except asyncio.TimeoutError:
            logger.error(f"[MCP][调用] 工具 {tool_name} 超时（{CALL_TIMEOUT_S}s）")
            return {"summary": "调用超时", "data": [], "context_text": "", "duration_ms": CALL_TIMEOUT_S * 1000}
        except Exception as e:
            logger.error(f"[MCP][调用] 工具 {tool_name} 失败: {e}")
            return {"summary": f"调用失败: {e}", "data": [], "context_text": "", "duration_ms": 0}

    async def _start_instance(self, fingerprint: str, user_id: int, mcp_id: str):
        """启动 MCP 实例（首次调用时触发）"""
        meta = mcp_registry.get(mcp_id)
        if not meta:
            logger.error(f"[MCP][启动] 市场中不存在 mcp_id={mcp_id}")
            return

        # 从 MySQL 拿 env_values
        record = await _query_install_record(user_id, mcp_id)
        if not record:
            logger.error(f"[MCP][启动] 用户 {user_id} 未安装 {mcp_id}")
            return

        # 后端实体字段名 envValues（驼峰），兼容下划线
        env_encrypted = record.get("envValues") or record.get("env_values") or ""
        env_json = crypto.decrypt(env_encrypted) if env_encrypted else "{}"
        try:
            env_values = json.loads(env_json)
        except json.JSONDecodeError:
            env_values = {}

        # 指纹已存在且已启动 → 复用
        if fingerprint in self._sessions and self._sessions[fingerprint].started:
            return

        # 全局实例数上限
        if len(self._sessions) >= MAX_PROCESSES:
            await self._evict_idle()

        # 根据 transport 类型启动
        transport_type = meta.transport.type if meta.transport else "stdio"
        if transport_type == "builtin_sdk":
            # Phase 1：直接用 Python SDK（不走子进程）
            session = await self._init_builtin_sdk(meta, env_values)
        elif transport_type == "stdio":
            # Phase 2：启动子进程 + MCP 握手
            session = await self._init_stdio(meta, env_values)
        elif transport_type in ("sse", "http"):
            session = await self._init_sse(meta, env_values)
        else:
            logger.error(f"[MCP][启动] 不支持的 transport 类型: {transport_type}")
            return

        self._sessions[fingerprint] = SessionEntry(
            session=session,
            ref_count=1,
            user_ids={user_id},
            mcp_meta=meta,
            env_values=env_values,
            last_used=time.time(),
            started=True
        )
        logger.info(f"[MCP][启动] 实例已启动: {mcp_id}, 指纹={fingerprint}, 类型={transport_type}")

    async def _init_builtin_sdk(self, meta: McpMeta, env_values: Dict[str, str]) -> Any:
        """初始化内置 SDK 客户端（TuShare / AKShare 直连）"""
        if meta.mcp_id == "tushare":
            try:
                import tushare as ts
                token = env_values.get("TUSHARE_TOKEN", "")
                if token:
                    ts.set_token(token)
                pro = ts.pro_api()
                logger.info("[MCP][TuShare] SDK 初始化完成")
                return {"type": "tushare", "client": pro, "token": token}
            except ImportError:
                logger.error("[MCP][TuShare] tushare 库未安装，请 pip install tushare")
                return {"type": "tushare", "client": None, "token": ""}
            except Exception as e:
                logger.error(f"[MCP][TuShare] SDK 初始化失败: {e}")
                return {"type": "tushare", "client": None, "token": ""}
        elif meta.mcp_id == "akshare":
            # AKShare 完全免费，无需 Token，直接 import 即可
            try:
                import akshare as ak
                logger.info("[MCP][AKShare] SDK 初始化完成（免费无需 Token）")
                return {"type": "akshare", "client": ak}
            except ImportError:
                logger.error("[MCP][AKShare] akshare 库未安装，请 pip install akshare")
                return {"type": "akshare", "client": None}
            except Exception as e:
                logger.error(f"[MCP][AKShare] SDK 初始化失败: {e}")
                return {"type": "akshare", "client": None}
        return None

    async def _init_stdio(self, meta: McpMeta, env_values: Dict[str, str]) -> Any:
        """启动 stdio 子进程 + MCP 握手（Phase 2）"""
        # Phase 2 实现：用 mcp Python SDK
        logger.warning("[MCP][stdio] Phase 2 功能，暂未实现")
        return None

    async def _init_sse(self, meta: McpMeta, env_values: Dict[str, str]) -> Any:
        """建立 SSE 连接（Phase 2）"""
        logger.warning("[MCP][SSE] Phase 2 功能，暂未实现")
        return None

    async def _invoke_tool(self, entry: SessionEntry, tool_name: str, args: dict) -> dict:
        """调用工具的具体实现（根据 MCP 类型路由）"""
        session = entry.session
        if not session:
            return {"summary": "SDK 未初始化", "data": [], "context_text": "", "duration_ms": 0}

        if session.get("type") == "tushare":
            return await self._invoke_tushare(session["client"], tool_name, args)
        if session.get("type") == "akshare":
            return await self._invoke_akshare(session["client"], tool_name, args)
        return {"summary": "不支持的 MCP 类型", "data": [], "context_text": "", "duration_ms": 0}

    async def _invoke_tushare(self, pro_api, tool_name: str, args: dict) -> dict:
        """调用 TuShare 工具（股票 + 基金）"""
        start = time.time()
        try:
            if tool_name == "stock_summary":
                return await self._tushare_stock_summary(pro_api, args)
            elif tool_name == "stock_daily":
                return await self._tushare_stock_daily(pro_api, args)
            elif tool_name == "stock_financial":
                return await self._tushare_stock_financial(pro_api, args)
            elif tool_name == "fund_summary":
                return await self._tushare_fund_summary(pro_api, args)
            elif tool_name == "fund_daily":
                return await self._tushare_fund_daily(pro_api, args)
            else:
                return {"summary": f"未知工具: {tool_name}", "data": [], "context_text": "", "duration_ms": 0}
        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            logger.error(f"[MCP][TuShare] 工具 {tool_name} 调用失败: {e}")
            return {"summary": f"调用失败: {e}", "data": [], "context_text": "", "duration_ms": duration_ms}

    async def _invoke_akshare(self, ak, tool_name: str, args: dict) -> dict:
        """调用 AKShare 工具（股票 + 基金，完全免费无需 Token）"""
        start = time.time()
        try:
            if tool_name == "stock_summary":
                return await self._akshare_stock_summary(ak, args)
            elif tool_name == "stock_daily":
                return await self._akshare_stock_daily(ak, args)
            elif tool_name == "fund_summary":
                return await self._akshare_fund_summary(ak, args)
            elif tool_name == "fund_daily":
                return await self._akshare_fund_daily(ak, args)
            else:
                return {"summary": f"未知工具: {tool_name}", "data": [], "context_text": "", "duration_ms": 0}
        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            logger.error(f"[MCP][AKShare] 工具 {tool_name} 调用失败: {e}")
            return {"summary": f"调用失败: {e}", "data": [], "context_text": "", "duration_ms": duration_ms}

    async def _akshare_stock_summary(self, ak, args: dict) -> dict:
        """AKShare：A股股票综合快照（个股信息 + 行业 + 市值，失败兜底日线接口）"""
        start = time.time()
        symbol = str(args.get("symbol", ""))
        if not symbol:
            return {"summary": "symbol 不能为空", "data": [], "context_text": "", "duration_ms": 0}

        # stock_individual_info_em 偶尔被东方财富限流，重试 1 次后兜底日线接口
        info_dict = {}
        for attempt in range(2):
            try:
                df = await asyncio.to_thread(ak.stock_individual_info_em, symbol=symbol)
                if len(df) > 0:
                    for _, row in df.iterrows():
                        info_dict[str(row["item"])] = row["value"]
                break
            except Exception as e:
                if attempt == 0:
                    logger.warning(f"[MCP][AKShare] stock_individual_info_em 第 1 次失败，1s 后重试: {e}")
                    await asyncio.sleep(1)
                else:
                    logger.warning(f"[MCP][AKShare] stock_individual_info_em 重试仍失败，兜底用日线接口: {e}")

        result = {
            "code": symbol,
            "name": info_dict.get("股票简称", ""),
            "industry": info_dict.get("行业", ""),
            "total_market_cap": info_dict.get("总市值", ""),
            "circulating_market_cap": info_dict.get("流通市值", ""),
            "listing_date": info_dict.get("上市时间", ""),
        }

        # 个股信息接口失败时，兜底用新浪日线接口拿最近行情（新浪跟东方财富是不同的数据源）
        if not result["name"]:
            try:
                sina_symbol = self._symbol_to_sina(symbol)
                df = await asyncio.to_thread(ak.stock_zh_a_daily, symbol=sina_symbol, adjust="qfq")
                if len(df) > 0:
                    latest = self._safe_records(df)[-1]
                    result["name"] = symbol
                    result["latest_close"] = str(latest.get("close", ""))
                    result["latest_date"] = str(latest.get("date", ""))
                    logger.info(f"[MCP][AKShare] 兜底新浪日线接口成功: {symbol} 最新收盘={result['latest_close']}")
            except Exception as e:
                logger.warning(f"[MCP][AKShare] 兜底新浪日线接口也失败: {e}")

        duration_ms = int((time.time() - start) * 1000)
        context = self._build_stock_summary_text(result)
        return {"summary": f"已查询 {symbol} 股票快照", "data": [result], "context_text": context, "duration_ms": duration_ms}

    async def _akshare_stock_daily(self, ak, args: dict) -> dict:
        """AKShare：A股股票日线行情历史（新浪数据源，前复权）"""
        start = time.time()
        symbol = str(args.get("symbol", ""))
        start_date = str(args.get("start_date", ""))
        end_date = str(args.get("end_date", ""))
        if not symbol:
            return {"summary": "symbol 不能为空", "data": [], "context_text": "", "duration_ms": 0}

        # stock_zh_a_daily（新浪数据源）返回全量历史，列名英文：date/open/high/low/close/volume 等
        sina_symbol = self._symbol_to_sina(symbol)
        df = await asyncio.to_thread(ak.stock_zh_a_daily, symbol=sina_symbol, adjust="qfq")
        records = self._safe_records(df)
        # 按日期过滤（新浪返回全量历史，前端传了日期就过滤）
        # 统一去掉横线比较，避免 "2026-08-31" vs "20250101" 格式不一致导致过滤错误
        if start_date:
            sd = start_date.replace("-", "")
            records = [r for r in records if str(r.get("date", "")).replace("-", "") >= sd]
        if end_date:
            ed = end_date.replace("-", "")
            records = [r for r in records if str(r.get("date", "")).replace("-", "") <= ed]
        duration_ms = int((time.time() - start) * 1000)
        # 拼上下文：总数 + 最近 20 条（供模型分析趋势，跟 data 字段一致）
        context = f"【股票日线 {symbol}】共 {len(records)} 条数据，以下为最近 20 条：\n"
        for r in records[-20:]:
            context += f"  {r.get('date', '')} 开{r.get('open', '')} 高{r.get('high', '')} 低{r.get('low', '')} 收{r.get('close', '')} 量{r.get('volume', '')}\n"
        return {"summary": f"已查询 {symbol} 日线 {len(records)} 条", "data": records[-20:], "context_text": context, "duration_ms": duration_ms}

    async def _akshare_fund_summary(self, ak, args: dict) -> dict:
        """AKShare：公募基金综合快照（雪球数据源，无需积分）"""
        start = time.time()
        symbol = str(args.get("symbol", ""))
        if not symbol:
            return {"summary": "symbol 不能为空", "data": [], "context_text": "", "duration_ms": 0}

        # fund_individual_basic_info_xq 返回 DataFrame（item/value 两列）
        df = await asyncio.to_thread(ak.fund_individual_basic_info_xq, symbol=symbol)
        info_dict = {}
        if len(df) > 0:
            for _, row in df.iterrows():
                info_dict[str(row["item"])] = row["value"]

        result = {
            "code": symbol,
            "name": info_dict.get("基金简称", info_dict.get("基金名称", "")),
            "fund_type": info_dict.get("基金类型", ""),
            "management": info_dict.get("管理人", info_dict.get("基金管理人", "")),
            "found_date": info_dict.get("成立时间", info_dict.get("成立日期", "")),
            "latest_nav": info_dict.get("最新净值", ""),
            "accum_nav": info_dict.get("累计净值", ""),
        }
        duration_ms = int((time.time() - start) * 1000)
        context = self._build_fund_summary_text(result)
        return {"summary": f"已查询 {symbol} 基金快照", "data": [result], "context_text": context, "duration_ms": duration_ms}

    async def _akshare_fund_daily(self, ak, args: dict) -> dict:
        """AKShare：公募基金净值历史（东方财富数据源，无需积分）"""
        start = time.time()
        symbol = str(args.get("symbol", ""))
        start_date = str(args.get("start_date", ""))
        end_date = str(args.get("end_date", ""))
        if not symbol:
            return {"summary": "symbol 不能为空", "data": [], "context_text": "", "duration_ms": 0}

        # fund_open_fund_info_em 返回 DataFrame（净值日期/单位净值/累计净值/日增长率）
        df = await asyncio.to_thread(
            ak.fund_open_fund_info_em, symbol=symbol, indicator="单位净值走势"
        )
        records = self._safe_records(df)
        # 按日期过滤（AKShare 返回全量历史，前端传了日期就过滤）
        # 统一去掉横线比较，避免 "2026-08-31" vs "20250101" 格式不一致导致过滤错误
        if start_date:
            sd = start_date.replace("-", "")
            records = [r for r in records if str(r.get("净值日期", "")).replace("-", "") >= sd]
        if end_date:
            ed = end_date.replace("-", "")
            records = [r for r in records if str(r.get("净值日期", "")).replace("-", "") <= ed]
        duration_ms = int((time.time() - start) * 1000)
        # 拼上下文：总数 + 最近 20 条（供模型分析趋势，跟 data 字段一致）
        context = f"【基金净值 {symbol}】共 {len(records)} 条数据，以下为最近 20 条：\n"
        for r in records[-20:]:
            context += f"  {r.get('净值日期', '')} 单位净值{r.get('单位净值', '')} 累计净值{r.get('累计净值', '')}\n"
        return {"summary": f"已查询 {symbol} 基金净值 {len(records)} 条", "data": records[-20:], "context_text": context, "duration_ms": duration_ms}

    @staticmethod
    def _safe_records(df) -> list:
        """DataFrame 转 records，date/datetime 转字符串避免 JSON 序列化报错"""
        import datetime
        records = df.to_dict("records") if len(df) > 0 else []
        for r in records:
            for k, v in r.items():
                if isinstance(v, (datetime.date, datetime.datetime)):
                    r[k] = v.strftime("%Y-%m-%d")
        return records

    @staticmethod
    def _symbol_to_sina(symbol: str) -> str:
        """纯数字代码转新浪格式（sh/sz/bj 前缀），新浪/腾讯接口需要"""
        if not symbol or len(symbol) != 6 or not symbol.isdigit():
            return symbol
        if symbol.startswith(("6", "9")):
            return "sh" + symbol
        elif symbol.startswith(("0", "3")):
            return "sz" + symbol
        elif symbol.startswith(("8", "4")):
            return "bj" + symbol
        return symbol

    async def _tushare_stock_summary(self, pro_api, args: dict) -> dict:
        """TuShare：A股综合快照"""
        start = time.time()
        ts_code = args.get("ts_code", "")
        if not ts_code:
            return {"summary": "ts_code 不能为空", "data": [], "context_text": "", "duration_ms": 0}

        # 并行查 3 个指标
        daily = await asyncio.to_thread(pro_api.daily, ts_code=ts_code)
        daily_basic = await asyncio.to_thread(pro_api.daily_basic, ts_code=ts_code)
        stock_basic = await asyncio.to_thread(pro_api.stock_basic, ts_code=ts_code)

        # 组装结果
        result = {
            "code": ts_code,
            "name": stock_basic.iloc[0].get("name", "") if len(stock_basic) > 0 else "",
            "industry": stock_basic.iloc[0].get("industry", "") if len(stock_basic) > 0 else "",
            "latest_price": daily.iloc[0].to_dict() if len(daily) > 0 else {},
            "valuation": daily_basic.iloc[0].to_dict() if len(daily_basic) > 0 else {},
        }
        duration_ms = int((time.time() - start) * 1000)
        context = self._build_stock_summary_text(result)
        return {"summary": f"已查询 {ts_code} 综合快照", "data": [result], "context_text": context, "duration_ms": duration_ms}

    async def _tushare_stock_daily(self, pro_api, args: dict) -> dict:
        """TuShare：A股日线行情"""
        start = time.time()
        ts_code = args.get("ts_code", "")
        start_date = args.get("start_date", "")
        end_date = args.get("end_date", "")
        if not ts_code:
            return {"summary": "ts_code 不能为空", "data": [], "context_text": "", "duration_ms": 0}

        df = await asyncio.to_thread(
            pro_api.daily, ts_code=ts_code,
            start_date=start_date, end_date=end_date
        )
        records = self._safe_records(df)
        duration_ms = int((time.time() - start) * 1000)
        context = f"【日线行情 {ts_code}】共 {len(records)} 条\n"
        for r in records[:5]:
            context += f"  {r.get('trade_date', '')} 开{r.get('open', '')} 收{r.get('close', '')} 涨跌幅{r.get('pct_chg', '')}%\n"
        return {"summary": f"已查询 {ts_code} 日线行情 {len(records)} 条", "data": records[:20], "context_text": context, "duration_ms": duration_ms}

    async def _tushare_stock_financial(self, pro_api, args: dict) -> dict:
        """TuShare：三表财报关键指标"""
        start = time.time()
        ts_code = args.get("ts_code", "")
        periods = args.get("periods", 4)
        if not ts_code:
            return {"summary": "ts_code 不能为空", "data": [], "context_text": "", "duration_ms": 0}

        # 查财务指标
        df = await asyncio.to_thread(pro_api.fina_indicator, ts_code=ts_code)
        records = df.to_dict("records")[:periods] if len(df) > 0 else []
        duration_ms = int((time.time() - start) * 1000)
        context = f"【财务指标 {ts_code}】共 {len(records)} 期\n"
        for r in records:
            context += f"  {r.get('end_date', '')} 营收{r.get('q_profit', '')} ROE{r.get('roe', '')}%\n"
        return {"summary": f"已查询 {ts_code} 财务指标 {len(records)} 期", "data": records, "context_text": context, "duration_ms": duration_ms}

    async def _tushare_fund_summary(self, pro_api, args: dict) -> dict:
        """TuShare：公募基金综合快照（基金基础信息 + 最新净值）"""
        start = time.time()
        ts_code = args.get("ts_code", "")
        if not ts_code:
            return {"summary": "ts_code 不能为空", "data": [], "context_text": "", "duration_ms": 0}

        # 并行查基金基础信息 + 净值历史（最近一条即最新净值）
        fund_basic = await asyncio.to_thread(pro_api.fund_basic, ts_code=ts_code)
        fund_nav = await asyncio.to_thread(pro_api.fund_nav, ts_code=ts_code)

        # 组装结果（fund_basic / fund_nav 返回 DataFrame）
        basic_row = fund_basic.iloc[0].to_dict() if len(fund_basic) > 0 else {}
        nav_row = fund_nav.iloc[0].to_dict() if len(fund_nav) > 0 else {}
        result = {
            "code": ts_code,
            "name": basic_row.get("name", ""),
            "management": basic_row.get("management", ""),       # 基金管理人
            "custodian": basic_row.get("custodian", ""),          # 托管人
            "fund_type": basic_row.get("fund_type", ""),         # 基金类型
            "invest_type": basic_row.get("invest_type", ""),     # 投资风格
            "found_date": basic_row.get("found_date", ""),       # 成立日期
            "due_date": basic_row.get("due_date", ""),            # 到期日期
            "latest_nav": nav_row,                                 # 最新净值（单位/累计/日期）
        }
        duration_ms = int((time.time() - start) * 1000)
        context = self._build_fund_summary_text(result)
        return {"summary": f"已查询 {ts_code} 基金快照", "data": [result], "context_text": context, "duration_ms": duration_ms}

    async def _tushare_fund_daily(self, pro_api, args: dict) -> dict:
        """TuShare：公募基金日线净值历史（单位净值 + 累计净值）"""
        start = time.time()
        ts_code = args.get("ts_code", "")
        start_date = args.get("start_date", "")
        end_date = args.get("end_date", "")
        if not ts_code:
            return {"summary": "ts_code 不能为空", "data": [], "context_text": "", "duration_ms": 0}

        # fund_nav 支持按日期区间查净值历史
        df = await asyncio.to_thread(
            pro_api.fund_nav, ts_code=ts_code,
            start_date=start_date, end_date=end_date
        )
        records = self._safe_records(df)
        duration_ms = int((time.time() - start) * 1000)
        # 拼上下文：最近 5 条净值记录
        context = f"【基金净值 {ts_code}】共 {len(records)} 条\n"
        for r in records[:5]:
            context += f"  {r.get('nav_date', '')} 单位净值{r.get('unit_nav', '')} 累计净值{r.get('accum_nav', '')}\n"
        return {"summary": f"已查询 {ts_code} 基金净值 {len(records)} 条", "data": records[:20], "context_text": context, "duration_ms": duration_ms}

    @staticmethod
    def _build_fund_summary_text(result: dict) -> str:
        """将基金快照结果拼接为编排器上下文文本"""
        lines = [f"【基金快照】{result.get('code', '')} {result.get('name', '')}"]
        if result.get("fund_type"):
            lines.append(f"  类型: {result['fund_type']}")
        if result.get("management"):
            lines.append(f"  管理人: {result['management']}")
        if result.get("found_date"):
            lines.append(f"  成立日: {result['found_date']}")
        nav = result.get("latest_nav", {})
        if nav:
            lines.append(f"  最新净值日: {nav.get('nav_date', 'N/A')} 单位净值: {nav.get('unit_nav', 'N/A')} 累计净值: {nav.get('accum_nav', 'N/A')}")
        return "\n".join(lines)

    @staticmethod
    def _build_stock_summary_text(result: dict) -> str:
        """将股票快照结果拼接为编排器上下文文本"""
        lines = [f"【股票快照】{result.get('code', '')} {result.get('name', '')}"]
        if result.get("industry"):
            lines.append(f"  行业: {result['industry']}")
        latest = result.get("latest_price", {})
        if latest:
            lines.append(f"  最新价: {latest.get('close', 'N/A')} 涨跌幅: {latest.get('pct_chg', 'N/A')}%")
        val = result.get("valuation", {})
        if val:
            lines.append(f"  PE: {val.get('pe', 'N/A')} PB: {val.get('pb', 'N/A')} 总市值: {val.get('total_mv', 'N/A')}")
        return "\n".join(lines)

    async def install(self, user_id: int, mcp_id: str, env_values: dict) -> dict:
        """安装 MCP：写 MySQL + 建堆内存映射（不启动实例）"""
        meta = mcp_registry.get(mcp_id)
        if not meta:
            return {"success": False, "message": f"MCP {mcp_id} 不存在于市场"}

        fingerprint = config_fingerprint(meta, env_values)
        env_encrypted = crypto.encrypt(json.dumps(env_values, ensure_ascii=False))

        # 写堆内存映射（不启动实例）
        self._user_map[(user_id, mcp_id)] = fingerprint
        self._loaded_users.add(user_id)
        logger.info(f"[MCP][安装] 用户 {user_id} 安装 {mcp_id}, 指纹={fingerprint}")
        # 返回 version 供后端写 MySQL（mcp_version 字段）
        return {"success": True, "fingerprint": fingerprint,
                "env_encrypted": env_encrypted, "version": meta.version}

    async def uninstall(self, user_id: int, mcp_id: str):
        """卸载 MCP：减引用 + 删堆内存映射"""
        fp = self._user_map.pop((user_id, mcp_id), None)
        if not fp:
            return

        if fp in self._sessions:
            entry = self._sessions[fp]
            entry.user_ids.discard(user_id)
            entry.ref_count -= 1
            if entry.ref_count <= 0:
                # 关闭 SDK 实例
                entry.started = False
                entry.session = None
                del self._sessions[fp]
                logger.info(f"[MCP][卸载] 关闭实例: {mcp_id}, 指纹={fp}")

        logger.info(f"[MCP][卸载] 用户 {user_id} 卸载 {mcp_id}")

    async def update_env(self, user_id: int, mcp_id: str, new_env: dict) -> dict:
        """改 Token：更新指纹 + 关闭旧实例（下次调用时懒启动新实例）"""
        meta = mcp_registry.get(mcp_id)
        if not meta:
            return {"success": False, "message": f"MCP {mcp_id} 不存在"}

        old_fp = self._user_map.get((user_id, mcp_id))
        new_fp = config_fingerprint(meta, new_env)

        if old_fp == new_fp:
            return {"success": True, "fingerprint": new_fp, "env_encrypted": crypto.encrypt(json.dumps(new_env)), "message": "配置未变"}

        # 更新映射
        self._user_map[(user_id, mcp_id)] = new_fp

        # 旧实例减引用
        if old_fp and old_fp in self._sessions:
            entry = self._sessions[old_fp]
            entry.user_ids.discard(user_id)
            entry.ref_count -= 1
            if entry.ref_count <= 0:
                entry.started = False
                entry.session = None
                del self._sessions[old_fp]
                logger.info(f"[MCP][改Token] 关闭旧实例: {mcp_id}, 旧指纹={old_fp}")

        env_encrypted = crypto.encrypt(json.dumps(new_env, ensure_ascii=False))
        logger.info(f"[MCP][改Token] 用户 {user_id} 更新 {mcp_id} Token, 新指纹={new_fp}")
        return {"success": True, "fingerprint": new_fp, "env_encrypted": env_encrypted}

    async def _evict_idle(self):
        """LRU 淘汰：关闭空闲时间最长的实例"""
        now = time.time()
        candidates = [
            (fp, entry) for fp, entry in self._sessions.items()
            if now - entry.last_used > IDLE_TIMEOUT_S
        ]
        if candidates:
            fp, entry = min(candidates, key=lambda x: x[1].last_used)
            entry.started = False
            entry.session = None
            del self._sessions[fp]
            logger.warning(f"[MCP][淘汰] 强制关闭空闲实例, 指纹={fp}")

    async def cleanup_idle(self):
        """定时任务：清理空闲实例（每 5 分钟跑一次）"""
        now = time.time()
        for fp in list(self._sessions.keys()):
            entry = self._sessions[fp]
            if now - entry.last_used > IDLE_TIMEOUT_S:
                entry.started = False
                entry.session = None
                del self._sessions[fp]
                logger.info(f"[MCP][清理] 空闲超时关闭实例, 指纹={fp}")


# 全局单例
mcp_client_pool = McpClientPool()
