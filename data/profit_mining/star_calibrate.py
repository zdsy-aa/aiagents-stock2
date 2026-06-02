# star_calibrate.py —— 阶段一：全历史1买信号回测"合成分→样本外胜率"，
# 给核心/精选两层各自定固定星级阈值(诚实降档)，产出 star_thresholds.json + 验证报告。
# 运行(宿主机即可，纯标准库)：
#   cd /home/tdxback/aiagents-stock/data/profit_mining
#   PM_DIR=. REPORT_DIR=/home/tdxback/report python3 star_calibrate.py
import os
import csv
import json
import datetime

PM_DIR = os.getenv("PM_DIR", "/app/data/profit_mining")
FEATURES = os.path.join(PM_DIR, "signal_features.csv")
THRESH_OUT = os.path.join(PM_DIR, "star_thresholds.json")
REPORT_DIR = os.getenv("REPORT_DIR", PM_DIR)

WIN_THRESH = 4.0
BIGRISE_THRESH = 10.0
TRAIN_END = "2023-12-31"
OOS_START, OOS_END = "2024-01-01", "2025-10-31"
MIN_BUCKET_N = 200
MAX_STARS = 5

BINARY_FEATS = ["极限抄底", "中枢极限底", "中枢底部回升"]


def _f(v, default=0.0):
    """宽松转 float：空串/None/非数字字符串 → default；'nan'/'inf' 视为合法浮点透传。"""
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def is_trap(row):
    """陷阱(精选层失效)：大盘多头 或 相对强弱>=0。复刻 daily_watchlist 的 trap 判定。
    相对强弱 缺失/空 → NaN（nan>=0 为 False，与 daily_watchlist 的 pd.notna 守卫一致），不判陷阱。"""
    return _f(row.get("大盘多头")) == 1 or _f(row.get("相对强弱"), default=float("nan")) >= 0


def reconstruct_tier(row):
    """复刻 daily_watchlist 层级：仅1买生效；陷阱→None；量能金叉→核心，否则精选。
    返回裸标签 '核心'/'精选'（不含★，供统计分组；展示用的★标签在 daily_watchlist）。"""
    if row.get("买点类型") != "1买":
        return None
    if is_trap(row):
        return None
    return "核心" if _f(row.get("量能金叉")) == 1 else "精选"
