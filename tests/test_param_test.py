"""Task 3.3: 参数网格测试 / 敏感性分析 / 滚动前推 / 过拟合告警(合成小面板)。

真实面板(confirm_panel.npz,15.1M 行)仅做 smoke,不进 CI 单测,结果见任务报告。

简报手写数据勘误(自审记录):简报注释为「A>=2 时盈利,A<2 不盈利」且断言阈值
2.0 时两段胜率均 == 1.0,但其数据 是否盈利=[1,1,1,0,0,0]*4 与 A=[2,1,0,2,1,0]*4
逐行配对后 A=2 行的胜率只有 0.5(断言必失败,数据与注释/断言不自洽)。按注释
意图改用 是否盈利=[1,0,0]*8(A=2 行↔1、A<2 行↔0),断言原样保留。
"""
import pandas as pd
import pytest

from backtest.combo_engine import eval_combo
from backtest.param_test import grid_test, overfit_flag, sensitivity, walk_forward


def _grid_df():
    """24 行小面板:2024×12(训练)/2025×12(测试);A=2 行盈利、A<2 行不盈利。"""
    return pd.DataFrame({"A": [2, 1, 0, 2, 1, 0] * 4,
                         "是否盈利": [1, 0, 0] * 8,
                         "区间涨跌幅": [0.1] * 24,
                         "年": ["2024"] * 12 + ["2025"] * 12,
                         "信号日期": [f"2024{i % 12:02d}01" for i in range(12)]
                         + [f"2025{i % 12:02d}01" for i in range(12)],
                         "股票代码": ["x"] * 24})


def test_grid_test_overfit_flag():
    """简报手工断言:阈值 2.0 两段胜率 1.0 且不过拟合;阈值 0.5 两段一致≈0.5。"""
    spec = {"name": "T", "conds": [{"col": "A", "op": ">=", "value": 0}], "join": "AND"}
    grid = grid_test(spec, {"A": [0.5, 2.0]}, _grid_df())
    r2 = [g for g in grid if g["params"]["A"] == 2.0][0]
    assert r2["train_win_rate"] == 1.0 and r2["test_win_rate"] == 1.0 and not r2["overfit_flag"]
    r0 = [g for g in grid if g["params"]["A"] == 0.5][0]
    assert abs(r0["train_win_rate"] - r0["test_win_rate"]) < 0.31   # 阈值 0.5 时两段一致≈0.5


def test_grid_test_shape_params_and_counts():
    """输出形状:list[dict] 六键;params 依 param_grid 顺序;n 手工核算。"""
    spec = {"name": "T", "conds": [{"col": "A", "op": ">=", "value": 0}], "join": "AND"}
    grid = grid_test(spec, {"A": [0.5, 2.0]}, _grid_df())
    keys = {"params", "train_win_rate", "test_win_rate", "n_train", "n_test", "overfit_flag"}
    assert [g["params"] for g in grid] == [{"A": 0.5}, {"A": 2.0}]
    # A>=0.5 命中 A∈{1,2}:训练 8 行 / 测试 8 行;A>=2.0 只命中 A=2:4/4
    assert [(g["n_train"], g["n_test"]) for g in grid] == [(8, 8), (4, 4)]
    for g in grid:
        assert set(g) == keys
        assert g["overfit_flag"] == overfit_flag(g["train_win_rate"], g["test_win_rate"])


def test_grid_test_two_col_cartesian():
    """多列 param_grid:笛卡尔积 2×2=4 组合;C=1 恒真不改变掩码,便于手工核算。"""
    df = _grid_df().assign(C=1)
    spec = {"name": "T", "join": "AND",
            "conds": [{"col": "A", "op": ">=", "value": 0},
                      {"col": "C", "op": ">=", "value": 0}]}
    grid = grid_test(spec, {"A": [0.5, 2.0], "C": [0.5, 1.0]}, df)
    assert len(grid) == 4
    by = {(g["params"]["A"], g["params"]["C"]): g for g in grid}
    for c in (0.5, 1.0):
        g2 = by[(2.0, c)]
        assert g2["train_win_rate"] == 1.0 and g2["test_win_rate"] == 1.0
        assert (g2["n_train"], g2["n_test"]) == (4, 4) and not g2["overfit_flag"]
        g0 = by[(0.5, c)]
        assert g0["train_win_rate"] == pytest.approx(0.5)
        assert (g0["n_train"], g0["n_test"]) == (8, 8)


def test_grid_test_or_group_replace_and_immutability():
    """递归替换进嵌套 or_group;spec_template 深拷贝后修改,调用后不变。"""
    df = _grid_df().assign(B=[2, 1, 0] * 8)
    template = {"name": "T", "join": "AND",
                "conds": [{"col": "A", "op": ">=", "value": 0},
                          {"or_group": [{"col": "B", "op": ">=", "value": 0}]}]}
    grid = grid_test(template, {"B": [2.0]}, df)
    assert template["conds"][1]["or_group"][0]["value"] == 0   # 模板不可变
    g = grid[0]
    assert g["params"] == {"B": 2.0}
    # or_group 内替换生效:B>=2 只命中 B==2 行(A>=0 恒真)→ 两段 4 行全胜
    assert (g["n_train"], g["n_test"]) == (4, 4)
    assert g["train_win_rate"] == 1.0 and g["test_win_rate"] == 1.0
    assert not g["overfit_flag"]
    # 与 eval_combo 交叉核对:替换后掩码 == A>=0 & B>=2
    m = eval_combo({"name": "T", "join": "AND",
                    "conds": [{"col": "A", "op": ">=", "value": 0},
                              {"or_group": [{"col": "B", "op": ">=", "value": 2.0}]}]}, df)
    assert int(m.sum()) == g["n_train"] + g["n_test"] == 8


def test_grid_test_unknown_col_raises():
    """param_grid 列未出现在任何条件中:fail fast,防笔误静默生成重复组合。"""
    spec = {"name": "T", "conds": [{"col": "A", "op": ">=", "value": 0}], "join": "AND"}
    with pytest.raises(ValueError, match="C"):
        grid_test(spec, {"C": [0.5]}, _grid_df())


def test_overfit_flag_threshold():
    """裁决阈值:差 > 0.10 告警;恰好 0.10 不告警(严格大于)。"""
    assert not overfit_flag(0.6, 0.5)
    assert overfit_flag(0.6, 0.49)
    assert not overfit_flag(0.5, 0.5)
    assert overfit_flag(0.0, 0.3)
    assert not overfit_flag(0.9, 0.8)


def _wf_df():
    """年 2019..2025,每年 4 行全 A=2;年度胜率:2019-2021 全胜,2022 全负,
    2023-2024 全胜,2025 全负。"""
    wins = {2019: 1, 2020: 1, 2021: 1, 2022: 0, 2023: 1, 2024: 1, 2025: 0}
    rows = [{"A": 2, "是否盈利": wins[y], "区间涨跌幅": 0.1, "年": y,
             "信号日期": f"{y}{i + 1:02d}01", "股票代码": "x"}
            for y in range(2019, 2026) for i in range(4)]
    return pd.DataFrame(rows)


def test_walk_forward_rolling_windows():
    """滚动前推:窗口末年 = 最小年+3 = 2022 滑到 2024;训练 = 末年往前 3 年
    (含末年),测试 = 次年;测试年不存在的窗口(2025→2026)跳过。"""
    spec = {"name": "T", "conds": [{"col": "A", "op": ">=", "value": 2}], "join": "AND"}
    wf = walk_forward(spec, _wf_df())
    assert [w["window_end"] for w in wf] == [2022, 2023, 2024]
    # 2022: 训练 2020-2022 → 8/12 胜;测试 2023 → 1.0
    assert wf[0]["train_win_rate"] == pytest.approx(8 / 12)
    assert wf[0]["test_win_rate"] == 1.0
    # 2023: 训练 2021-2023 → 8/12;测试 2024 → 1.0
    assert wf[1]["train_win_rate"] == pytest.approx(8 / 12)
    assert wf[1]["test_win_rate"] == 1.0
    # 2024: 训练 2022-2024 → 8/12;测试 2025 → 0.0
    assert wf[2]["train_win_rate"] == pytest.approx(8 / 12)
    assert wf[2]["test_win_rate"] == 0.0


def test_walk_forward_train_years_param():
    """train_years=2:首窗末年 = 最小年+2 = 2021,滑到 2024(共 4 窗)。"""
    spec = {"name": "T", "conds": [{"col": "A", "op": ">=", "value": 2}], "join": "AND"}
    wf = walk_forward(spec, _wf_df(), train_years=2)
    assert [w["window_end"] for w in wf] == [2021, 2022, 2023, 2024]
    assert wf[0]["train_win_rate"] == 1.0    # 训练 2020-2021 全胜
    assert wf[0]["test_win_rate"] == 0.0     # 测试 2022 全负


def test_sensitivity_basic():
    """单阈值 ±delta 重算全量胜率:0.9 命中 3 行 2 胜;1.1 命中 1 行 1 胜。"""
    df = pd.DataFrame({"A": [1.0, 0.9, 1.2, 0.5],
                       "是否盈利": [1, 0, 1, 0], "区间涨跌幅": [0.1] * 4,
                       "年": [2024] * 4,
                       "信号日期": [20240101 + i for i in range(4)],
                       "股票代码": ["x"] * 4})
    spec = {"name": "T", "conds": [{"col": "A", "op": ">=", "value": 1.0}], "join": "AND"}
    s = sensitivity(spec, df, delta=0.1)
    assert len(s) == 1
    r = s[0]
    assert r["col"] == "A" and r["value"] == 1.0
    assert r["win_rate_lo"] == pytest.approx(2 / 3)
    assert r["win_rate_hi"] == 1.0
    assert r["win_rate_diff"] == pytest.approx(1 / 3)
    assert spec["conds"][0]["value"] == 1.0   # 原 spec 不变


def test_sensitivity_nested_or_group():
    """敏感性递归覆盖 or_group 内阈值(前序遍历 X,A,B);spec 不变。"""
    df = pd.DataFrame({"X": [1, 1, 1, 1], "A": [1.0, 0.0, 0.0, 0.0],
                       "B": [0.0, 1.0, 0.0, 0.0],
                       "是否盈利": [1, 0, 1, 0], "区间涨跌幅": [0.1] * 4,
                       "年": [2024] * 4,
                       "信号日期": [20240101 + i for i in range(4)],
                       "股票代码": ["x"] * 4})
    spec = {"name": "T", "join": "AND",
            "conds": [{"col": "X", "op": ">=", "value": 0},
                      {"or_group": [{"col": "A", "op": ">=", "value": 1},
                                    {"col": "B", "op": ">=", "value": 1}]}]}
    s = sensitivity(spec, df, delta=0.1)
    assert [r["col"] for r in s] == ["X", "A", "B"]
    x = s[0]
    assert x["win_rate_lo"] == x["win_rate_hi"] == 0.5 and x["win_rate_diff"] == 0.0
    # A 臂:lo 0.9 命中 A=1 行 → 与 B 臂合 2 行 1 胜;hi 1.1 空 → 只剩 B 臂 1 行 0 胜
    a = s[1]
    assert a["win_rate_lo"] == pytest.approx(0.5)
    assert a["win_rate_hi"] == 0.0
    assert a["win_rate_diff"] == pytest.approx(-0.5)
    # B 臂:lo 0.9 命中 B=1 行 → 0.5;hi 1.1 空 → 只剩 A 臂 1 行 1 胜
    b = s[2]
    assert b["win_rate_lo"] == pytest.approx(0.5)
    assert b["win_rate_hi"] == 1.0
    assert b["win_rate_diff"] == pytest.approx(0.5)
    assert spec["conds"][1]["or_group"][0]["value"] == 1
    assert spec["conds"][1]["or_group"][1]["value"] == 1
