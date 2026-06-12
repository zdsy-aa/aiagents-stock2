# surface_l3.py —— L3 三指标独立榜浮出：后处理 各组方案_全部评分_*.csv，
# 筛 L3 + 算"第三条件增量价值" + 护栏 + 排序 → 独立榜 CSV + md。纯 pandas，只读。
import os, sys, glob, datetime
import pandas as pd

NUM_COLS = ["支持数", "盈利覆盖率", "非盈利覆盖率", "提升度",
            "条件内胜率", "基线胜率", "胜率增益"]


def split_conditions(plan_str):
    """方案名按 ' + ' 切成条件名列表。条件名内含 >=/<= 不受影响。"""
    return [p for p in str(plan_str).split(" + ")]


def load_scores(path):
    """读全量评分 CSV，数值列转 float。字符串列(分组/方案/层级)保持。"""
    df = pd.read_csv(path, encoding="utf-8-sig", low_memory=False)
    for c in NUM_COLS:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def build_pair_lift(l2_df):
    """单组 L2 行 → {frozenset({条件x,条件y}): 提升度}。用集合做键,无视存储顺序。"""
    d = {}
    for _, r in l2_df.iterrows():
        names = split_conditions(r["方案"])
        if len(names) == 2:
            d[frozenset(names)] = r["提升度"]
    return d


def l3_marginal(plan_str, l3_lift, pair_lift):
    """L3 三元组 → (最优两两子集 str, 子集提升度, 增量提升度)。
    增量 = L3提升度 − 三个两两子集中提升度最高者。提升度 999 视为 inf 哨兵。"""
    names = split_conditions(plan_str)
    pairs = [(names[0], names[1]), (names[0], names[2]), (names[1], names[2])]
    best_pair, best_lift = None, float("-inf")
    for x, y in pairs:
        lift = pair_lift.get(frozenset((x, y)))
        if lift is None:
            continue
        if lift > best_lift:
            best_lift, best_pair = lift, (x, y)
    if best_pair is None:
        return ("", float("nan"), float("nan"))
    subset_str = f"{best_pair[0]} + {best_pair[1]}"
    if l3_lift >= 999:
        inc = float("inf")
    elif best_lift >= 999:
        inc = float("-inf")
    else:
        inc = l3_lift - best_lift
    return (subset_str, best_lift, inc)
