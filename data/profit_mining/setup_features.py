# setup_features.py —— 起涨预测的逐bar连续特征 + 两标签(y_fwd/y_zz)。纯计算,特征只用<=t。
import numpy as np
import pandas as pd

import features as F
import swing_samples as SW
from turnover_features import chip_series

FEATURE_COLS = [
    "vol_std20_pct", "vbar20", "vbar60", "box20", "box60", "profit", "trapped",
    "macd_bar", "macd_bar_slope", "rsi14", "kdj_k",
    "dist_ma5", "dist_ma20", "dist_ma60", "rel_strength", "atr_pct",
    "ret20", "ret60", "pos_year_hi", "pos_year_lo", "turn",
]


def _rsi(c, n=14):
    d = c.diff()
    up = d.clip(lower=0).rolling(n, min_periods=n).mean()
    dn = (-d.clip(upper=0)).rolling(n, min_periods=n).mean()
    return 100 - 100 / (1 + up / (dn + 1e-9))


def _kdj_k(df, n=9):
    low_n = F.LLV(df["Low"], n); high_n = F.HHV(df["High"], n)
    rsv = (df["Close"] - low_n) / (high_n - low_n + 1e-9) * 100
    return rsv.ewm(com=2, adjust=False).mean()


def compute_features(df, idx_close=None, turn=None):
    """df(OHLCV,datetime索引) -> numpy 二维 [n, len(FEATURE_COLS)] (float, 含NaN)。
    idx_close=对齐到df.index的大盘收盘Series(无则相对强弱填NaN); turn=换手率Series(无则chip/turn填NaN)。"""
    c, h, l, v = df["Close"], df["High"], df["Low"], df["Volume"]
    ret = c.pct_change()
    std20 = F.STD(ret, 20)
    cols = {}
    cols["vol_std20_pct"] = std20.rolling(120, min_periods=40).rank(pct=True)
    cols["vbar20"] = v / (F.MA(v, 20) + 1e-9)
    cols["vbar60"] = v / (F.MA(v, 60) + 1e-9)
    cols["box20"] = (F.HHV(c, 20) - F.LLV(c, 20)) / (F.LLV(c, 20) + 1e-9)
    cols["box60"] = (F.HHV(c, 60) - F.LLV(c, 60)) / (F.LLV(c, 60) + 1e-9)
    if turn is not None:
        try:
            ch = chip_series(df, turn)
            cols["profit"] = ch["获利盘"]; cols["trapped"] = ch["套牢盘"]
        except Exception:
            cols["profit"] = pd.Series(np.nan, index=df.index); cols["trapped"] = cols["profit"]
        cols["turn"] = turn.reindex(df.index)
    else:
        cols["profit"] = pd.Series(np.nan, index=df.index)
        cols["trapped"] = pd.Series(np.nan, index=df.index)
        cols["turn"] = pd.Series(np.nan, index=df.index)
    dif = F.EMA(c, 12) - F.EMA(c, 26); dea = F.EMA(dif, 9); bar = dif - dea
    cols["macd_bar"] = bar / (c + 1e-9)
    cols["macd_bar_slope"] = (bar - bar.shift(1)) / (c + 1e-9)
    cols["rsi14"] = _rsi(c, 14)
    cols["kdj_k"] = _kdj_k(df, 9)
    cols["dist_ma5"] = (c - F.MA(c, 5)) / (F.MA(c, 5) + 1e-9)
    cols["dist_ma20"] = (c - F.MA(c, 20)) / (F.MA(c, 20) + 1e-9)
    cols["dist_ma60"] = (c - F.MA(c, 60)) / (F.MA(c, 60) + 1e-9)
    if idx_close is not None:
        cols["rel_strength"] = F.relative_strength(c, idx_close.reindex(df.index).ffill())["相对强弱"]
    else:
        cols["rel_strength"] = pd.Series(np.nan, index=df.index)
    atr = F.TR(df).rolling(14, min_periods=14).mean()
    cols["atr_pct"] = atr / (c + 1e-9)
    cols["ret20"] = c / (c.shift(20) + 1e-9) - 1
    cols["ret60"] = c / (c.shift(60) + 1e-9) - 1
    cols["pos_year_hi"] = (c - F.HHV(c, 250)) / (F.HHV(c, 250) + 1e-9)
    cols["pos_year_lo"] = (c - F.LLV(c, 250)) / (F.LLV(c, 250) + 1e-9)
    M = np.column_stack([cols[k].to_numpy(float) for k in FEATURE_COLS])
    return M


def label_fwd(df, H=20, X=0.06):
    """后H交易日内最大High/当前Close-1>=X ->1; 末尾不足H根 ->NaN。返回 float numpy(0/1/NaN)。"""
    c = df["Close"].to_numpy(float); h = df["High"].to_numpy(float)
    n = len(c); y = np.full(n, np.nan)
    for t in range(n):
        if t + H >= n:
            break
        fwd_max = h[t + 1:t + 1 + H].max()
        y[t] = 1.0 if (fwd_max / c[t] - 1.0) >= X else 0.0
    return y


def label_zz(df, pct=0.06, K=10):
    """t∈某zz段上涨段波谷L的[L-K,L] ->1; 其余0。返回 float numpy(0/1)。
    注:y_zz 用ZigZag(含未来确认)定义,仅作对照标签。"""
    piv = SW.Z.zigzag_pivots(df["High"].tolist(), df["Low"].tolist(), pct)
    wins = SW.presetup_windows_from_pivots(piv, tight_k=K)
    n = len(df); y = np.zeros(n)
    for w in wins:
        for i in w:
            if 0 <= i < n:
                y[i] = 1.0
    return y
