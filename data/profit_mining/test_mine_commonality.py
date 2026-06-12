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


def test_finalize_and_rank():
    # 两个key累加计数 → 覆盖率/提升度/精确度
    counts = {
        ("A", "buy", 0.15, (20, 0.618, 0.01, 12, 26, 9)):
            [7, 10, 8, 40, 20, 1000],     # cover 0.7, rate_pos .2, rate_all .02 → lift 10
        ("A", "buy", 0.15, (10, 0.5, 0.01, 12, 26, 9)):
            [5, 10, 1, 40, 50, 1000],     # cover 0.5 → 被滤
    }
    rows = M.finalize(counts)
    assert len(rows) == 2
    kept = M.filter_rank(rows, cover_min=0.70)
    assert len(kept) == 1, kept
    r = kept[0]
    assert abs(r["coverage"] - 0.7) < 1e-9
    assert abs(r["lift"] - 10.0) < 1e-6, r["lift"]
    assert abs(r["precision"] - 8 / 20) < 1e-9
    assert r["plan"] == "A" and r["side"] == "buy" and r["pct"] == 0.15
    print("OK finalize_and_rank")


if __name__ == "__main__":
    test_count_for_signal()
    test_count_out_of_range_window()
    test_finalize_and_rank()
    print("ALL OK")
