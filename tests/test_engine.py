"""Task 3.2: 统一回测引擎 run_backtest 的指标单元测试(合成面板)。

对齐验收(57 信号,确认面板)见 tests/test_alignment_57.py。
"""
import math

import pandas as pd

from backtest.engine import run_backtest


def test_run_backtest_metrics():
    """简报口径:win_rate / avg_ret / max_consec_loss(合成 4 行)。"""
    df = pd.DataFrame({"股票代码": ["1"] * 4,
                       "信号日期": ["20240101", "20240102", "20240103", "20240104"],
                       "是否盈利": [1, 1, 0, 0],
                       "区间涨跌幅": [0.15, 0.12, -0.05, -0.10],
                       "年": ["2024"] * 4})
    spec = {"name": "T", "conds": [{"col": "是否盈利", "op": ">=", "value": -1}],
            "join": "AND"}
    r = run_backtest(spec, df)
    assert r["n"] == 4 and r["win_rate"] == 0.5
    assert abs(r["avg_ret"] - 0.03) < 1e-9
    assert r["max_consec_loss"] == 2
    assert r["trades"] == 4 and r["wins"] == 2


def test_run_backtest_full_metrics():
    """九项指标手工核算(6 行,日期升序):回撤/年化/盈亏比/标准差/最大涨幅。"""
    df = pd.DataFrame({"股票代码": ["1"] * 6,
                       "信号日期": [20240101, 20240102, 20240103, 20240104,
                                    20240105, 20240106],
                       "是否盈利": [1, 1, 0, 0, 1, 0],
                       "区间涨跌幅": [0.10, 0.20, -0.10, -0.05, 0.30, -0.20],
                       "年": [2024] * 6})
    spec = {"name": "T", "conds": [{"col": "是否盈利", "op": ">=", "value": -1}],
            "join": "AND"}
    r = run_backtest(spec, df)
    assert r["n"] == 6 and r["wins"] == 3 and r["win_rate"] == 0.5
    assert abs(r["avg_ret"] - 0.25 / 6) < 1e-9
    assert abs(r["max_ret"] - 0.30) < 1e-9
    # 累计净值 [1.10,1.32,1.188,1.1286,1.46718,1.173744]:最大回撤在第 6 行
    # 1 - 1.173744/1.46718 = 0.2
    assert abs(r["max_drawdown"] - 0.2) < 1e-9
    # 年化 (1+0.25/6)^(250/20)-1
    expected_annual = (1 + 0.25 / 6) ** (250 / 20) - 1
    assert abs(r["annual_ret"] - expected_annual) < 1e-12
    # 盈亏比:平均盈利 0.2 / 平均亏损 (0.10+0.05+0.20)/3
    assert abs(r["profit_loss_ratio"] - 0.2 / (0.35 / 3)) < 1e-12
    assert r["max_consec_loss"] == 2
    assert abs(r["ret_std"] - pd.Series([0.10, 0.20, -0.10, -0.05, 0.30, -0.20]).std()) < 1e-12


def test_run_backtest_sorts_by_date():
    """打乱输入行序:回撤/连续亏损按信号日期排序后计算,结果与升序输入一致。"""
    base = pd.DataFrame({"股票代码": ["1"] * 4,
                         "信号日期": [20240101, 20240102, 20240103, 20240104],
                         "是否盈利": [1, 1, 0, 0],
                         "区间涨跌幅": [0.10, 0.12, -0.05, -0.10],
                         "年": [2024] * 4})
    shuffled = base.sample(frac=1, random_state=42)
    spec = {"name": "T", "conds": [{"col": "是否盈利", "op": ">=", "value": -1}],
            "join": "AND"}
    r_sorted = run_backtest(spec, base)
    r_shuffled = run_backtest(spec, shuffled)
    assert r_sorted["max_drawdown"] == r_shuffled["max_drawdown"]
    assert r_sorted["max_consec_loss"] == r_shuffled["max_consec_loss"]
    assert r_sorted["win_rate"] == r_shuffled["win_rate"] == 0.5


def test_run_backtest_empty_mask():
    """n=0:中性值 + ret_std/盈亏比 NaN,不崩溃。"""
    df = pd.DataFrame({"股票代码": ["1"] * 3,
                       "信号日期": [20240101, 20240102, 20240103],
                       "是否盈利": [1, 0, 1], "区间涨跌幅": [0.1, -0.1, 0.2],
                       "年": [2024] * 3})
    spec = {"name": "T", "conds": [{"col": "是否盈利", "op": "==", "value": 99}],
            "join": "AND"}
    r = run_backtest(spec, df)
    assert r["n"] == 0 and r["trades"] == 0 and r["wins"] == 0
    assert r["win_rate"] == 0.0 and r["avg_ret"] == 0.0 and r["max_ret"] == 0.0
    assert r["max_drawdown"] == 0.0 and r["annual_ret"] == 0.0
    assert r["max_consec_loss"] == 0
    assert math.isnan(r["ret_std"]) and math.isnan(r["profit_loss_ratio"])


def test_run_backtest_no_loss_profit_loss_ratio_inf():
    df = pd.DataFrame({"股票代码": ["1"] * 2,
                       "信号日期": [20240101, 20240102],
                       "是否盈利": [1, 1], "区间涨跌幅": [0.1, 0.2],
                       "年": [2024] * 2})
    spec = {"name": "T", "conds": [{"col": "是否盈利", "op": ">=", "value": -1}],
            "join": "AND"}
    r = run_backtest(spec, df)
    assert r["win_rate"] == 1.0 and r["max_consec_loss"] == 0
    assert math.isinf(r["profit_loss_ratio"]) and r["profit_loss_ratio"] > 0
