# test_mine_commonality.py —— 计数与聚合测试
import numpy as np
import mine_commonality as M


def test_count_for_signal():
    # 8根，信号在 idx 3,7 触发；窗口[[1,2,3],[5,6]]
    sig = [False, False, False, True, False, False, False, True]
    windows = [[1, 2, 3], [5, 6]]
    seg_hit, seg_total, fires_pos, bars_pos, fires_all, bars_all = \
        M.count_for_signal(sig, windows)
    assert seg_total == 2
    assert seg_hit == 1                 # 仅窗口1命中(idx3)
    assert bars_pos == 5                # {1,2,3,5,6}
    assert fires_pos == 1               # idx3 在正样本，idx7 不在
    assert fires_all == 2
    assert bars_all == 8
    print("OK count_for_signal")


def test_count_out_of_range_window():
    sig = [True, False, False]
    windows = [[-1, 0]]                  # -1 越界忽略
    seg_hit, seg_total, fires_pos, bars_pos, fires_all, bars_all = \
        M.count_for_signal(sig, windows)
    assert seg_hit == 1 and bars_pos == 1 and fires_pos == 1
    print("OK count_out_of_range")


if __name__ == "__main__":
    test_count_for_signal()
    test_count_out_of_range_window()
    print("ALL OK")
