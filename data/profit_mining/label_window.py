# label_window.py —— 固定前向窗口标签（纯函数，无未来函数泄漏到信号日之前）
# 买点盈利: 信号后 win 个交易日内 max(High)/进场价-1 >= thresh
# 卖点好卖: 信号后 win 个交易日内 min(Low)/进场价-1 <= -thresh
# 进场价=信号当日收盘(Close[i])；不足win根标 truncated。
import pandas as pd


def forward_window_label(df, i, direction, win=30, thresh=0.10):
    """返回 (label:int, extreme_ret:float, truncated:bool)。
    direction: 'buy' 用最高价算最大涨幅(MFE)；'sell' 用最低价算最大跌幅(MAE)。"""
    n = len(df)
    base = float(df["Close"].iloc[i])
    if base <= 0:
        return 0, 0.0, True
    lo, hi = i + 1, min(i + win, n - 1)
    truncated = (i + win) > (n - 1)
    if lo > hi:
        return 0, 0.0, True
    fut = df.iloc[lo:hi + 1]
    if direction == "buy":
        ext = float(fut["High"].max())
        ret = ext / base - 1.0
        label = 1 if ret >= thresh else 0
    else:
        ext = float(fut["Low"].min())
        ret = ext / base - 1.0
        label = 1 if ret <= -thresh else 0
    return label, round(ret, 6), bool(truncated)
