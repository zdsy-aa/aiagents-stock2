"""
AKShare 统一数据网关 v3
四级数据源降级链：TDX(本地Docker) → AKTools(HTTP) → 本地akshare → Tushare

特点：
  1. TDX 优先 — 本地Docker最快最稳，不受IP封禁影响
  2. AKTools HTTP — 独立进程隔离，可部署在不同IP的机器上
  3. 本地 akshare — 直接调用，被封接口设短超时避免卡死
  4. Tushare — 最终兜底
  5. 全局限流 + 分级缓存 + 调用统计
"""

import os
import time
import json
import socket
import sqlite3
import logging
import threading
import requests as http_requests
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


# ============ 缓存 TTL 配置（秒） ============

CACHE_TTL = {
    'realtime':    10,    # 实时行情
    'intraday':    30,    # 分钟级数据
    'daily':       300,   # 日K线
    'fund_flow':   120,   # 资金流向
    'financial':   3600,  # 财务数据
    'macro':       7200,  # 宏观经济
    'sector':      180,   # 板块数据
    'news':        300,   # 新闻
    'index':       60,    # 指数
    'market':      60,    # 全市场行情
}


# ============ 被封接口清单 ============
# 走 push2his.eastmoney.com 的接口，当前服务器 IP 被封
# 仍然会尝试调用（万一解封），但设短超时(5秒)避免卡死

BLOCKED_EM_FUNCS = {
    'stock_zh_a_hist',
    'stock_zh_a_hist_min_em',
    'stock_individual_info_em',
    'stock_individual_spot_em',
    'stock_zh_a_spot_em',
    'stock_zh_index_spot_em',
    'stock_individual_fund_flow',
    'stock_individual_fund_flow_rank',
    'stock_sector_fund_flow_rank',
    'stock_board_industry_name_em',
    'stock_board_concept_name_em',
    'stock_zt_pool_em',
    'stock_zt_pool_dtgc_em',
    'stock_margin_underlying_info_szse',
    'stock_margin_szsh',
    'stock_hsgt_fund_flow_summary_em',
    'stock_hk_spot_em',
    'stock_news_em',
}


# ============ TDX 接口能力映射 ============
# TDX Docker 能替代哪些 akshare 接口
TDX_CAPABLE_FUNCS = {
    'stock_zh_a_hist',            # 日K线
    'stock_zh_a_hist_min_em',     # 分钟K线
    'stock_individual_info_em',   # 个股信息（部分）
    'stock_individual_spot_em',   # 个股实时
    'stock_zh_a_spot_em',         # 全市场行情（逐个获取）
}


class RateLimiter:
    """令牌桶限流器"""

    def __init__(self, rate=1.0, burst=3):
        self.rate = rate
        self.burst = burst
        self.tokens = burst
        self.last_time = time.time()
        self.lock = threading.Lock()

    def acquire(self, timeout=30):
        deadline = time.time() + timeout
        while True:
            with self.lock:
                now = time.time()
                elapsed = now - self.last_time
                self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
                self.last_time = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return True
            if time.time() >= deadline:
                return False
            time.sleep(0.1)


class DataCache:
    """线程安全的内存缓存"""

    def __init__(self, max_size=500):
        self._cache = {}
        self._lock = threading.Lock()
        self._max_size = max_size

    def get(self, key):
        with self._lock:
            if key in self._cache:
                value, expiry = self._cache[key]
                if time.time() < expiry:
                    return value
                del self._cache[key]
        return None

    def set(self, key, value, ttl=60):
        """设置缓存 (P2 整改十二: 优化清理机制)"""
        with self._lock:
            # P2 整改十二: 无论是否满，都定期触发清理（比如 1/10 的概率）
            import random
            if len(self._cache) >= self._max_size or random.random() < 0.1:
                self._evict_expired()
            self._cache[key] = (value, time.time() + ttl)

    def _evict_expired(self):
        now = time.time()
        expired = [k for k, (_, exp) in self._cache.items() if now >= exp]
        for k in expired:
            del self._cache[k]

    @property
    def size(self):
        return len(self._cache)


# ================================================================
#  数据源客户端
# ================================================================

class LocalDBClient:
    """本地下载K线数据源（第0优先级，最高）

    读取 tdx-api `pull-kline` 落地的 SQLite 文件，实现真正的本地/离线数据。
    目录结构：<base_dir>/<代码>.db，文件名兼容裸代码（600519.db）与
    带市场前缀（sh600519.db / sz000001.db / bj920000.db）两种命名。
    表名：DayKline / WeekKline / MonthKline / Minute1Kline / Minute5Kline /
          Minute15Kline / Minute30Kline / HourKline
    列：Code, Date(unix秒,UTC), Open, High, Low, Close, Volume, Amount（价格×1000）
    """

    _PERIOD_TO_TABLE = {
        'day': 'DayKline', 'week': 'WeekKline', 'month': 'MonthKline',
        '1min': 'Minute1Kline', '5min': 'Minute5Kline', '15min': 'Minute15Kline',
        '30min': 'Minute30Kline', '60min': 'HourKline', '1hour': 'HourKline',
        # 已是 tdx-api 命名的直接透传
        'minute1': 'Minute1Kline', 'minute5': 'Minute5Kline', 'minute15': 'Minute15Kline',
        'minute30': 'Minute30Kline', 'hour': 'HourKline',
    }
    _INTRADAY_TABLES = {'Minute1Kline', 'Minute5Kline', 'Minute15Kline', 'Minute30Kline', 'HourKline'}

    def __init__(self, base_dir):
        self.base_dir = base_dir
        self.enabled = os.getenv('LOCAL_DB_ENABLED', 'true').lower() == 'true'
        self.available = self.enabled and bool(base_dir) and os.path.isdir(base_dir)
        if self.available:
            logger.info(f"✅ [0] 本地数据源已就绪: {base_dir}")
        elif self.enabled:
            logger.info(f"ℹ️ [0] 本地数据源目录不存在（将跳过）: {base_dir}")

    def _db_path(self, symbol):
        code = str(symbol).split('.')[0]
        # 兼容裸代码与带市场前缀两种文件名（tdx-api 批量下载用前缀名）：
        # 命中第一个存在的；都不存在时返回裸名占位，交由 get_kline 的 exists 检查降级。
        for fname in (f"{code}.db", f"sh{code}.db", f"sz{code}.db", f"bj{code}.db"):
            p = os.path.join(self.base_dir, fname)
            if os.path.exists(p):
                return p
        return os.path.join(self.base_dir, f"{code}.db")

    def get_kline(self, symbol, kline_type='day', limit=None, start_date=None, end_date=None):
        """从本地 SQLite 读取K线，返回与 TDXClient 一致的中文列 DataFrame"""
        if not self.available:
            return None
        table = self._PERIOD_TO_TABLE.get(kline_type)
        if not table:
            return None
        path = self._db_path(symbol)
        if not os.path.exists(path):
            return None
        try:
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                cur = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
                )
                if not cur.fetchone():
                    return None
                df = pd.read_sql_query(
                    f"SELECT Date, Open, High, Low, Close, Volume, Amount FROM {table} ORDER BY Date",
                    conn
                )
            finally:
                conn.close()

            if df is None or df.empty:
                return None

            # unix(UTC) → 北京时间；日/周/月归一化为日期，分钟/小时保留完整时间戳
            dt = pd.to_datetime(df['Date'], unit='s') + pd.Timedelta(hours=8)
            if table not in self._INTRADAY_TABLES:
                dt = dt.dt.normalize()

            out = pd.DataFrame({
                '日期': dt,
                '开盘': df['Open'].astype(float) / 1000.0,
                '收盘': df['Close'].astype(float) / 1000.0,
                '最高': df['High'].astype(float) / 1000.0,
                '最低': df['Low'].astype(float) / 1000.0,
                '成交量': df['Volume'].astype(float),
                '成交额': df['Amount'].astype(float),
            })

            if start_date:
                out = out[out['日期'] >= pd.to_datetime(start_date)]
            if end_date:
                out = out[out['日期'] <= pd.to_datetime(end_date)]
            if limit and len(out) > limit:
                out = out.tail(limit)

            out = out.sort_values('日期').reset_index(drop=True)
            return out if not out.empty else None
        except Exception as e:
            logger.debug(f"[本地] 读取失败 {symbol} {table}: {type(e).__name__}: {str(e)[:60]}")
            return None


class TDXClient:
    """TDX Docker API 客户端（第1优先级）"""

    _RECHECK_INTERVAL = 60        # 正常重连间隔（秒）
    _FAST_RECHECK_INTERVAL = 10   # 刚失败后的快速重连间隔（秒）

    # 网关内部周期名 → tdx-api 的 type 参数（tdx-api 读 query 参数 "type"，
    # 取值 minute1/minute5/minute15/minute30/hour/day/week/month）
    _PERIOD_TO_TDX_TYPE = {
        'day': 'day', 'week': 'week', 'month': 'month',
        '1min': 'minute1', '5min': 'minute5', '15min': 'minute15',
        '30min': 'minute30', '60min': 'hour', '1hour': 'hour',
        # 已是 tdx-api 命名的直接透传
        'minute1': 'minute1', 'minute5': 'minute5', 'minute15': 'minute15',
        'minute30': 'minute30', 'hour': 'hour',
    }

    def __init__(self, base_url='http://127.0.0.1:8080'):
        self.base_url = base_url
        self.available = False
        self._last_check_time = 0.0
        self._check()

    def _check(self):
        self._last_check_time = time.time()
        try:
            r = http_requests.get(
                f"{self.base_url}/api/kline",
                params={"code": "SZ000001", "type": "day", "limit": 1},
                timeout=5
            )
            if r.status_code == 200 and r.json().get('code') == 0:
                if not self.available:
                    logger.info(f"✅ [1] TDX 数据源可用: {self.base_url}")
                self.available = True
            else:
                self.available = False
                # 下次 _FAST_RECHECK_INTERVAL 秒后重试
                self._last_check_time = time.time() - (self._RECHECK_INTERVAL - self._FAST_RECHECK_INTERVAL)
        except Exception as e:
            self.available = False
            logger.warning(f"⚠️ [1] TDX 不可用: {e}")
            # 下次 _FAST_RECHECK_INTERVAL 秒后重试
            self._last_check_time = time.time() - (self._RECHECK_INTERVAL - self._FAST_RECHECK_INTERVAL)

    def _maybe_recheck(self):
        """若当前不可用，每隔 _RECHECK_INTERVAL 秒自动重试一次"""
        if not self.available and (time.time() - self._last_check_time) >= self._RECHECK_INTERVAL:
            logger.info("[TDX] 尝试重新连接...")
            self._check()

    def _to_code(self, symbol):
        symbol = symbol.split('.')[0]
        if symbol.startswith(('6', '9', '5')):
            return f"SH{symbol}"
        return f"SZ{symbol}"

    def get_kline(self, symbol, kline_type='day', limit=250):
        """获取K线（日/分钟）"""
        self._maybe_recheck()
        if not self.available:
            return None
        try:
            code = self._to_code(symbol)
            tdx_type = self._PERIOD_TO_TDX_TYPE.get(kline_type, kline_type)
            r = http_requests.get(
                f"{self.base_url}/api/kline",
                params={"code": code, "type": tdx_type, "limit": limit},
                timeout=10
            )
            if r.status_code == 200:
                items = r.json().get('data', {}).get('List', [])
                if items:
                    # 分钟/小时级保留完整时间戳；日/周/月仅取日期（避免日线带 15:00 影响按日筛选）
                    is_intraday = tdx_type in ('minute1', 'minute5', 'minute15', 'minute30', 'hour')
                    rows = []
                    for d in items:
                        t = d.get('Time', '')
                        rows.append({
                            '日期': t if is_intraday else t[:10],
                            '开盘': float(d.get('Open', 0)) / 1000.0,
                            '收盘': float(d.get('Close', 0)) / 1000.0,
                            '最高': float(d.get('High', 0)) / 1000.0,
                            '最低': float(d.get('Low', 0)) / 1000.0,
                            '成交量': float(d.get('Volume', 0)),
                            '成交额': float(d.get('Amount', 0)),
                        })
                    df = pd.DataFrame(rows)
                    df['日期'] = pd.to_datetime(df['日期'])
                    df = df.sort_values('日期').reset_index(drop=True)
                    return df
        except Exception as e:
            logger.warning(f"[TDX] K线失败 {symbol}: {e}")
        return None

    def get_quote(self, symbol):
        """获取实时行情"""
        self._maybe_recheck()
        if not self.available:
            return None
        try:
            code = self._to_code(symbol)
            r = http_requests.get(
                f"{self.base_url}/api/quote",
                params={"code": code},
                timeout=5
            )
            if r.status_code == 200:
                data = r.json()
                if data.get('code') == 0:
                    return data.get('data')
        except Exception as e:
            logger.warning(f"[TDX] 行情失败 {symbol}: {e}")
        return None


class AKToolsClient:
    """AKTools HTTP API 客户端（第2优先级，支持远程云服务器 + Basic Auth）"""

    def __init__(self, base_url='http://127.0.0.1:8088', timeout=15):
        self.base_url = base_url
        self.timeout = timeout
        self.available = False

        # Basic Auth 认证（云服务器 Nginx 反代需要）
        auth_user = os.getenv('AKTOOLS_AUTH_USER', '')
        auth_pass = os.getenv('AKTOOLS_AUTH_PASS', '')
        self.auth = (auth_user, auth_pass) if auth_user and auth_pass else None

        self._check()

    def _check(self):
        try:
            r = http_requests.get(
                f"{self.base_url}/version",
                auth=self.auth,
                timeout=5
            )
            if r.status_code == 200:
                ver = r.json()
                location = '远程' if self.auth else '本地'
                logger.info(
                    f"✅ [2] AKTools({location})可用: {self.base_url} "
                    f"(AKShare={ver.get('ak_current_version')}, "
                    f"AKTools={ver.get('at_current_version')})"
                )
                self.available = True
            elif r.status_code == 401:
                logger.warning(f"⚠️ [2] AKTools 认证失败，请检查 AKTOOLS_AUTH_USER/PASS")
        except Exception as e:
            logger.warning(f"⚠️ [2] AKTools 不可用: {e}")

    def call(self, func_name, **kwargs):
        """通过 HTTP 调用 akshare 接口"""
        if not self.available:
            return None
        try:
            url = f"{self.base_url}/api/public/{func_name}"
            params = {k: v for k, v in kwargs.items() if v is not None}
            r = http_requests.get(
                url, params=params,
                auth=self.auth,
                timeout=self.timeout
            )
            if r.status_code == 200:
                data = r.json()
                if data:
                    return pd.DataFrame(data)
        except Exception as e:
            logger.debug(f"[AKTools] {func_name} 失败: {type(e).__name__}: {str(e)[:60]}")
        return None


class TushareClient:
    """Tushare 数据源客户端（第4优先级 / 最终兜底）"""

    def __init__(self):
        self.api = None
        self.available = False
        token = os.getenv('TUSHARE_TOKEN', '')
        if token:
            try:
                import tushare as ts
                ts.set_token(token)
                self.api = ts.pro_api()
                self.available = True
                logger.info("✅ [4] Tushare 数据源可用")
            except Exception as e:
                logger.warning(f"⚠️ [4] Tushare 初始化失败: {e}")

    def _to_ts_code(self, symbol):
        symbol = symbol.split('.')[0]
        if symbol.startswith(('6', '9')):
            return f"{symbol}.SH"
        return f"{symbol}.SZ"

    def get_daily(self, symbol, start_date=None, end_date=None):
        if not self.available:
            return None
        try:
            ts_code = self._to_ts_code(symbol)
            if not end_date:
                end_date = datetime.now().strftime('%Y%m%d')
            if not start_date:
                start_date = (datetime.now() - timedelta(days=365)).strftime('%Y%m%d')
            df = self.api.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
            if df is not None and not df.empty:
                df = df.rename(columns={
                    'trade_date': '日期', 'open': '开盘', 'close': '收盘',
                    'high': '最高', 'low': '最低', 'vol': '成交量', 'amount': '成交额',
                    'pct_chg': '涨跌幅', 'change': '涨跌额'
                })
                df['日期'] = pd.to_datetime(df['日期'])
                df['成交量'] = df['成交量'] * 100
                df['成交额'] = df['成交额'] * 1000
                df = df.sort_values('日期').reset_index(drop=True)
                return df
        except Exception as e:
            logger.warning(f"[Tushare] 日线失败 {symbol}: {e}")
        return None

    def get_daily_basic(self, symbol):
        if not self.available:
            return None
        try:
            ts_code = self._to_ts_code(symbol)
            df = self.api.daily_basic(
                ts_code=ts_code, trade_date=datetime.now().strftime('%Y%m%d')
            )
            if df is not None and not df.empty:
                return df
        except Exception as e:
            logger.warning(f"[Tushare] 基本面失败 {symbol}: {e}")
        return None

    def get_moneyflow(self, symbol, days=30):
        if not self.available:
            return None
        try:
            ts_code = self._to_ts_code(symbol)
            end_date = datetime.now().strftime('%Y%m%d')
            start_date = (datetime.now() - timedelta(days=days * 2)).strftime('%Y%m%d')
            df = self.api.moneyflow(
                ts_code=ts_code, start_date=start_date, end_date=end_date
            )
            if df is not None and not df.empty:
                return df
        except Exception as e:
            logger.warning(f"[Tushare] 资金流向失败 {symbol}: {e}")
        return None

    def get_index_daily(self, ts_code='000001.SH', start_date=None, end_date=None):
        if not self.available:
            return None
        try:
            if not end_date:
                end_date = datetime.now().strftime('%Y%m%d')
            if not start_date:
                start_date = (datetime.now() - timedelta(days=30)).strftime('%Y%m%d')
            df = self.api.index_daily(
                ts_code=ts_code, start_date=start_date, end_date=end_date
            )
            if df is not None and not df.empty:
                return df
        except Exception as e:
            logger.warning(f"[Tushare] 指数失败: {e}")
        return None

    def get_hsgt_flow(self, days=20):
        if not self.available:
            return None
        try:
            end_date = datetime.now().strftime('%Y%m%d')
            start_date = (datetime.now() - timedelta(days=days)).strftime('%Y%m%d')
            df = self.api.moneyflow_hsgt(
                start_date=start_date, end_date=end_date
            )
            if df is not None and not df.empty:
                return df
        except Exception as e:
            logger.warning(f"[Tushare] 北向资金失败: {e}")
        return None

    def call_generic(self, api_name, **kwargs):
        """通用 Tushare 接口调用"""
        if not self.available:
            return None
        try:
            func = getattr(self.api, api_name, None)
            if func:
                df = func(**kwargs)
                if df is not None and not df.empty:
                    return df
        except Exception as e:
            logger.warning(f"[Tushare] {api_name} 失败: {e}")
        return None


# ================================================================
#  核心网关
# ================================================================

class AKShareGateway:
    """
    AKShare 统一数据网关 v3

    四级降级链：TDX → AKTools HTTP → 本地 akshare → Tushare
    
    使用方式：
        from akshare_gateway import akshare_gw
        df = akshare_gw.call('stock_zh_a_hist', cache_category='daily',
                             symbol='600519', period='daily', ...)
    """

    def __init__(self):
        # ---- 第0级：本地下载库（最高优先级） ----
        local_dir = os.getenv("LOCAL_DB_DIR", "/app/tdx-data/database/kline")
        self.local = LocalDBClient(base_dir=local_dir)

        # ---- 四个数据源 ----
        tdx_url = os.getenv("TDX_BASE_URL", "http://127.0.0.1:8080")
        self.tdx = TDXClient(base_url=tdx_url)

        aktools_url = os.getenv("AKTOOLS_BASE_URL", "http://127.0.0.1:8088")
        aktools_timeout = int(os.getenv("AKTOOLS_TIMEOUT", "15"))
        self.aktools = AKToolsClient(base_url=aktools_url, timeout=aktools_timeout)

        # 被封接口调 akshare 时的短超时（秒），避免卡死
        self.blocked_timeout = int(os.getenv("BLOCKED_AKSHARE_TIMEOUT", "5"))

        self.tushare = TushareClient()

        # ---- 限流 ----
        rate = float(os.getenv("AKSHARE_RATE_LIMIT", "1.0"))
        burst = int(os.getenv("AKSHARE_BURST_LIMIT", "3"))
        self.rate_limiter = RateLimiter(rate=rate, burst=burst)

        # ---- 缓存 ----
        self.cache = DataCache(max_size=500)

        # ---- 统计 ----
        self._stats = {
            'cache_hit': 0,
            'local_ok': 0, 'local_fail': 0,
            'tdx_ok': 0, 'tdx_fail': 0,
            'aktools_ok': 0, 'aktools_fail': 0,
            'akshare_ok': 0, 'akshare_fail': 0,
            'tushare_ok': 0, 'tushare_fail': 0,
            'all_fail': 0, 'rate_limited': 0,
        }
        self._stats_lock = threading.Lock()

        src_status = (
            f"本地={'✅' if self.local.available else '❌'} | "
            f"TDX={'✅' if self.tdx.available else '❌'} | "
            f"AKTools={'✅' if self.aktools.available else '❌'} | "
            f"AKShare=✅ | "
            f"Tushare={'✅' if self.tushare.available else '❌'}"
        )
        logger.info(f"📡 网关 v3 初始化 | {src_status} | 限流={rate}/s 突发={burst}")

    def _inc_stat(self, key):
        with self._stats_lock:
            self._stats[key] = self._stats.get(key, 0) + 1

    # ================================================================
    #  统一入口
    # ================================================================

    def call(self, func_name: str, cache_category: str = 'daily', **kwargs):
        """
        统一调用入口 — 自动按 TDX→AKTools→akshare→Tushare 降级
        
        Args:
            func_name: akshare 函数名，如 'stock_zh_a_hist'
            cache_category: 缓存类别（见 CACHE_TTL）
            **kwargs: 传给接口的参数
        Returns:
            pd.DataFrame 或 None
        """
        # 1. 查缓存
        cache_key = self._make_cache_key(func_name, kwargs)
        cached = self.cache.get(cache_key)
        if cached is not None:
            self._inc_stat('cache_hit')
            return cached

        # 2. 限流
        if not self.rate_limiter.acquire(timeout=30):
            self._inc_stat('rate_limited')
            logger.warning(f"[限流] {func_name} 超时丢弃")
            return None

        # 3. 四级降级调用
        df = self._call_chain(func_name, **kwargs)

        # 4. 缓存
        if df is not None and not df.empty:
            ttl = CACHE_TTL.get(cache_category, 60)
            self.cache.set(cache_key, df, ttl=ttl)

        return df

    def get_minute_kline(self, symbol, freq, limit=240):
        """获取分钟K线（route B 本地 → TDX；东财分钟接口被封，不走 AKTools/akshare）。

        freq: '5min' / '30min'（本地 _PERIOD_TO_TABLE 与 TDX _PERIOD_TO_TDX_TYPE 均支持）
        返回中文列 DataFrame（日期/开盘/收盘/最高/最低/成交量/成交额）或 None
        """
        if self.local.available:
            df = self.local.get_kline(symbol, kline_type=freq, limit=limit)
            if df is not None and not df.empty:
                return df
        if self.tdx.available:
            df = self.tdx.get_kline(symbol, kline_type=freq, limit=limit)
            if df is not None and not df.empty:
                return df
        return None

    # ================================================================
    #  四级降级链
    # ================================================================

    def _call_chain(self, func_name, **kwargs):
        """TDX → AKTools → akshare → Tushare"""

        symbol = str(kwargs.get('symbol') or kwargs.get('stock') or '').split('.')[0]
        is_blocked = func_name in BLOCKED_EM_FUNCS
        has_tdx = func_name in TDX_CAPABLE_FUNCS

        # strip symbol/stock so they don't conflict with the positional 'symbol' arg
        # in _try_local / _try_tdx / _try_tushare
        _kw = {k: v for k, v in kwargs.items() if k not in ('symbol', 'stock')}

        # ---- 第0级：本地下载库（最高优先级，命中即用，完全离线） ----
        if has_tdx and self.local.available:
            df = self._try_local(func_name, symbol, **_kw)
            if df is not None and not df.empty:
                self._inc_stat('local_ok')
                logger.debug(f"[0-本地 ✓] {func_name} → {len(df)} rows")
                return df
            self._inc_stat('local_fail')

        # ---- 第1级：TDX ----
        if has_tdx and self.tdx.available:
            df = self._try_tdx(func_name, symbol, **_kw)
            if df is not None and not df.empty:
                self._inc_stat('tdx_ok')
                logger.debug(f"[1-TDX ✓] {func_name} → {len(df)} rows")
                return df
            self._inc_stat('tdx_fail')

        # ---- 第2级：AKTools HTTP ----
        if self.aktools.available:
            df = self.aktools.call(func_name, **kwargs)
            if df is not None and not df.empty:
                self._inc_stat('aktools_ok')
                logger.debug(f"[2-AKTools ✓] {func_name} → {len(df)} rows")
                return df
            self._inc_stat('aktools_fail')

        # ---- 第3级：本地 akshare ----
        df = self._try_akshare(func_name, is_blocked, **kwargs)
        if df is not None and not df.empty:
            self._inc_stat('akshare_ok')
            logger.debug(f"[3-AKShare ✓] {func_name} → {len(df)} rows")
            return df
        self._inc_stat('akshare_fail')

        # ---- 第4级：Tushare 兜底 ----
        df = self._try_tushare(func_name, symbol, **_kw)
        if df is not None and not df.empty:
            self._inc_stat('tushare_ok')
            logger.debug(f"[4-Tushare ✓] {func_name} → {len(df)} rows")
            return df
        self._inc_stat('tushare_fail')

        # 全部失败
        self._inc_stat('all_fail')
        logger.warning(f"[ALL FAIL] {func_name} 四级数据源均失败")
        return None

    # ================================================================
    #  第0级：本地下载库
    # ================================================================

    def _try_local(self, func_name, symbol, **kwargs):
        """尝试从本地下载的 SQLite 库获取数据（仅 K线类接口）"""
        if not symbol:
            return None

        # 日K线（支持区间过滤）
        if func_name == 'stock_zh_a_hist':
            return self.local.get_kline(
                symbol, kline_type='day',
                start_date=kwargs.get('start_date') or None,
                end_date=kwargs.get('end_date') or None,
            )

        # 分钟K线（默认 1 分钟，与 TDX 行为一致）
        elif func_name == 'stock_zh_a_hist_min_em':
            return self.local.get_kline(symbol, kline_type='1min')

        return None

    # ================================================================
    #  第1级：TDX
    # ================================================================

    def _try_tdx(self, func_name, symbol, **kwargs):
        """尝试从 TDX 获取数据"""
        if not symbol:
            return None

        # 日K线
        if func_name == 'stock_zh_a_hist':
            start_date = kwargs.get('start_date', '')
            end_date = kwargs.get('end_date', '')
            df = self.tdx.get_kline(symbol, kline_type='day', limit=500)
            if df is not None and not df.empty:
                if start_date:
                    df = df[df['日期'] >= pd.to_datetime(start_date)]
                if end_date:
                    df = df[df['日期'] <= pd.to_datetime(end_date)]
                if not df.empty:
                    return df

        # 分钟K线
        elif func_name == 'stock_zh_a_hist_min_em':
            return self.tdx.get_kline(symbol, kline_type='1min', limit=240)

        # 个股实时行情
        elif func_name in ('stock_individual_spot_em', 'stock_individual_info_em'):
            data = self.tdx.get_quote(symbol)
            if data:
                return pd.DataFrame([data])

        # 全市场实时行情（TDX 逐个太慢，跳过让后面的数据源处理）
        elif func_name == 'stock_zh_a_spot_em':
            return None

        return None

    # ================================================================
    #  第2级：AKTools HTTP（已在 _call_chain 中直接调用）
    # ================================================================

    # ================================================================
    #  第3级：本地 akshare
    # ================================================================

    def _try_akshare(self, func_name, is_blocked, **kwargs):
        """
        直接调用本地 akshare
        被封接口设短超时(5秒)，正常接口用默认超时
        """
        try:
            import akshare as ak
            func = getattr(ak, func_name, None)
            if func is None:
                return None

            clean_kwargs = {k: v for k, v in kwargs.items() if v is not None}

            if is_blocked:
                # 被封接口：设置短超时，用线程执行避免卡死
                result = [None]
                exc = [None]

                def _run():
                    try:
                        result[0] = func(**clean_kwargs)
                    except Exception as e:
                        exc[0] = e

                t = threading.Thread(target=_run, daemon=True)
                t.start()
                t.join(timeout=self.blocked_timeout)

                if t.is_alive():
                    logger.debug(f"[AKShare] {func_name} 超时({self.blocked_timeout}s)，跳过")
                    return None
                if exc[0]:
                    logger.debug(f"[AKShare] {func_name} 被封: {str(exc[0])[:60]}")
                    return None
                return result[0]
            else:
                # 正常接口：直接调用
                df = func(**clean_kwargs)
                return df

        except Exception as e:
            logger.debug(f"[AKShare] {func_name} 失败: {type(e).__name__}: {str(e)[:80]}")
        return None

    # ================================================================
    #  第4级：Tushare
    # ================================================================

    def _try_tushare(self, func_name, symbol, **kwargs):
        """Tushare 兜底，根据 func_name 映射到对应的 Tushare 接口"""
        if not self.tushare.available:
            return None

        # 日K线
        if func_name == 'stock_zh_a_hist':
            return self.tushare.get_daily(
                symbol,
                kwargs.get('start_date'),
                kwargs.get('end_date')
            )

        # 个股基本信息
        if func_name == 'stock_individual_info_em':
            return self.tushare.get_daily_basic(symbol)

        # 全市场行情
        if func_name in ('stock_zh_a_spot_em', 'stock_individual_spot_em'):
            if func_name == 'stock_zh_a_spot_em':
                return self.tushare.call_generic(
                    'daily', trade_date=datetime.now().strftime('%Y%m%d')
                )
            else:
                return self.tushare.get_daily_basic(symbol)

        # 指数行情
        if func_name == 'stock_zh_index_spot_em':
            sym = kwargs.get('symbol', '')
            index_map = {
                '上证指数': '000001.SH', '上证系列指数': '000001.SH',
                '深证成指': '399001.SZ', '创业板指': '399006.SZ',
            }
            ts_code = index_map.get(sym, '000001.SH')
            return self.tushare.get_index_daily(ts_code=ts_code)

        # 资金流向
        if func_name == 'stock_individual_fund_flow':
            return self.tushare.get_moneyflow(symbol)

        # 资金流向排名
        if func_name in ('stock_individual_fund_flow_rank', 'stock_sector_fund_flow_rank'):
            return None  # Tushare 无直接对应

        # 板块
        if func_name in ('stock_board_industry_name_em', 'stock_board_concept_name_em'):
            return None  # Tushare 需要更高权限

        # 涨跌停
        if func_name in ('stock_zt_pool_em', 'stock_zt_pool_dtgc_em'):
            try:
                date = kwargs.get('date', datetime.now().strftime('%Y%m%d'))
                limit_type = 'U' if func_name == 'stock_zt_pool_em' else 'D'
                return self.tushare.call_generic(
                    'limit_list_d', trade_date=date, limit_type=limit_type
                )
            except Exception:
                return None

        # 融资融券
        if func_name in ('stock_margin_underlying_info_szse', 'stock_margin_szsh'):
            date = kwargs.get('date', datetime.now().strftime('%Y%m%d'))
            return self.tushare.call_generic('margin_detail', trade_date=date)

        # 北向资金
        if func_name == 'stock_hsgt_fund_flow_summary_em':
            return self.tushare.get_hsgt_flow()

        # 新闻（Tushare 有 news 接口但质量一般）
        if func_name == 'stock_news_em':
            return self.tushare.call_generic('news', src='sina')

        # 其他未映射的接口，Tushare 无法替代
        return None

    # ================================================================
    #  工具方法
    # ================================================================

    def _make_cache_key(self, func_name, kwargs):
        filtered = {k: v for k, v in kwargs.items() if v is not None}
        try:
            params_str = json.dumps(filtered, sort_keys=True, default=str)
        except (TypeError, ValueError):
            params_str = str(filtered)
        return f"{func_name}:{params_str}"

    def get_stats(self) -> dict:
        with self._stats_lock:
            stats = dict(self._stats)
        stats['cache_size'] = self.cache.size
        return stats

    def print_stats(self):
        s = self.get_stats()
        total = (s.get('local_ok', 0) + s['tdx_ok'] + s['aktools_ok']
                 + s['akshare_ok'] + s['tushare_ok'] + s['cache_hit'])
        logger.info(
            f"📊 网关统计 | "
            f"缓存命中:{s['cache_hit']} | "
            f"本地✓:{s.get('local_ok', 0)} ✗:{s.get('local_fail', 0)} | "
            f"TDX✓:{s['tdx_ok']} ✗:{s['tdx_fail']} | "
            f"AKTools✓:{s['aktools_ok']} ✗:{s['aktools_fail']} | "
            f"AKShare✓:{s['akshare_ok']} ✗:{s['akshare_fail']} | "
            f"Tushare✓:{s['tushare_ok']} ✗:{s['tushare_fail']} | "
            f"全失败:{s['all_fail']} | 总成功:{total}"
        )

    def status(self) -> dict:
        """返回各数据源状态"""
        return {
            '本地下载库': '✅ 可用' if self.local.available else '❌ 未启用/无数据',
            'TDX': '✅ 可用' if self.tdx.available else '❌ 不可用',
            'AKTools': '✅ 可用' if self.aktools.available else '❌ 不可用',
            'AKShare': '✅ 可用（部分接口被封）',
            'Tushare': '✅ 可用' if self.tushare.available else '❌ 未配置',
            '被封接口数': len(BLOCKED_EM_FUNCS),
            '降级链': '本地 → TDX → AKTools → AKShare → Tushare',
        }


# ============ 全局单例 ============
akshare_gw = AKShareGateway()
