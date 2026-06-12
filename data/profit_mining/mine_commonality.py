# mine_commonality.py —— 方案A/B 涨跌前期共性挖掘：逐股累加→覆盖率/提升度/精确度→报告。
import numpy as np


def count_for_signal(signal, windows):
    """signal: bool序列(len=n_bars)；windows: list[list[int]] (每段的W=5正样本bar索引)。
    返回 (seg_hit, seg_total, fires_pos, bars_pos, fires_all, bars_all)。
    seg_hit: 窗口内任一根信号True则该段命中；bars_pos: 所有窗口索引去重后的根数；
    fires_pos: 正样本根里信号True数；fires_all/bars_all: 全体。"""
    sig = np.asarray(signal, dtype=bool)
    n = len(sig)
    seg_total = len(windows)
    seg_hit = 0
    pos_idx = set()
    for w in windows:
        idx = [i for i in w if 0 <= i < n]
        if any(bool(sig[i]) for i in idx):
            seg_hit += 1
        pos_idx.update(idx)
    pos_idx = sorted(pos_idx)
    bars_pos = len(pos_idx)
    fires_pos = int(sum(bool(sig[i]) for i in pos_idx))
    fires_all = int(sig.sum())
    bars_all = n
    return seg_hit, seg_total, fires_pos, bars_pos, fires_all, bars_all


# key = (plan, side, pct, paramtuple)；paramtuple: A=(N,ratio,band,f,s,sig) B=(periods,f,s,sig)
def finalize(counts):
    """counts(已跨股累加) → list[dict] 含 coverage/lift/precision 等。"""
    rows = []
    for (plan, side, pct, params), c in counts.items():
        seg_hit, seg_total, fires_pos, bars_pos, fires_all, bars_all = c
        coverage = seg_hit / seg_total if seg_total else 0.0
        rate_pos = fires_pos / bars_pos if bars_pos else 0.0
        rate_all = fires_all / bars_all if bars_all else 0.0
        lift = rate_pos / rate_all if rate_all > 0 else float("inf")
        precision = fires_pos / fires_all if fires_all else 0.0
        rows.append({"plan": plan, "side": side, "pct": pct, "params": params,
                     "seg_hit": seg_hit, "seg_total": seg_total,
                     "coverage": coverage, "rate_all": rate_all,
                     "lift": lift, "precision": precision})
    return rows


def filter_rank(rows, cover_min=0.70):
    """筛 coverage≥门槛 且 rate_all>0(剔除退化/哪都不亮)，按提升度降序。"""
    keep = [r for r in rows
            if r["seg_total"] > 0 and r["coverage"] >= cover_min and r["rate_all"] > 0]
    return sorted(keep, key=lambda r: r["lift"], reverse=True)


import swing_samples as SW
import param_signals as PS
from collections import defaultdict

DEFAULT_PCTS = (0.10, 0.15, 0.20)


def accumulate_stock(df, pcts=DEFAULT_PCTS, W=5):
    """单股 → 计数dict key=(plan,side,pct,params) val=[6元累计]。
    df 需含 High/Low/Close 列、时间升序。"""
    out = defaultdict(lambda: [0, 0, 0, 0, 0, 0])
    high = df["High"].tolist(); low = df["Low"].tolist()
    for pct in pcts:
        up_win, down_win = SW.positive_windows(high, low, pct, W)
        for side, windows in (("buy", up_win), ("sell", down_win)):
            if not windows:
                continue
            for params in PS.PLAN_A_GRID:
                sig = PS.plan_a_signal(df, *params, side=side).to_numpy()
                _merge(out[("A", side, pct, params)], count_for_signal(sig, windows))
            for params in PS.PLAN_B_GRID:
                sig = PS.plan_b_signal(df, *params, side=side).to_numpy()
                _merge(out[("B", side, pct, params)], count_for_signal(sig, windows))
    return dict(out)


def _merge(acc, c):
    for i in range(6):
        acc[i] += c[i]


def merge_counts(dst, src):
    """跨股合并：把 src(单股dict) 累加进 dst(defaultdict)。"""
    for k, v in src.items():
        a = dst[k]
        for i in range(6):
            a[i] += v[i]
