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
