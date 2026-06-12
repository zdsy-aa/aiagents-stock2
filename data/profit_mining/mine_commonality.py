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
