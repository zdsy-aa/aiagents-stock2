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
