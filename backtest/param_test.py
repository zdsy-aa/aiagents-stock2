# backtest/param_test.py
"""参数网格测试 / 敏感性分析 / 滚动前推 / 过拟合告警(消费统一回测引擎)。

- grid_test(spec_template, param_grid, df) -> list[dict]:
    param_grid = {"col": [v1, v2, ...], ...} 的笛卡尔积;每个组合递归替换 spec
    条件(含嵌套 or_group)中同列条件的 value(深拷贝,spec_template 不可变),
    按 split_train_test(年 <= 2024 训练 / >= 2025 测试)分段回测,输出
    {"params", "train_win_rate", "test_win_rate", "n_train", "n_test",
     "overfit_flag"}。param_grid 的列未出现在任何条件中 -> ValueError(防笔误
    静默生成重复组合)。
- sensitivity(spec, df, delta=0.1) -> list[dict]:
    对 spec 中每个叶子阈值(含 or_group 内,按前序遍历序)以 value±delta 重算
    全量胜率(不切分),输出 {"col", "value", "win_rate_lo", "win_rate_hi",
    "win_rate_diff"}(win_rate_diff = hi - lo);原 spec 不变。
- walk_forward(spec, df, train_years=3) -> list[dict]:
    按年滚动前推。窗口末年从 面板最小年 + train_years(裁决:最小年+3)起滑到
    2024(dataio.TRAIN_MAX_YEAR,训练恒 <= 2024);训练 = 末年往前连续
    train_years 年(含末年),测试 = 紧接次年(面板数据覆盖到 2026,最后一窗
    测试年 = 2025 恒有数据);测试年不在面板中的窗口跳过。输出
    {"window_end", "train_win_rate", "test_win_rate"}。
- overfit_flag(train_win_rate, test_win_rate) -> bool:
    裁决阈值 |train_win_rate - test_win_rate| > 0.10(严格大于,恰好 0.10 不告警)。
"""
import copy
import itertools

import pandas as pd

from backtest.dataio import TRAIN_MAX_YEAR, split_train_test
from backtest.engine import run_backtest

OVERFIT_EPS = 0.10


def overfit_flag(train_win_rate, test_win_rate):
    """过拟合告警:训练/测试胜率差绝对值超过 0.10(裁决阈值,严格大于)。"""
    return abs(train_win_rate - test_win_rate) > OVERFIT_EPS


def _leaves(conds):
    """条件树的全部叶子条件(前序遍历;元素为原 dict 引用,可改值)。"""
    out = []
    for c in conds:
        if "or_group" in c:
            out.extend(_leaves(c["or_group"]))
        else:
            out.append(c)
    return out


def _replace_values(conds, params):
    """就地递归替换 conds(含嵌套 or_group)中 col 命中 params 的 value。

    返回命中的列名集合(用于校验 param_grid 列都存在)。
    """
    found = set()
    for c in conds:
        if "or_group" in c:
            found |= _replace_values(c["or_group"], params)
        elif c.get("col") in params:
            c["value"] = params[c["col"]]
            found.add(c["col"])
    return found


def _cartesian_combos(param_grid):
    cols = list(param_grid.keys())
    for combo in itertools.product(*(param_grid[c] for c in cols)):
        yield dict(zip(cols, combo))


def grid_test(spec_template, param_grid, df):
    """param_grid 笛卡尔积 × 分段回测,输出过拟合告警表。spec_template 不可变。"""
    train_df, test_df = split_train_test(df)
    out = []
    for params in _cartesian_combos(param_grid):
        spec = copy.deepcopy(spec_template)
        found = _replace_values(spec.get("conds") or [], params)
        missing = [c for c in params if c not in found]
        if missing:
            raise ValueError(f"param_grid 列未出现在 spec 条件中: {missing}")
        r_tr = run_backtest(spec, train_df)
        r_te = run_backtest(spec, test_df)
        out.append({
            "params": dict(params),
            "train_win_rate": r_tr["win_rate"],
            "test_win_rate": r_te["win_rate"],
            "n_train": r_tr["n"],
            "n_test": r_te["n"],
            "overfit_flag": overfit_flag(r_tr["win_rate"], r_te["win_rate"]),
        })
    return out


def sensitivity(spec, df, delta=0.1):
    """对 spec 的每个叶子阈值以 value±delta 重算全量胜率,输出胜率差。"""
    leaves = _leaves(spec.get("conds") or [])
    out = []
    for i, leaf in enumerate(leaves):
        col = leaf.get("col")
        value = leaf.get("value")
        if col is None or value is None:
            continue
        s_lo = copy.deepcopy(spec)
        _leaves(s_lo["conds"])[i]["value"] = value - delta
        s_hi = copy.deepcopy(spec)
        _leaves(s_hi["conds"])[i]["value"] = value + delta
        win_lo = run_backtest(s_lo, df)["win_rate"]
        win_hi = run_backtest(s_hi, df)["win_rate"]
        out.append({"col": col, "value": value,
                    "win_rate_lo": win_lo, "win_rate_hi": win_hi,
                    "win_rate_diff": win_hi - win_lo})
    return out


def walk_forward(spec, df, train_years=3):
    """按年滚动前推:训练 = 窗口末年前连续 train_years 年(含末年,恒 <= 2024),
    测试 = 紧接次年;窗口末年从 面板最小年 + train_years 滑到 2024。"""
    yr = pd.to_numeric(df["年"], errors="coerce")
    valid = yr.notna()
    yr = yr[valid]
    if len(yr) == 0:
        return []
    year_set = set(yr.astype(int).unique())
    min_year = int(yr.min())
    out = []
    for window_end in range(min_year + train_years, TRAIN_MAX_YEAR + 1):
        test_year = window_end + 1
        if test_year not in year_set:
            continue
        lo = window_end - train_years + 1
        train_df = df[valid & (yr >= lo) & (yr <= window_end)]
        test_df = df[valid & (yr == test_year)]
        r_tr = run_backtest(spec, train_df)
        r_te = run_backtest(spec, test_df)
        out.append({"window_end": int(window_end),
                    "train_win_rate": r_tr["win_rate"],
                    "test_win_rate": r_te["win_rate"]})
    return out


__all__ = ["grid_test", "sensitivity", "walk_forward", "overfit_flag",
           "OVERFIT_EPS"]
