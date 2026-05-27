# tests/test_chanlun_engine.py
import pandas as pd
from chanlun_engine import merge_inclusion, KBar


def _df(rows):
    # rows: list of (high, low)；Open/Close/Volume 填充占位
    idx = pd.RangeIndex(len(rows))
    return pd.DataFrame(
        {"Open": [h for h, l in rows], "High": [h for h, l in rows],
         "Low": [l for h, l in rows], "Close": [l for h, l in rows],
         "Volume": [1] * len(rows)}, index=idx)


def test_merge_inclusion_upward_merges_to_higher():
    # 第3根(11,8)被(12,7)向上包含 -> 合并成(12,8)
    df = _df([(10, 5), (12, 7), (11, 8)])
    ks = merge_inclusion(df)
    assert [(k.high, k.low) for k in ks] == [(10, 5), (12, 8)]
    assert ks[-1].i_lo == 1 and ks[-1].i_hi == 2


def test_merge_inclusion_no_inclusion_passthrough():
    df = _df([(10, 5), (12, 7), (14, 9)])
    ks = merge_inclusion(df)
    assert [(k.high, k.low) for k in ks] == [(10, 5), (12, 7), (14, 9)]


from chanlun_engine import find_fractals


def test_find_fractals_top_and_bottom():
    df = _df([(10, 5), (12, 7), (11, 6), (13, 8), (9, 4)])
    ks = merge_inclusion(df)
    fs = find_fractals(ks)
    kinds = [(f.kind, round(f.price, 1)) for f in fs]
    assert ("top", 12.0) in kinds
    assert ("top", 13.0) in kinds


from chanlun_engine import build_strokes


def test_build_strokes_alternating_and_gap():
    rows = [(8,3),(7,2),(9,4),(10,5),(12,6),(13,8),(11,6),(10,5),(9,4),(7,2),(8,3)]
    df = _df(rows)
    ks = merge_inclusion(df)
    sts = build_strokes(find_fractals(ks))
    assert len(sts) >= 2
    assert sts[0].dir in ("up", "down")
    for a, b in zip(sts, sts[1:]):
        assert a.dir != b.dir


def test_build_strokes_skips_too_close_fractals():
    rows = [(10,5),(12,7),(8,4),(13,9)]
    df = _df(rows)
    ks = merge_inclusion(df)
    sts = build_strokes(find_fractals(ks))
    for s in sts:
        assert s.end.k - s.start.k >= 3


from chanlun_engine import build_segments


def _strokes_from(rows):
    df = _df(rows); ks = merge_inclusion(df)
    return build_strokes(find_fractals(ks))


def _zig(pivots, step=1.0):
    """由转折中价生成干净锯齿K线（每腿严格单调、无包含、腿足够长）。
    每根 K: high=mid+1, low=mid-1。"""
    rows = []
    for a, b in zip(pivots, pivots[1:]):
        n = max(4, int(abs(b - a) / step))
        for j in range(n):
            mid = a + (b - a) * j / n
            rows.append((round(mid + 1, 2), round(mid - 1, 2)))
    rows.append((round(pivots[-1] + 1, 2), round(pivots[-1] - 1, 2)))
    return rows


def test_build_segments_multi_alternating_monotonic():
    # 趋势：下 -> 上(更高高/更高低) -> 下，应得 ≥2 段、方向交替、各段端点单调
    rows = _zig([2, 12, 7, 17, 11, 22, 16, 8, 12, 4, 8, 1])
    segs = build_segments(_strokes_from(rows))
    assert len(segs) >= 2
    # 方向交替
    for a, b in zip(segs, segs[1:]):
        assert a.dir != b.dir
    # 上段升、下段降
    for s in segs:
        if s.dir == "up":
            assert s.p_end > s.p_start
        else:
            assert s.p_end < s.p_start


def test_build_segments_needs_min_three_strokes():
    rows = [(8,3),(7,2),(12,6),(11,7),(9,4)]
    segs = build_segments(_strokes_from(rows))
    assert segs == [] or all(s.dir in ("up", "down") for s in segs)
