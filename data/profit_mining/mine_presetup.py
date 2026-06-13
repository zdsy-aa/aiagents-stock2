# mine_presetup.py —— 起涨前蓄势窗口共性挖掘(buy向/仅zz6)。
# 窗口=每个>=6%上涨段起涨前的蓄势期(近=上一涨段+下降段/远=前7天,含波谷L)。
# 段级覆盖率: 窗口内任一bar触发即该段命中。复用 mine_commonality 的 finalize/写榜。
import os, sys, csv as _csv, time
from collections import defaultdict
import numpy as np

import swing_samples as SW
import param_signals as PS
from mine_commonality import (finalize, filter_rank, _write_board, _expand_params,
                              _load_kline, _universe)

PCT = 0.06
NEAR_N = 20
FAR = 7


def _win_arrays(windows, n):
    st = np.fromiter((w[0] for w in windows), dtype=np.int64, count=len(windows))
    en = np.fromiter((w[-1] for w in windows), dtype=np.int64, count=len(windows))
    np.clip(st, 0, n - 1, out=st); np.clip(en, 0, n - 1, out=en)
    return st, en


def accumulate_presetup(df, pct=PCT, near_n=NEAR_N, far=FAR):
    """单股 -> counts dict key=("ALL",plan,"buy",pct,params) val=[seg_hit,seg_total,
    fires_pos,bars_pos,fires_all,n]。窗口=presetup(buy向)。"""
    out = defaultdict(lambda: [0, 0, 0, 0, 0, 0])
    n = len(df)
    if n == 0:
        return dict(out)
    piv = SW.Z.zigzag_pivots(df["High"].tolist(), df["Low"].tolist(), pct)
    wins = SW.presetup_windows_from_pivots(piv, near_n, far)
    if not wins:
        return dict(out)
    st, en = _win_arrays(wins, n)
    seg_total = len(wins)
    macd_cache, fib_cache, bbi_cache = {}, {}, {}

    def tally(plan, params, sig):
        csum = np.concatenate(([0], np.cumsum(sig, dtype=np.int64)))
        fires_all = int(sig.sum())
        wf = csum[en + 1] - csum[st]            # 每窗口命中bar数
        seg_hit = int(np.count_nonzero(wf)); fires_pos = int(wf.sum())
        bars_pos = int((en - st + 1).sum())     # 近窗口可能重叠,bars_pos为窗口求和(lift近似,coverage精确)
        a = out[("ALL", plan, "buy", pct, params)]
        a[0] += seg_hit; a[1] += seg_total; a[2] += fires_pos
        a[3] += bars_pos; a[4] += fires_all; a[5] += n

    for params in PS.PLAN_A_GRID:
        N, r, b, f, s, sg = params
        m = fib_cache.get((N, r, b))
        if m is None:
            m = PS.fib_support_hold(df, N, r, b).to_numpy(); fib_cache[(N, r, b)] = m
        mc = macd_cache.get((f, s, sg))
        if mc is None:
            mc = PS.macd_golden(df, f, s, sg).to_numpy(); macd_cache[(f, s, sg)] = mc
        tally("A", params, m & mc)
    for params in PS.PLAN_B_GRID:
        periods, form, f, s, sg = params
        bb = bbi_cache.get((periods, form))
        if bb is None:
            bb = PS._bbi_form(df, periods, form, "buy").to_numpy(); bbi_cache[(periods, form)] = bb
        mc = macd_cache.get((f, s, sg))
        if mc is None:
            mc = PS.macd_golden(df, f, s, sg).to_numpy(); macd_cache[(f, s, sg)] = mc
        tally("B", params, bb & mc)
    return dict(out)


def merge_counts(dst, src):
    for k, v in src.items():
        a = dst[k]
        for i in range(6):
            a[i] += v[i]
