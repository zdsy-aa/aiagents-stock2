# group_dims.py —— 分维度分组工具：三分位归桶 / 板块·市值标签 / vol20 / 按vol拆窗 / 读buckets。
import json


SIZE_LABELS = ("小盘", "中盘", "大盘")
VOL_LABELS = ("低", "中", "高")


def bucketize(value, cuts):
    """三分位归桶：cuts=[c1,c2] → 0(<c1) / 1([c1,c2)) / 2(>=c2)。左闭右开，最高桶含上界。"""
    if value < cuts[0]:
        return 0
    if value < cuts[1]:
        return 1
    return 2


def board_group(board):
    """events 板块字段 → '板块=X'；空/None → None(不分组)。"""
    return f"板块={board}" if board else None


def size_group(mktcap, cuts):
    """总市值 → '市值=小/中/大盘'；mktcap 缺或无 cuts → None(不参与市值分组)。"""
    if mktcap is None or cuts is None:
        return None
    return f"市值={SIZE_LABELS[bucketize(mktcap, cuts)]}"


def vol20_series(df, win=20):
    """逐 bar 波动率 vol20 = rolling(win) 均值 of (High-Low)/Close；min_periods=1。返回 numpy。"""
    amp = (df["High"] - df["Low"]) / df["Close"]
    return amp.rolling(win, min_periods=1).mean().to_numpy()


def split_windows_by_vol(windows, vol20, cuts):
    """按拐点(window[0]) 的 vol20 把窗口分到 {0:低,1:中,2:高}。返回 dict[int,list]。"""
    out = {0: [], 1: [], 2: []}
    for w in windows:
        out[bucketize(vol20[w[0]], cuts)].append(w)
    return out


def load_buckets(path):
    """读 group_buckets.json → dict。"""
    with open(path, encoding="utf-8") as f:
        return json.load(f)
