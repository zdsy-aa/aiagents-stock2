# -*- coding: utf-8 -*-
"""automation.market_env 市场环境数据(Phase5 Task5.6)。

提供市场环境快照 market_snapshot() 与数据质量三查 quality_check(df):

- 大盘指数:上证指数(000001.SH)日K,akshare 优先(stock_zh_index_daily 新浪
  源 → index_zh_a_hist 东财源),失败回退本地 index_sh000001.csv(profit_mining
  同源文件)。trend 口径参照 tq_confirm_top10._get_index_state:
  空头 = close<MA20 且 MA20<MA60;多头 = close>MA20 且 MA20>MA60;否则震荡;
  日K不足 60 根不判趋势(tq 脚本同口径)。
- 涨停/跌停/连板高度:akshare stock_zt_pool_em / stock_zt_pool_dtgc_em
  (东财 push2ex,本机当前被 IP 封禁——降级 None 并记 notes,见 5.5 报告)。
- sentiment 简单规则:涨停数>100 且连板高度≥5 → 亢奋;涨停数<30 → 冰点;
  否则中性;任一输入缺失 → None(取不到标 None,不编造)。
- 任一字段取数失败标 None 并在 notes 记录原因(全局约束:失败不静默、可重试);
  本模块不抛异常,方便编排任务直接调用。

字段约定(代码 6 位/日期 YYYYMMDD/不复权)见 docs/data_contract.md。
"""
from __future__ import annotations

import logging
from datetime import datetime

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

__all__ = ["market_snapshot", "quality_check"]

# 上证指数(akshare sina 记法 sh000001 / 东财记法 000001;与 tq 脚本
# 999999.SH 同标的)。IDX_COUNT=tq 脚本 120 根;趋势判定的最小根数 60
# (tq_confirm_top10._get_index_state:不足 60 根返回 (None, None))。
INDEX_SYMBOL_SINA = "sh000001"
INDEX_SYMBOL_EM = "000001"
MIN_BARS = 60
LOCAL_INDEX_CSV = "/home/tdxback/aiagents-stock/data/profit_mining/index_sh000001.csv"

# akshare 可选依赖(venv-data 已装 1.18.97;其他环境缺失时降级)。
try:
    import akshare as ak
except Exception as _exc:  # pragma: no cover - 依赖环境决定
    ak = None
    _AK_IMPORT_ERROR = f"{type(_exc).__name__}: {_exc}"
else:
    _AK_IMPORT_ERROR = ""


# ---------------------------------------------------------------------------
# sentiment 规则
# ---------------------------------------------------------------------------

def _sentiment(limit_up, height):
    """涨停数/连板高度 → 市场情绪(简单规则,Phase5 简报口径)。

    - limit_up > 100 且 height >= 5 → 「亢奋」;
    - limit_up < 30 → 「冰点」;
    - 其余 → 「中性」;
    - 任一输入为 None → None(规则无法判定,不编造)。
    """
    if limit_up is None or height is None:
        return None
    if limit_up > 100 and height >= 5:
        return "亢奋"
    if limit_up < 30:
        return "冰点"
    return "中性"


# ---------------------------------------------------------------------------
# 取数(每步独立、可 monkeypatch;失败抛异常,由 market_snapshot 捕获记 notes)
# ---------------------------------------------------------------------------

def _normalize_index(raw):
    """akshare 指数日K各接口返回 → DataFrame(index=DatetimeIndex, 仅 Close)。

    兼容中英文列名(date/日期;close/Close/收盘)。空表/缺列返回 None。
    """
    if raw is None or getattr(raw, "empty", True):
        return None
    df = raw.copy()
    date_col = next((c for c in ("date", "日期") if c in df.columns), None)
    close_col = next((c for c in ("close", "Close", "收盘", "最新价") if c in df.columns), None)
    if date_col is None or close_col is None:
        return None
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    df["Close"] = pd.to_numeric(df[close_col], errors="coerce")
    return df.set_index(date_col).sort_index()[["Close"]].dropna()


def _ak_index_history():
    """akshare 上证指数日K(优先新浪 stock_zh_index_daily,备选东财
    index_zh_a_hist / stock_zh_index_daily_em)。全部不可用抛 RuntimeError。"""
    if ak is None:
        raise RuntimeError(f"akshare 未安装:{_AK_IMPORT_ERROR}")
    last_err = "无可用接口"
    today = datetime.now().strftime("%Y%m%d")
    candidates = [
        ("stock_zh_index_daily", lambda f: f(symbol=INDEX_SYMBOL_SINA)),
        ("index_zh_a_hist", lambda f: f(symbol=INDEX_SYMBOL_EM, period="daily",
                                        start_date="19900101", end_date=today)),
        ("stock_zh_index_daily_em", lambda f: f(symbol=INDEX_SYMBOL_SINA,
                                                start_date="19900101", end_date=today)),
    ]
    for name, call in candidates:
        fn = getattr(ak, name, None)
        if fn is None:
            continue
        try:
            frame = _normalize_index(call(fn))
        except Exception as exc:
            last_err = f"{name}: {type(exc).__name__}: {exc}"
            continue
        if frame is not None and len(frame):
            return frame
        last_err = f"{name}: 空返回"
    raise RuntimeError(f"akshare 指数日K全部接口失败({last_err})")


def _local_index_history():
    """本地上证指数 CSV(profit_mining 同源文件,未复权)。读取失败抛异常。"""
    df = pd.read_csv(LOCAL_INDEX_CSV, encoding="utf-8-sig")
    df["日期"] = pd.to_datetime(df["日期"], errors="coerce")
    df["Close"] = pd.to_numeric(df["Close"], errors="coerce")
    frame = df.set_index("日期").sort_index()[["Close"]].dropna()
    if frame.empty:
        raise RuntimeError("本地指数 CSV 无有效数据")
    return frame


def _fetch_index_history():
    """上证指数日K → (frame, source)。akshare 优先,失败回退本地 CSV;
    两源都失败抛 RuntimeError(消息含两源错误,不静默)。

    独立 seam 供测试 monkeypatch(返回 (DataFrame, source_str))。
    """
    ak_err = "未尝试"
    try:
        frame = _ak_index_history()
        if frame is not None and len(frame):
            return frame, "akshare"
        ak_err = "akshare 返回空表"
    except Exception as exc:
        ak_err = f"{type(exc).__name__}: {exc}"
        logger.warning("akshare 指数日K不可用(%s),回退本地 CSV", exc)
    try:
        return _local_index_history(), "local_csv"
    except Exception as exc2:
        raise RuntimeError(
            f"指数日K两源均失败(akshare: {ak_err};本地CSV: {type(exc2).__name__}: {exc2})") from exc2


def _fetch_zt_pool(date=None):
    """涨停股池 → (涨停数, 最高连板高度)。akshare stock_zt_pool_em。

    - 返回空表 → (0, 0)(可能非交易日或当日无涨停,由调用方记 notes);
    - 缺「连板数」列或该列全 NaN/非数值 → 高度 None(涨停数照常,不因此
      清空整个池结果);
    - 接口失败抛异常(由 market_snapshot 记 notes)。
    """
    if ak is None:
        raise RuntimeError(f"akshare 未安装:{_AK_IMPORT_ERROR}")
    day = date or datetime.now().strftime("%Y%m%d")
    raw = ak.stock_zt_pool_em(date=day)
    if raw is None or getattr(raw, "empty", True):
        return (0, 0)
    count = int(len(raw))
    height_col = next((c for c in raw.columns if "连板" in str(c)), None)
    height = None
    if height_col:
        m = pd.to_numeric(raw[height_col], errors="coerce").max()
        height = int(m) if pd.notna(m) else None
    return (count, height)


def _fetch_dt_pool(date=None):
    """跌停股池 → 跌停数。akshare stock_zt_pool_dtgc_em;失败抛异常。"""
    if ak is None:
        raise RuntimeError(f"akshare 未安装:{_AK_IMPORT_ERROR}")
    day = date or datetime.now().strftime("%Y%m%d")
    raw = ak.stock_zt_pool_dtgc_em(date=day)
    if raw is None or getattr(raw, "empty", True):
        return 0
    return int(len(raw))


# ---------------------------------------------------------------------------
# 对外接口
# ---------------------------------------------------------------------------

def market_snapshot():
    """市场环境快照 → dict(简报键集 + notes)。

    Returns:
        {"date": "YYYYMMDD"|None, "index_close": float|None, "ma20": float|None,
         "ma60": float|None, "trend": "多头"|"空头"|"震荡"|None,
         "limit_up_count": int|None, "limit_down_count": int|None,
         "limit_up_height": int|None, "sentiment": "亢奋"|"冰点"|"中性"|None,
         "notes": [str, ...]}
    任一字段取不到标 None 并在 notes 记录原因;本函数不抛异常。
    """
    result = {
        "date": None,
        "index_close": None,
        "ma20": None,
        "ma60": None,
        "trend": None,
        "limit_up_count": None,
        "limit_down_count": None,
        "limit_up_height": None,
        "sentiment": None,
    }
    notes = []

    # 1. 大盘指数:akshare → 本地 CSV 回退(来源/失败均记 notes,不静默)
    frame, source = None, None
    try:
        frame, source = _fetch_index_history()
    except Exception as exc:
        notes.append(f"指数日K失败: {type(exc).__name__}: {exc}")
    if frame is None or len(frame) < MIN_BARS:
        notes.append(f"上证指数日K不足 {MIN_BARS} 根,不判趋势"
                     f"(实际 {len(frame) if frame is not None else 0})")
    else:
        notes.append(f"指数日K来源: {source}({len(frame)} 根)")
    if frame is not None and len(frame):
        last_date = frame.index[-1]
        result["date"] = pd.Timestamp(last_date).strftime("%Y%m%d")
        result["index_close"] = float(frame["Close"].iloc[-1])
    # 趋势与均线只在数据充足时计算(tq 脚本口径:不足 60 根不判趋势)
    if frame is not None and len(frame) >= MIN_BARS:
        close = frame["Close"]
        ma20 = float(close.rolling(20, min_periods=20).mean().iloc[-1])
        ma60 = float(close.rolling(60, min_periods=60).mean().iloc[-1])
        result["ma20"] = None if np.isnan(ma20) else ma20
        result["ma60"] = None if np.isnan(ma60) else ma60
        if result["ma20"] is not None and result["ma60"] is not None:
            last_close = result["index_close"]
            if last_close < ma20 and ma20 < ma60:
                result["trend"] = "空头"
            elif last_close > ma20 and ma20 > ma60:
                result["trend"] = "多头"
            else:
                result["trend"] = "震荡"

    # 2. 涨停/跌停/连板高度(东财 push2ex,本机 IP 被封时降级并记 notes)
    try:
        result["limit_up_count"], result["limit_up_height"] = _fetch_zt_pool()
    except Exception as exc:
        notes.append(f"涨停股池失败: {type(exc).__name__}: {exc}")
    try:
        result["limit_down_count"] = _fetch_dt_pool()
    except Exception as exc:
        notes.append(f"跌停股池失败: {type(exc).__name__}: {exc}")

    # 3. sentiment 简单规则
    result["sentiment"] = _sentiment(result["limit_up_count"], result["limit_up_height"])
    if result["sentiment"] is None and result["limit_up_count"] is None:
        notes.append("涨停数/连板高度缺失,sentiment 无法判定")

    result["notes"] = notes
    return result


# ---------------------------------------------------------------------------
# 数据质量三查
# ---------------------------------------------------------------------------

KEY_COLS = ("代码", "日期")


def _to_ymd(series):
    """日期列 → YYYYMMDD 字符串(兼容 datetime64 与字符串输入)。"""
    if pd.api.types.is_datetime64_any_dtype(series):
        return series.dt.strftime("%Y%m%d")
    return series.astype(str).str.strip()


def quality_check(df):
    """数据质量三查 → dict(完整性 / 重复 / 异常值)。

    - rows/cols: 形状;
    - dup_keys: 按主键重复的行数(键 = 代码+日期,缺列时取前两列;
      只计重复出现,不含首次);
    - null_cols: 每列缺失计数 {列名: 缺失数}(无缺失的列不出现);
    - bad_dates: 「日期」列非法值数(非合法 YYYYMMDD,含缺失);
    - non_finite: 数值列 ±inf 计数 {列名: 计数}(NaN 计入 null_cols)。

    空表不抛错(rows=0,其余为空)。不修改输入。
    """
    rows = int(len(df))
    cols = int(len(df.columns))
    keys = [c for c in KEY_COLS if c in df.columns]
    if not keys:
        keys = [c for c in df.columns[:2]]
    dup_keys = int(df.duplicated(subset=keys).sum()) if keys and rows else 0
    null_cols = {str(c): int(df[c].isna().sum())
                 for c in df.columns if int(df[c].isna().sum()) > 0}
    bad_dates = 0
    if "日期" in df.columns and rows:
        ymd = _to_ymd(df["日期"])
        bad_dates = int(pd.to_datetime(ymd, format="%Y%m%d", errors="coerce").isna().sum())
    non_finite = {}
    for c in df.columns:
        if pd.api.types.is_numeric_dtype(df[c]):
            n = int(np.isinf(pd.to_numeric(df[c], errors="coerce")).sum())
            if n:
                non_finite[str(c)] = n
    return {"rows": rows, "cols": cols, "dup_keys": dup_keys,
            "null_cols": null_cols, "bad_dates": bad_dates,
            "non_finite": non_finite}
