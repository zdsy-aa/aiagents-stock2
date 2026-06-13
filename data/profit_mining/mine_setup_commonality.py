# mine_setup_commonality.py —— 蓄势期特征共性挖掘(buy向/仅zz6, L1单+L2两两)。
# 复用 mine_presetup 的起涨前蓄势窗口 + 段级覆盖率; 信号库=presetup_signals(蓄势特征)。
import os, sys, time
from collections import defaultdict
import numpy as np
import pandas as pd

import swing_samples as SW
import presetup_signals as PSig
from mine_commonality import finalize, filter_rank, _load_kline, _universe
from turnover_features import chip_series

PCT = 0.06
NEAR_N = 20
FAR = 7

_TURN = {}   # {code: pd.Series(turn% , index=datetime)}; fork前填,COW共享不pickle


def _win_arrays(windows, n):
    st = np.fromiter((w[0] for w in windows), dtype=np.int64, count=len(windows))
    en = np.fromiter((w[-1] for w in windows), dtype=np.int64, count=len(windows))
    np.clip(st, 0, n - 1, out=st); np.clip(en, 0, n - 1, out=en)
    return st, en


def accumulate_setup(df, code, turn=None):
    """单股 -> counts dict key=("ALL",level,"buy",PCT,name) val=[seg_hit,seg_total,
    fires_pos,bars_pos,fires_all,n]。level∈{L1,L2}; name=信号名(L2='a & b')。
    turn=该股换手率Series(None则chip类全False)。"""
    out = defaultdict(lambda: [0, 0, 0, 0, 0, 0])
    n = len(df)
    if n == 0:
        return dict(out)
    piv = SW.Z.zigzag_pivots(df["High"].tolist(), df["Low"].tolist(), PCT)
    wins = SW.presetup_windows_from_pivots(piv, NEAR_N, FAR)
    if not wins:
        return dict(out)
    st, en = _win_arrays(wins, n)
    seg_total = len(wins)

    profit = None
    if turn is not None:
        try:
            profit = chip_series(df, turn)["获利盘"].to_numpy(float)
        except Exception:
            profit = None

    l1_arr = {}
    for spec in PSig.L1_SPECS:
        l1_arr[spec[0]] = PSig.eval_l1(spec, df, profit).astype(bool)

    def tally(level, name, sig):
        csum = np.concatenate(([0], np.cumsum(sig, dtype=np.int64)))
        fires_all = int(sig.sum())
        wf = csum[en + 1] - csum[st]
        seg_hit = int(np.count_nonzero(wf)); fires_pos = int(wf.sum())
        bars_pos = int((en - st + 1).sum())   # 近窗口按构造重叠->bars_pos重复计:coverage精确,lift近似
        a = out[("ALL", level, "buy", PCT, name)]
        a[0] += seg_hit; a[1] += seg_total; a[2] += fires_pos
        a[3] += bars_pos; a[4] += fires_all; a[5] += n

    for name, arr in l1_arr.items():
        tally("L1", name, arr)
    for a, b in PSig.l2_pairs(list(l1_arr.keys())):
        tally("L2", f"{a} & {b}", l1_arr[a] & l1_arr[b])
    return dict(out)


def merge_counts(dst, src):
    for k, v in src.items():
        acc = dst[k]
        for i in range(6):
            acc[i] += v[i]
