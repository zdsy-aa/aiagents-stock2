# tests/test_liumai_engine.py
import numpy as np
import pandas as pd
from liumai_engine import (_tdx_sma, compute_flags, bull_count_series,
                           score_of, state_of, latest_snapshot, DIMS)


def _df(closes):
    """用收盘价序列构造 OHLC(High=close+0.5, Low=close-0.5)。索引为日期。"""
    closes = list(closes)
    idx = pd.date_range("2026-01-01", periods=len(closes), freq="D")
    return pd.DataFrame({
        "Open": closes, "High": [c + 0.5 for c in closes],
        "Low": [c - 0.5 for c in closes], "Close": closes,
        "Volume": [1] * len(closes),
    }, index=idx)


def _bullish_df():
    """60根全六维多头行情: 缓涨30根 → 回调5根 → 强势反弹25根。
    纯线性斜率在 TDX 递推公式下 K==D 永远 False，需要"先跌后涨"
    使短周期均线重新超越长周期均线，才能令 KDJ/RSI/LWR/MTM 均为多头。
    """
    closes = [10 + i * 0.5 for i in range(30)]      # 缓涨
    for _ in range(5):
        closes.append(closes[-1] - 1.0)              # 小幅回调
    for _ in range(25):
        closes.append(closes[-1] + 1.0)              # 强势反弹
    return _df(closes)


def test_tdx_sma_recursive():
    s = pd.Series([2.0, 4.0, 6.0])
    out = _tdx_sma(s, 2, 1)
    assert out.iloc[0] == 2.0
    assert out.iloc[1] == (4.0 + 2.0) / 2
    assert out.iloc[2] == (6.0 + 3.0) / 2


def test_strong_uptrend_all_bullish():
    df = _bullish_df()
    snap = latest_snapshot(df)
    assert snap is not None
    assert snap["bull_count"] == 6
    assert snap["score"] == 100
    assert snap["state"] == "强势"
    assert all(snap[d] == 1 for d in DIMS)


def test_downtrend_low_bull():
    df = _df([100 - i for i in range(60)])
    snap = latest_snapshot(df)
    assert snap is not None
    assert snap["bull_count"] <= 1
    assert snap["state"] == "偏空"


def test_insufficient_bars_returns_none():
    df = _df([10 + i for i in range(20)])
    assert latest_snapshot(df) is None
    assert bull_count_series(df).empty


def test_state_boundaries():
    assert state_of(100) == "强势"
    assert state_of(70) == "强势"
    assert state_of(40) == "偏多"
    assert state_of(21) == "震荡"
    assert state_of(20) == "偏空"
    assert state_of(0) == "偏空"


def test_bull_count_series_indexed_by_date():
    df = _bullish_df()
    bc = bull_count_series(df)
    assert len(bc) == 60
    assert (bc.index == df.index).all()
    assert bc.iloc[-1] == 6
