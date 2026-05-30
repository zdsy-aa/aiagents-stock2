# tests/test_chanlun_single.py
import numpy as np
import pandas as pd
import chanlun_single
from chanlun_single import _normalize, query_stock_signals, KEEP_COLS


def _fake_day(n=300, seed=1):
    """构造一段先跌后涨的随机游走日线，确保引擎能产出买卖点（含买点）。
    n=300, seed=1 经验证可产出 1卖/2卖/1买，索引为日期。"""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-01-01", periods=n, freq="D")
    prices = [50.0]
    for i in range(n - 1):
        trend = -0.5 if i < n // 2 else 0.5
        noise = float(rng.normal(0, 2.0))
        prices.append(max(5.0, prices[-1] + trend + noise))
    prices = np.array(prices)
    highs = prices + 3.0
    lows = prices - 3.0
    return pd.DataFrame({"Open": prices, "High": highs, "Low": lows,
                         "Close": prices, "Volume": [1] * n}, index=idx)


def test_normalize_strips_prefix_and_space():
    assert _normalize("sh600519") == "600519"
    assert _normalize("SZ000001") == "000001"
    assert _normalize(" 600519 ") == "600519"


def test_invalid_code_rejected():
    ok, df, msg = query_stock_signals("abc")
    assert ok is False and df is None and "6 位" in msg
    ok2, _, _ = query_stock_signals("12345")
    assert ok2 is False


def test_no_data_returns_friendly(monkeypatch):
    monkeypatch.setattr(chanlun_single, "_load", lambda *a, **k: None)
    ok, df, msg = query_stock_signals("600519")
    assert ok is False and df is None and "日线" in msg


def test_signals_assembled_sorted_desc(monkeypatch):
    day = _fake_day()

    def fake_load(sym, kind, limit):
        return day if kind == "day" else None  # 30min 返回 None → 无次级别确认分支

    monkeypatch.setattr(chanlun_single, "_load", fake_load)
    ok, df, msg = query_stock_signals("600519")
    assert ok is True and df is not None
    assert list(df.columns) == KEEP_COLS
    assert df["signal_date"].iloc[0] >= df["signal_date"].iloc[-1]
    buys = df[df["signal_type"].isin(["1买", "2买", "3买"])]
    sells = df[df["signal_type"].isin(["1卖", "2卖", "3卖"])]
    assert (buys["stop_loss"].notna()).all()
    if len(sells):
        assert (sells["stop_loss"].isna()).all()
