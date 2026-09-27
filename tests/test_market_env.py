# -*- coding: utf-8 -*-
"""automation.market_env 市场环境数据测试(Phase5 Task5.6)。

测试不真实跑网络:指数与涨停/跌停取数经 monkeypatch 注入假数据;降级路径
覆盖全部取数失败。字段约定与 registry 输出名↔面板列名映射表见
docs/data_contract.md。大盘趋势口径参照 tq_confirm_top10._get_index_state:
close<MA20 且 MA20<MA60 空头、close>MA20 且 MA20>MA60 多头、否则震荡;
日K不足 60 根不判趋势。
"""
import numpy as np
import pandas as pd
import pytest

import automation.market_env as me


# ---- 简报原用例 ----

def test_quality_check_counts():
    df = pd.DataFrame({"代码": ["1", "1", "2"], "日期": ["20250101"] * 3})
    q = me.quality_check(df)
    assert q["dup_keys"] == 1 and q["rows"] == 3


def test_sentiment_rules():
    assert me._sentiment(limit_up=200, height=5) == "亢奋"
    assert me._sentiment(limit_up=10, height=2) == "冰点"
    assert me._sentiment(limit_up=80, height=3) == "中性"


# ---- 补充用例 ----

def test_sentiment_none_when_inputs_missing():
    assert me._sentiment(None, 5) is None
    assert me._sentiment(200, None) is None


def test_quality_check_null_and_bad_date():
    df = pd.DataFrame({"代码": ["1", "2", "3"],
                       "日期": ["20250101", "20251399", None]})
    q = me.quality_check(df)
    assert q["rows"] == 3 and q["dup_keys"] == 0
    assert q["bad_dates"] == 2        # 非法月份 20251399 + 缺失日期
    assert q["null_cols"] == {"日期": 1}


def _index_frame(prices):
    """合成上证指数日K(index=DatetimeIndex, Close 列)。"""
    idx = pd.date_range("2025-01-01", periods=len(prices), freq="D")
    return pd.DataFrame({"Close": np.asarray(prices, dtype=float)}, index=idx)


def _patch_index(monkeypatch, prices):
    """按 seam 契约注入合成指数日K:_fetch_index_history -> (frame, source)。"""
    monkeypatch.setattr(me, "_fetch_index_history",
                        lambda: (_index_frame(prices), "fake"))


def test_market_snapshot_bear_trend_and_frozen_sentiment(monkeypatch):
    # 单调下行:close<MA20 且 MA20<MA60 → 空头;涨停 15<30 → 冰点
    _patch_index(monkeypatch, np.linspace(100, 60, 120))
    monkeypatch.setattr(me, "_fetch_zt_pool", lambda: (15, 2))
    monkeypatch.setattr(me, "_fetch_dt_pool", lambda: 40)
    s = me.market_snapshot()
    assert s["trend"] == "空头"
    assert s["index_close"] == pytest.approx(60.0)
    assert s["date"] == "20250430"          # 2025-01-01 + 119 天
    assert s["ma20"] is not None and s["ma60"] is not None
    assert s["limit_up_count"] == 15 and s["limit_up_height"] == 2
    assert s["limit_down_count"] == 40
    assert s["sentiment"] == "冰点"
    assert isinstance(s["notes"], list) and s["notes"]


def test_market_snapshot_bull_trend_and_excited_sentiment(monkeypatch):
    _patch_index(monkeypatch, np.linspace(60, 100, 120))
    monkeypatch.setattr(me, "_fetch_zt_pool", lambda: (200, 5))
    monkeypatch.setattr(me, "_fetch_dt_pool", lambda: 3)
    s = me.market_snapshot()
    assert s["trend"] == "多头"
    assert s["sentiment"] == "亢奋"          # 涨停>100 且连板≥5


def test_market_snapshot_sideways_trend(monkeypatch):
    # 前 60 根 100 走平 → 跌至 90(20 根) → 涨回 100(20 根):
    # 末根 close=100 > MA20=95,MA20=95 < MA60≈96.67 → 多头空头皆不成立 → 震荡
    prices = [100.0] * 60 + list(np.linspace(100, 90, 20)) + list(np.linspace(90, 100, 20))
    _patch_index(monkeypatch, prices)
    monkeypatch.setattr(me, "_fetch_zt_pool", lambda: (80, 4))
    monkeypatch.setattr(me, "_fetch_dt_pool", lambda: 12)
    s = me.market_snapshot()
    assert s["trend"] == "震荡"
    assert s["sentiment"] == "中性"


def test_market_snapshot_insufficient_bars_no_trend(monkeypatch):
    _patch_index(monkeypatch, np.linspace(50, 60, 30))
    monkeypatch.setattr(me, "_fetch_zt_pool", lambda: (80, 4))
    monkeypatch.setattr(me, "_fetch_dt_pool", lambda: 12)
    s = me.market_snapshot()
    assert s["trend"] is None              # 不足 60 根不判趋势(tq 脚本口径)
    assert s["ma20"] is None and s["ma60"] is None
    assert s["index_close"] == pytest.approx(60.0)   # 收盘价仍可取
    assert any("不足" in n for n in s["notes"])


def test_market_snapshot_degraded_when_all_fail(monkeypatch):
    def boom():
        raise RuntimeError("网络不可用")

    monkeypatch.setattr(me, "_fetch_index_history", boom)
    monkeypatch.setattr(me, "_fetch_zt_pool", boom)
    monkeypatch.setattr(me, "_fetch_dt_pool", boom)
    s = me.market_snapshot()
    for k in ("date", "index_close", "ma20", "ma60", "trend",
              "limit_up_count", "limit_down_count", "limit_up_height",
              "sentiment"):
        assert s[k] is None, k
    assert s["notes"] and any("指数" in n for n in s["notes"])


def test_market_snapshot_height_none_when_column_missing(monkeypatch):
    # 涨停池缺「连板数」列 → 高度 None,但涨停数与 sentiment 不因此清空
    _patch_index(monkeypatch, np.linspace(100, 60, 120))
    monkeypatch.setattr(me, "_fetch_zt_pool", lambda: (10, None))
    monkeypatch.setattr(me, "_fetch_dt_pool", lambda: 5)
    s = me.market_snapshot()
    assert s["limit_up_count"] == 10 and s["limit_up_height"] is None
    assert s["sentiment"] is None           # 高度缺失,规则无法判定
