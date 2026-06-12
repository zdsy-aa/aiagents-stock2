# swing_samples.py —— 由 ZigZag 段生成 W=5 正样本窗口（上涨前买 / 下跌前卖）。
import zigzag_segments as Z


def windows_from_pivots(pivots, W=5):
    """拐点 → (up_windows, down_windows)。
    每个 up 段(L→H)取波谷 L 当根及前 W-1 根；down 段(H→L)取波峰 H 当根及前 W-1 根。
    段起点即对应拐点(L 或 H)。窗口边界 < 0 时头部截断。"""
    segs = Z.segments_from_pivots(pivots)
    up, down = [], []
    for start, _end, d in segs:
        win = list(range(max(0, start - (W - 1)), start + 1))
        (up if d == "up" else down).append(win)
    return up, down


def positive_windows(high, low, pct, W=5):
    """日K高低 → (up_windows, down_windows)。"""
    pivots = Z.zigzag_pivots(high, low, pct)
    return windows_from_pivots(pivots, W)
