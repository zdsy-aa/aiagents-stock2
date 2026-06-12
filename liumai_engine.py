# liumai_engine.py
"""六脉神剑指标引擎(纯函数,零IO,零Streamlit)。按通达信公式实现
MACD/KDJ/RSI/LWR/BBI/MTM 六维多头判定 + 加权得分 + 四档状态。
输入日线 DataFrame(列 Open/High/Low/Close/Volume, 索引升序)。"""
from typing import Optional
import numpy as np
import pandas as pd

DIMS = ["MACD", "KDJ", "RSI", "LWR", "BBI", "MTM"]
_WEIGHTS = {"MACD": 20, "KDJ": 15, "RSI": 15, "LWR": 10, "BBI": 20, "MTM": 20}
_MIN_BARS = 30


def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def _tdx_sma(s: pd.Series, n: int, m: int) -> pd.Series:
    """通达信 SMA(X,N,M)=(M*X+(N-M)*前值)/N; 首个有效值取首个非 NaN 的 X。"""
    arr = s.to_numpy(dtype=float)
    out = np.full_like(arr, np.nan)
    prev = np.nan
    for i, x in enumerate(arr):
        if np.isnan(x):
            continue
        prev = x if np.isnan(prev) else (m * x + (n - m) * prev) / n
        out[i] = prev
    return pd.Series(out, index=s.index)


def compute_flags(df: pd.DataFrame) -> pd.DataFrame:
    """逐根六维多头布尔(列=DIMS, 索引=df.index)。NaN 预热期记 False。"""
    c = df["Close"].astype(float)
    h = df["High"].astype(float)
    lo = df["Low"].astype(float)

    macd_fast = _ema(c, 8) - _ema(c, 13)
    macd = macd_fast > _ema(macd_fast, 5)

    llv8, hhv8 = lo.rolling(8).min(), h.rolling(8).max()
    rsv = (c - llv8) / (hhv8 - llv8).replace(0, np.nan) * 100
    k = _tdx_sma(rsv, 3, 1)
    kdj = k > _tdx_sma(k, 3, 1)

    diff = c - c.shift(1)
    up, ab = diff.clip(lower=0), diff.abs()
    rsi_s = _tdx_sma(up, 5, 1) / _tdx_sma(ab, 5, 1).replace(0, np.nan) * 100
    rsi_l = _tdx_sma(up, 13, 1) / _tdx_sma(ab, 13, 1).replace(0, np.nan) * 100
    rsi = rsi_s > rsi_l

    hhv13, llv13 = h.rolling(13).max(), lo.rolling(13).min()
    lwr_raw = (-(hhv13 - c)) / (hhv13 - llv13).replace(0, np.nan) * 100
    lwr_k = _tdx_sma(lwr_raw, 3, 1)
    lwr = lwr_k > _tdx_sma(lwr_k, 3, 1)

    bbi = (c.rolling(3).mean() + c.rolling(6).mean()
           + c.rolling(12).mean() + c.rolling(24).mean()) / 4
    bbi_bull = c > bbi

    mtm_s = 100 * _ema(_ema(diff, 5), 3) / _ema(_ema(ab, 5), 3).replace(0, np.nan)
    mtm_l = 100 * _ema(_ema(diff, 13), 8) / _ema(_ema(ab, 13), 8).replace(0, np.nan)
    mtm = mtm_s > mtm_l

    return pd.DataFrame({"MACD": macd, "KDJ": kdj, "RSI": rsi,
                         "LWR": lwr, "BBI": bbi_bull, "MTM": mtm}).fillna(False)


def bull_count_series(df: pd.DataFrame) -> pd.Series:
    """逐根多头数(0-6); df 过短(<30 根)返回空 Series。"""
    if df is None or len(df) < _MIN_BARS:
        return pd.Series(dtype=int)
    return compute_flags(df)[DIMS].sum(axis=1).astype(int)


def score_of(flags_row) -> int:
    """单根六维布尔 → 加权得分(0-100)。"""
    return int(sum(_WEIGHTS[d] for d in DIMS if bool(flags_row[d])))


def state_of(score: int) -> str:
    if score >= 70:
        return "强势"
    if score >= 40:
        return "偏多"
    if score > 20:
        return "震荡"
    return "偏空"


def latest_snapshot(df: pd.DataFrame) -> Optional[dict]:
    """最新一根快照; df 过短返回 None。"""
    if df is None or len(df) < _MIN_BARS:
        return None
    row = compute_flags(df).iloc[-1]
    score = score_of(row)
    snap = {
        "signal_date": pd.Timestamp(df.index[-1]).strftime("%Y-%m-%d"),
        "bull_count": int(sum(bool(row[d]) for d in DIMS)),
        "score": score, "state": state_of(score),
    }
    for d in DIMS:
        snap[d] = int(bool(row[d]))
    return snap
