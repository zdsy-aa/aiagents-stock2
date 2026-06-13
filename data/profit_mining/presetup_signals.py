# presetup_signals.py —— 起涨前"蓄势期特征"信号库(逐bar布尔, 参数化)。
# 4类: 低波动率收敛 lowvol / 缩量 dryup / 箱体盘整 box / 筹码集中 chip。
# 纯函数: df(或获利盘数组)-> numpy bool 数组(长度n); 不足回看的bar记False。
from itertools import combinations
import numpy as np


def sig_lowvol(df, win, q):
    """收益率STD(win)跌到自身近120日q分位 = 波动收敛。"""
    ret = df["Close"].pct_change()
    v = ret.rolling(win).std()
    thr = v.rolling(120, min_periods=40).quantile(q)
    return (v <= thr).fillna(False).to_numpy()


def sig_dryup(df, win, ratio):
    """量 <= ratio*MA(量,win) = 缩量。无 Volume 列 -> 全False。"""
    if "Volume" not in df.columns:
        return np.zeros(len(df), dtype=bool)
    vol = df["Volume"]
    return (vol <= ratio * vol.rolling(win).mean()).fillna(False).to_numpy()


def sig_box(df, win, width):
    """(HHV-LLV)/LLV <= width = 窄箱体横盘。"""
    c = df["Close"]
    hhv = c.rolling(win, min_periods=win).max()
    llv = c.rolling(win, min_periods=win).min()
    rng = (hhv - llv) / (llv + 1e-9)
    return (rng <= width).fillna(False).to_numpy()


def sig_chip(profit, lo, hi):
    """获利盘 profit(numpy数组,可含NaN)在[lo,hi] = 筹码集中/超跌。
    profit=None(该股无turnover) -> 返回 None(调用方按全False处理)。"""
    if profit is None:
        return None
    p = np.asarray(profit, dtype=float)
    return (p >= lo) & (p <= hi) & ~np.isnan(p)


# L1 信号谱: (name, kind, params)。kind∈{lowvol,dryup,box,chip}。
L1_SPECS = (
    [(f"lowvol_w{w}_q{q}", "lowvol", (w, q)) for w in (10, 20, 30) for q in (0.2, 0.3)] +
    [(f"dryup_w{w}_r{r}", "dryup", (w, r)) for w in (20, 60) for r in (0.7, 0.8)] +
    [(f"box_w{w}_wd{wd}", "box", (w, wd)) for w in (20, 30) for wd in (0.10, 0.15)] +
    [("chip_50_80", "chip", (50, 80)),
     ("chip_60_85", "chip", (60, 85)),
     ("chip_deep_0_30", "chip", (0, 30))]
)


def eval_l1(spec, df, profit):
    """按 spec 算单股逐bar布尔数组。chip 类用 profit(获利盘数组或None->全False)。"""
    name, kind, params = spec
    if kind == "lowvol":
        return sig_lowvol(df, *params)
    if kind == "dryup":
        return sig_dryup(df, *params)
    if kind == "box":
        return sig_box(df, *params)
    if kind == "chip":
        s = sig_chip(profit, *params)
        return np.zeros(len(df), dtype=bool) if s is None else s
    raise ValueError(kind)


def l2_pairs(names):
    return list(combinations(names, 2))
