# -*- coding: utf-8 -*-
"""信号生命周期追踪测试(Phase5 Task5.3)。

隔离纪律(与 test_failure_db.py 同款):
- autouse fixture 把 st.DB_PATH(信号追踪库)与 fb.DB_PATH(失败库)都指向
  tmp_path,绝不写真实 data/backtest_signals.db / data/backtest_failures.db;
- signal_stats 的面板加载(st.load_panel / st.load_confirm_panel)一律
  monkeypatch 合成面板,不加载 15M 确认面板与真实 CSV。
"""
import sqlite3

import pandas as pd
import pytest

import automation.signal_tracking as st
import backtest.failure_db as fb


@pytest.fixture(autouse=True)
def _isolate_real_dbs(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "DB_PATH", str(tmp_path / "signals.db"))
    monkeypatch.setattr(fb, "DB_PATH", str(tmp_path / "failures.db"))


def _df():
    return pd.DataFrame({
        "股票代码": ["1", "2", "3", "4"],
        "信号日期": ["20240101", "20240102", "20240103", "20240104"],
        "是否盈利": [0, 1, 0, 1],
        "区间涨跌幅": [-0.10, 0.05, -0.20, 0.30],
        "年": ["2024"] * 4,
    })


# ---------- record_signals ----------

def test_record_signals_all_hits_to_signals_failures_subset():
    st.init_db()
    n = st.record_signals("TQ01", _df(), pd.Series([True] * 4), "市场环境")
    assert n == 4                                   # 全部命中行落追踪表
    with sqlite3.connect(st.DB_PATH) as conn:
        rows = conn.execute(
            "SELECT combo, code, date, win, ret, days FROM signals ORDER BY code"
        ).fetchall()
    assert rows == [
        ("TQ01", "1", "20240101", 0, -0.1, 20),
        ("TQ01", "2", "20240102", 1, 0.05, 20),
        ("TQ01", "3", "20240103", 0, -0.2, 20),
        ("TQ01", "4", "20240104", 1, 0.3, 20),
    ]
    assert fb.failure_stats("TQ01")["市场环境"] == 2   # 仅未盈利行复用失败库


def test_record_signals_idempotent_rerun():
    st.init_db()
    df = _df()
    st.record_signals("TQ01", df, pd.Series([True] * 4), "参数")
    n = st.record_signals("TQ01", df, pd.Series([True] * 4), "参数")   # 重跑
    assert n == 0                                   # 去重键 (combo, code, date)
    with sqlite3.connect(st.DB_PATH) as conn:
        assert conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0] == 4
    assert fb.failure_stats("TQ01")["参数"] == 2


def test_record_signals_respects_mask():
    st.init_db()
    n = st.record_signals("TQ01", _df(), pd.Series([True, False, True, False]))
    assert n == 2
    with sqlite3.connect(st.DB_PATH) as conn:
        codes = [r[0] for r in conn.execute("SELECT code FROM signals")]
    assert sorted(codes) == ["1", "3"]


def test_record_signals_default_reason_and_enum():
    st.init_db()
    st.record_signals("TQ01", _df(), pd.Series([True, False, False, False]))
    assert fb.failure_stats("TQ01")["市场环境"] == 1    # 默认 reason
    with pytest.raises(ValueError):
        st.record_signals("TQ01", _df(), pd.Series([True] * 4), "心情不好")


def test_record_signals_blank_code_rejected():
    st.init_db()
    df = _df()
    df.loc[0, "股票代码"] = None
    with pytest.raises(ValueError):
        st.record_signals("TQ01", df, pd.Series([True, False, False, False]))
    with sqlite3.connect(st.DB_PATH) as conn:
        assert conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0] == 0


def test_record_signals_missing_columns_rejected():
    with pytest.raises(ValueError):
        st.record_signals("TQ01", _df().drop(columns=["区间涨跌幅"]),
                          pd.Series([True] * 4))


# ---------- signal_stats ----------

def test_signal_stats_shape():
    df = st.signal_stats("不存在组合")      # 空库返回空表不抛错(简报用例)
    assert {"组合", "1天后成功率", "3天后成功率"} <= set(df.columns)
    assert len(df) == 0


def test_signal_stats_matches_panel_semantics(monkeypatch):
    """Phase 4 comparison 匹配语义:按 (代码, 信号日期+N天) 先买点面板后确认面板。"""
    st.init_db()
    df = pd.DataFrame({
        "股票代码": ["1", "1", "2"],
        "信号日期": ["20240101", "20240102", "20240101"],
        "是否盈利": [0, 0, 0],
        "区间涨跌幅": [0.0, 0.0, 0.0],
        "年": ["2024"] * 3,
    })
    st.record_signals("TQ01", df, pd.Series([True] * 3))
    buy = pd.DataFrame({
        "股票代码": ["1", "2"],
        "信号日期": ["2024-01-02", "2024-01-04"],
        "是否盈利": [1, 0],
        "区间涨跌幅": [0.10, -0.05],
    })
    confirm = pd.DataFrame({
        "股票代码": ["1", "1", "2"],
        "信号日期": [20240104, 20240103, 20240102],
        "是否盈利": [0, 1, 1],
        "区间涨跌幅": [-0.20, 0.15, 0.08],
    })
    monkeypatch.setattr(st, "load_panel", lambda: buy)
    monkeypatch.setattr(st, "load_confirm_panel", lambda **kw: confirm)
    out = st.signal_stats("TQ01", days=(1, 3))
    assert len(out) == 1
    row = out.iloc[0]
    assert row["组合"] == "TQ01"
    assert row["1天后成功率"] == 1.0        # A/B/C 全部命中且盈利
    assert abs(row["1天后平均收益"] - 0.11) < 1e-9     # (0.10+0.15+0.08)/3
    assert abs(row["1天后最大回撤"] - 0.0) < 1e-9      # 全正收益无回撤
    assert row["3天后成功率"] == 0.0        # A(0)、C(0);B 未匹配不计入分母
    assert abs(row["3天后平均收益"] - (-0.125)) < 1e-9  # (-0.20-0.05)/2
    assert abs(row["3天后最大回撤"] - 0.05) < 1e-9       # 净值 1→0.8→0.76


def test_signal_stats_all_combo_aggregate(monkeypatch):
    st.init_db()
    df = pd.DataFrame({
        "股票代码": ["1", "2"],
        "信号日期": ["20240101", "20240101"],
        "是否盈利": [0, 0],
        "区间涨跌幅": [0.0, 0.0],
        "年": ["2024"] * 2,
    })
    st.record_signals("TQ01", df, pd.Series([True, False]))
    st.record_signals("TQ02", df, pd.Series([False, True]))
    buy = pd.DataFrame({
        "股票代码": ["1", "2"],
        "信号日期": ["2024-01-02", "2024-01-02"],
        "是否盈利": [1, 0],
        "区间涨跌幅": [0.05, -0.03],
    })
    monkeypatch.setattr(st, "load_panel", lambda: buy)
    monkeypatch.setattr(st, "load_confirm_panel", lambda **kw: pd.DataFrame())
    out = st.signal_stats()                 # combo_name=None 全库聚合
    assert len(out) == 1
    row = out.iloc[0]
    assert row["组合"] == "全部"
    assert row["1天后成功率"] == 0.5        # (1+0)/2
    assert abs(row["1天后平均收益"] - 0.01) < 1e-9
    assert abs(row["1天后最大回撤"] - 0.03) < 1e-9  # 净值 1.05→1.0185


def test_signal_stats_days_validation():
    with pytest.raises(ValueError):
        st.signal_stats(days=(0, 1))
    with pytest.raises(ValueError):
        st.signal_stats(days=(-1,))
    df = st.signal_stats(days=3)            # 标量 days 接受(与 comparison_table 同口径)
    assert "3天后成功率" in df.columns


# ---------- failure_breakdown ----------

def test_failure_breakdown_six_categories():
    st.init_db()
    st.record_signals("TQ01", _df(), pd.Series([True] * 4), "指标")
    st.record_signals("TQ02", _df(), pd.Series([True] * 4), "执行")
    bd = st.failure_breakdown("TQ01")
    assert set(bd) == set(fb.CATEGORIES)       # 六分类齐全,未出现按 0
    assert bd["指标"] == 2 and bd["组合"] == 0
    assert st.failure_breakdown()["指标"] == 2
    assert st.failure_breakdown()["执行"] == 2
    assert st.failure_breakdown("不存在")["指标"] == 0
