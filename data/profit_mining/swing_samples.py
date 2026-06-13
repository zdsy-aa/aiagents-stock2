# swing_samples.py —— 由 ZigZag 段生成正样本窗口（起涨/起跌初期，拐点后 fwd 根）。
import zigzag_segments as Z


def windows_from_pivots(pivots, fwd=4):
    """拐点 → (up_windows, down_windows)。
    up 段(L→H)：买样本 = 波谷 L 当根及其后 fwd 根 [L, L+fwd]，截到段终点 H 为止。
    down 段(H→L)：卖样本 = 波峰 H 当根及其后 fwd 根 [H, H+fwd]，截到段终点 L 为止。
    含拐点本身共 fwd+1 根（除非段长不足而被段终点截短）。"""
    segs = Z.segments_from_pivots(pivots)
    up, down = [], []
    for start, end, d in segs:
        last = min(start + fwd, end)        # 不越过该段终点(避免漏进反向段)
        win = list(range(start, last + 1))
        (up if d == "up" else down).append(win)
    return up, down


def positive_windows(high, low, pct, fwd=4):
    """日K高低 → (up_windows, down_windows)。"""
    pivots = Z.zigzag_pivots(high, low, pct)
    return windows_from_pivots(pivots, fwd)


def presetup_windows_from_pivots(pivots, near_n=20, far=7, tight_k=None):
    """每个上涨段(L->H)的"起涨前蓄势窗口"(buy向, 含波谷L, 截止于L无泄漏)。
    tight_k 给定: 紧窗口=[max(0,L-tight_k), L](忽略近/远自适应)。
    tight_k=None(默认): 近(上一涨段终点H_prev到L的间隔 gap<=near_n)->[上一涨段起点L_prev, L];
    远(gap>near_n 或无上一涨段)->[L-far, L]。返回 list[list[int]](升序bar索引)。"""
    segs = Z.segments_from_pivots(pivots)
    wins = []
    prev_up = None                       # (L_prev_idx, H_prev_idx)
    for start, end, d in segs:
        if d != "up":
            continue
        L = start
        if tight_k is not None:
            lo = max(0, L - tight_k)
        elif prev_up is not None and (L - prev_up[1]) <= near_n:
            lo = prev_up[0]              # 上一涨段起点
        else:
            lo = max(0, L - far)
        wins.append(list(range(lo, L + 1)))   # 含L
        prev_up = (start, end)
    return wins
