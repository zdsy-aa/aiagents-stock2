# zigzag_segments.py —— ZigZag 摆动切段：日K高低 → 拐点 → 上涨/下跌段。纯计算。
from __future__ import annotations


def zigzag_pivots(high, low, pct):
    """ZigZag 拐点。high/low 等长序列(时间升序)，pct 反向摆动确认阈值(0.15=15%)。
    返回 [(idx, kind)]，kind ∈ {"L","H"}，时间升序且方向交替。"""
    n = len(high)
    if n == 0:
        return []
    h = list(high); lo = list(low)
    pivots = []
    trend = 0                      # +1 上行寻顶 / -1 下行寻底 / 0 未定
    hi_v, hi_i = h[0], 0
    lo_v, lo_i = lo[0], 0
    moved = False                  # 自上次重置后候选极值是否被刷新过
    for i in range(1, n):
        if trend > 0:
            if h[i] > hi_v:
                hi_v, hi_i = h[i], i
                moved = True
            elif lo[i] <= hi_v * (1 - pct):
                pivots.append((hi_i, "H")); trend = -1
                lo_v, lo_i = lo[i], i
                moved = False
        elif trend < 0:
            if lo[i] < lo_v:
                lo_v, lo_i = lo[i], i
                moved = True
            elif h[i] >= lo_v * (1 + pct):
                pivots.append((lo_i, "L")); trend = 1
                hi_v, hi_i = h[i], i
                moved = False
        else:
            if h[i] > hi_v:
                hi_v, hi_i = h[i], i
            if lo[i] < lo_v:
                lo_v, lo_i = lo[i], i
            if h[i] >= lo_v * (1 + pct):
                pivots.append((lo_i, "L")); trend = 1
                hi_v, hi_i = h[i], i
                moved = False
            elif lo[i] <= hi_v * (1 - pct):
                pivots.append((hi_i, "H")); trend = -1
                lo_v, lo_i = lo[i], i
                moved = False
    # 末尾若候选极值在最后一次重置后又被刷新过，补一个尾部拐点
    if moved:
        if trend > 0:
            pivots.append((hi_i, "H"))
        elif trend < 0:
            pivots.append((lo_i, "L"))
    return pivots


def segments_from_pivots(pivots):
    """相邻拐点 → 段。返回 [(start_idx, end_idx, direction)]，
    direction: "up"(L→H) / "down"(H→L)。非交替对跳过。"""
    segs = []
    for (i0, k0), (i1, k1) in zip(pivots, pivots[1:]):
        if k0 == "L" and k1 == "H":
            segs.append((i0, i1, "up"))
        elif k0 == "H" and k1 == "L":
            segs.append((i0, i1, "down"))
    return segs
