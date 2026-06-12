# intraday_quote.py —— 盘中实时行情：取全市场快照 + 把"今日实时bar"拼到日K末尾。
#   供 chanlun 盘中重算 与 daily_watchlist 盘中模式 共用。
import pandas as pd
import sys, logging
sys.path.insert(0, "/app")
logger = logging.getLogger(__name__)

_COLS = ["Open", "High", "Low", "Close", "Volume"]

# stock_zh_a_spot_em 中文列 → 标准列
_SPOT_MAP = {"今开": "Open", "最高": "High", "最低": "Low",
             "最新价": "Close", "成交量": "Volume"}


def inject_today_bar(df, bar, today):
    """把今日实时 bar 拼到标准 OHLCV df(index=日期) 末尾。
    bar={'Open','High','Low','Close','Volume'}；today=pd.Timestamp(当天)。
    末行已是今天→覆盖；否则追加。bar 为 None/空→原样返回。不改入参。"""
    if not bar:
        return df
    today = pd.Timestamp(today).normalize()
    row = {c: float(bar.get(c)) for c in _COLS if bar.get(c) is not None}
    if len(row) < len(_COLS):
        return df  # 字段不全，保守不注入
    out = df.copy()
    out.loc[today, _COLS] = [row[c] for c in _COLS]
    return out.sort_index()[_COLS]


def _quote_to_bar(q):
    """TDX /api/quote|batch-quote 单条 q → 标准 bar；停牌(Close<=0)/缺字段→None。"""
    try:
        k = q["K"]
        close = float(k["Close"]) / 1000.0
        if close <= 0:
            return None
        return {"Open": float(k["Open"]) / 1000.0, "High": float(k["High"]) / 1000.0,
                "Low": float(k["Low"]) / 1000.0, "Close": close,
                "Volume": float(q.get("TotalHand", 0))}
    except (KeyError, TypeError, ValueError):
        return None


def _parse_spot(df):
    """全市场快照 DataFrame → {code(6位): {Open,High,Low,Close,Volume}}。
    现价<=0(停牌/无效)或字段缺失的票剔除。"""
    if df is None or len(df) == 0:
        return {}
    need = set(_SPOT_MAP) | {"代码"}
    if not need <= set(df.columns):
        return {}
    out = {}
    for _, r in df.iterrows():
        code = str(r["代码"]).zfill(6)
        try:
            bar = {std: float(r[zh]) for zh, std in _SPOT_MAP.items()}
        except (TypeError, ValueError):
            continue
        if bar["Close"] <= 0:
            continue
        out[code] = bar
    return out


def _tdx_batch_snapshot(codes, chunk=800):
    """TDX /api/batch-quote 批量取行情(优先源)。TDX 不可用 → {}。"""
    from akshare_gateway import akshare_gw
    import requests
    tdx = akshare_gw.tdx
    if not getattr(tdx, "available", False):
        return {}
    base = tdx.base_url.rstrip("/")
    out = {}
    for s in range(0, len(codes), chunk):
        batch = codes[s:s + chunk]
        try:
            r = requests.post(f"{base}/api/batch-quote", json={"codes": batch}, timeout=15)
            if r.status_code != 200:
                continue
            for q in (r.json().get("data") or []):
                code = str(q.get("Code", "")).zfill(6)[-6:]
                bar = _quote_to_bar(q)
                if code and bar:
                    out[code] = bar
        except Exception as e:
            logger.warning(f"[盘中快照] TDX 批量失败 {batch[0]}..: {type(e).__name__}: {str(e)[:60]}")
    return out


def fetch_market_snapshot(codes=None):
    """取实时快照 → {code(6位): bar}。TDX 批量优先，akshare 全市场快照兜底补 TDX 取不到的票。
    codes=None → 全市场(list_universe)。整体取不到返回 {}（调用方降级为纯历史）。"""
    if codes is None:
        from chanlun_universe import list_universe
        codes = [c for c, _, _ in list_universe()]
    codes = [str(c).zfill(6) for c in codes]
    if not codes:
        return {}
    out = _tdx_batch_snapshot(codes)          # 1) TDX 优先
    missing = [c for c in codes if c not in out]
    if missing:                                # 2) akshare 兜底补缺
        try:
            from akshare_gateway import akshare_gw
            sub = _parse_spot(akshare_gw.call("stock_zh_a_spot_em"))
        except Exception:
            sub = {}
        out.update({c: sub[c] for c in missing if c in sub})
    logger.info(f"[盘中快照] 取到 {len(out)}/{len(codes)} 只实时 bar")
    return out


def _trade_cal_dates():
    """返回近年交易日集合(set[pd.Timestamp normalize])，取不到返回 None。"""
    try:
        import akshare as ak
        df = ak.tool_trade_date_hist_sina()
        return {pd.Timestamp(d).normalize() for d in df["trade_date"]}
    except Exception:
        return None


def is_cn_trading_day(today=None):
    """A股交易日判断：优先交易日历，失败退化为工作日(周一~周五)。"""
    today = pd.Timestamp(today or pd.Timestamp.now()).normalize()
    cal = _trade_cal_dates()
    if cal is not None:
        return today in cal
    return today.weekday() < 5
