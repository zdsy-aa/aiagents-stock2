# tests/test_qizhang_batch_logic.py
"""qizhang_batch 纯逻辑：今日行选取 / 候选排名 / 择时 gate / realized 回填(真实 simulate_trade)。"""
import os, sys

import numpy as np
import pandas as pd
import pytest

import qizhang_batch as QB

# realized 用真实 C4 退出口径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "data", "profit_mining"))
from setup_backtest import simulate_trade  # noqa: E402


def test_label_index():
    names = np.array(["fwd_6_20", "fwd_10_10", "fwd_10_20", "excess_10_20"])
    assert QB.label_index(names, "fwd_10_10") == 1


def test_latest_date_mask():
    dates = np.array(["2026-06-10", "2026-06-12", "2026-06-12"], dtype="datetime64[D]")
    m = QB.latest_date_mask(dates)
    assert list(m) == [False, True, True]


def test_build_ranked_picks_sorts_desc_and_caps_topn():
    codes = np.array(["a", "b", "c"], dtype=object)
    scores = np.array([0.2, 0.9, 0.5])
    picks = QB.build_ranked_picks(codes, scores, topn=2)
    assert [p["code"] for p in picks] == ["b", "c"]
    assert [p["rank"] for p in picks] == [1, 2]
    assert picks[0]["score"] == pytest.approx(0.9)


def test_is_riskoff():
    ro = {np.datetime64("2026-06-12")}
    assert QB.is_riskoff(np.datetime64("2026-06-12"), ro) is True
    assert QB.is_riskoff(np.datetime64("2026-06-11"), ro) is False


def test_attach_names_fills_from_map_and_blank_when_missing():
    picks = [{"code": "000001", "score": 1.0, "rank": 1},
             {"code": "999000", "score": 0.5, "rank": 2}]
    QB.attach_names(picks, {"000001": "平安银行"})
    assert picks[0]["name"] == "平安银行"
    assert picks[1]["name"] == ""  # 缺失留空


def _kline(opens, highs, lows, closes, start="2026-01-01"):
    idx = pd.bdate_range(start, periods=len(opens))
    return pd.DataFrame({"Open": opens, "High": highs, "Low": lows, "Close": closes}, index=idx)


def test_compute_realized_trailing_take_profit():
    # 入场=次日开盘10;涨到峰值12后回撤破 12*0.92=11.04 → 移动止盈
    o = [10, 10, 10, 10, 10, 10]
    h = [10, 10, 12, 12, 11, 11]
    l = [10, 10, 10, 11, 10, 10]
    c = [10, 10, 11, 11, 10, 10]
    df = _kline(o, h, l, c)
    scan_date = df.index[0].strftime("%Y-%m-%d")  # entry=次日(index1)开盘
    idx_close = pd.Series([3000.0] * len(df), index=df.index)
    r = QB.compute_realized(df, scan_date, idx_close, simulate_trade, maxhold=30)
    assert r is not None
    assert r["exit_reason"] == "移动止盈"
    assert r["hit_10pct"] is True          # 峰值12 ≥ 入场10×1.1
    assert r["realized_return"] < 0.12      # 扣成本后约 11.04/10-1-0.002


def test_compute_realized_not_mature_returns_none():
    df = _kline([10, 10], [10, 10], [10, 10], [10, 10])
    scan_date = df.index[0].strftime("%Y-%m-%d")
    idx_close = pd.Series([3000.0, 3000.0], index=df.index)
    # 仅 2 根 bar,入场后不足 maxhold → 未到期
    assert QB.compute_realized(df, scan_date, idx_close, simulate_trade, maxhold=30) is None


def test_compute_realized_scan_date_not_in_kline_returns_none():
    df = _kline([10, 10, 10], [10, 10, 10], [10, 10, 10], [10, 10, 10])
    idx_close = pd.Series([3000.0] * 3, index=df.index)
    assert QB.compute_realized(df, "1990-01-01", idx_close, simulate_trade, maxhold=30) is None
