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
