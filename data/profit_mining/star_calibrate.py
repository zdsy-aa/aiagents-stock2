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


def bin_volratio(x):
    """量比分箱：>=2 →2，>=1.3 →1，否则 0（与 daily_watchlist 的 1.3 阈值一致）。"""
    v = _f(x)
    return 2 if v >= 2 else (1 if v >= 1.3 else 0)


def bin_relstr(x):
    """相对强弱分箱(越低越超跌、档位越高；非陷阱已保证 <0)：<=-5 →2，<=-2 →1，否则 0。"""
    v = _f(x)
    return 2 if v <= -5 else (1 if v <= -2 else 0)


CONT_FEATS = {"量比": bin_volratio, "相对强弱": bin_relstr}


def feature_values(row):
    """该信号每个打分特征的档位值（binary 0/1；连续 0/1/2）。"""
    fv = {k: _f(row.get(k)) for k in BINARY_FEATS}
    for k, fn in CONT_FEATS.items():
        fv[k] = fn(row.get(k))
    return fv


def fit_weights(rows, feat_names):
    """rows: [{"fv": {feat: level}, "win": 0/1}]。
    权重 = mean(win | level>0) − mean(win | level==0)。无对照组则 0。"""
    weights = {}
    for f in feat_names:
        on = [r["win"] for r in rows if r["fv"].get(f, 0) > 0]
        off = [r["win"] for r in rows if r["fv"].get(f, 0) == 0]
        if not on or not off:
            weights[f] = 0.0
        else:
            weights[f] = sum(on) / len(on) - sum(off) / len(off)
    return weights


def score_row(fv, weights):
    """合成分 = Σ 权重·档位值。"""
    return sum(weights.get(f, 0.0) * lvl for f, lvl in fv.items())


def assign_bucket(score, cuts):
    """按升序切点 cuts 返回档号 0..len(cuts)。score>=cuts[i] 则进更高档。"""
    b = 0
    for c in cuts:
        if score >= c:
            b += 1
        else:
            break
    return b


def _equal_freq_cuts(scored, k):
    """对已按 score 升序排好的 scored 取 k 等频切点(长度 k-1)。"""
    n = len(scored)
    return [scored[int(round(n * i / k))][0] for i in range(1, k)]


def _bucketize(scored, cuts):
    """按 cuts 把 scored 分进 len(cuts)+1 个桶(0=最低分..末=最高分)。"""
    buckets = [[] for _ in range(len(cuts) + 1)]
    for row in scored:
        buckets[assign_bucket(row[0], cuts)].append(row)
    return buckets


def fit_buckets(scored, max_stars=MAX_STARS, min_n=MIN_BUCKET_N):
    """scored: [(score, win, bigwin)] 按 score 升序。
    从 max_stars 往下试，找"每档>=min_n 且 训练胜率单调不降"的最大档数。
    返回 (n_stars, cuts, stats)；stats[i]={"star":i+1,"n":..,"train_win":..}。
    桶号低=分低=低星，故 star = 桶号+1。"""
    n = len(scored)
    for k in range(max_stars, 1, -1):
        if n < min_n * k:
            continue
        cuts = _equal_freq_cuts(scored, k)
        buckets = _bucketize(scored, cuts)
        if any(len(b) < min_n for b in buckets):
            continue
        wr = [sum(w for _, w, _ in b) / len(b) for b in buckets]
        if all(wr[i] <= wr[i + 1] + 1e-9 for i in range(len(wr) - 1)):
            stats = [{"star": i + 1, "n": len(b), "train_win": wr[i]}
                     for i, b in enumerate(buckets)]
            return k, cuts, stats
    wr0 = sum(w for _, w, _ in scored) / max(n, 1)
    return 1, [], [{"star": 1, "n": n, "train_win": wr0}]


def eval_buckets(scored, cuts):
    """样本外评估：返回各档 n / oos_win(>=4%) / oos_bigrise(>=10%)。空档为 None。"""
    buckets = _bucketize(scored, cuts)
    out = []
    for i, b in enumerate(buckets):
        nb = len(b)
        out.append({
            "star": i + 1,
            "n": nb,
            "oos_win": (sum(w for _, w, _ in b) / nb) if nb else None,
            "oos_bigrise": (sum(g for _, _, g in b) / nb) if nb else None,
        })
    return out
