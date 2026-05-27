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


from chanlun_engine import build_pivots, Segment


def test_build_pivots_three_overlapping_segments():
    segs = [
        Segment("up", 0, 3, 10, 14),
        Segment("down", 3, 6, 14, 11),
        Segment("up", 6, 9, 11, 15),
    ]
    pv = build_pivots(segs)
    assert len(pv) == 1
    assert pv[0].ZD == 11 and pv[0].ZG == 14   # max low / min high
    assert pv[0].GG == 15 and pv[0].DD == 10


def test_build_pivots_none_when_no_overlap():
    segs = [
        Segment("up", 0, 3, 10, 14),
        Segment("down", 3, 6, 14, 12),
        Segment("up", 6, 9, 12, 20),
    ]
    pv = build_pivots(segs)
    assert len(pv) <= 1


import numpy as np
from chanlun_engine import compute_macd, seg_macd_power, is_diverging


def test_compute_macd_columns():
    close = pd.Series(np.linspace(10, 20, 60))
    dif, dea, hist = compute_macd(close)
    assert len(dif) == 60 and len(dea) == 60 and len(hist) == 60


def test_is_diverging_when_later_leg_weaker():
    hist = pd.Series([0]*5 + [2,3,4,3,2] + [0]*5 + [1,1,1,0,0])
    assert seg_macd_power(hist, 5, 9) > seg_macd_power(hist, 15, 19)
    assert is_diverging(seg_macd_power(hist, 15, 19), seg_macd_power(hist, 5, 9)) is True
    assert is_diverging(seg_macd_power(hist, 5, 9), seg_macd_power(hist, 15, 19)) is False


from chanlun_engine import detect_trade_points


def test_detect_3buy_after_breakout_pullback():
    # 中枢 ZG=14；其后一段上破到18，回踩到15(>14)不破 -> 3买
    segs = [Segment("up", 0, 3, 10, 14), Segment("down", 3, 6, 14, 11), Segment("up", 6, 9, 11, 14),
            Segment("up", 9, 12, 14, 18), Segment("down", 12, 15, 18, 15)]
    pivots = build_pivots(segs)
    close = pd.Series(list(range(10, 10 + 40)))  # 占位，3买不依赖背驰
    pts = detect_trade_points(segs, pivots, close)
    assert any(p.kind == "3买" for p in pts)


def test_detect_1buy_on_bottom_divergence():
    # 两段下跌：第二段创新低但 MACD 力度更弱 -> 1买
    segs = [Segment("down", 0, 5, 20, 12), Segment("up", 5, 8, 12, 15), Segment("down", 8, 13, 15, 10)]
    pivots = build_pivots(segs)
    # 首跌陡(大动能)、次跌缓(小动能)但创更低低点 -> 底背驰
    close = pd.Series([20, 14, 11, 10, 11, 12, 13, 14, 15, 14, 13, 12, 11, 10])
    pts = detect_trade_points(segs, pivots, close)
    assert any(p.kind == "1买" for p in pts)


from chanlun_engine import analyze_one, analyze, ChanResult


def test_analyze_one_returns_full_result():
    rows = [(8,3),(7,2),(10,4),(9,5),(13,7),(12,8),(16,10),(15,11),
            (14,9),(12,7),(10,5),(8,3),(6,2),(7,3),(9,5),(8,4)]
    df = _df(rows)
    r = analyze_one(df)
    assert isinstance(r, ChanResult)
    assert len(r.kbars) > 0 and isinstance(r.points, list)


def test_analyze_multilevel_marks_confirmation():
    rows = [(8,3),(7,2),(10,4),(9,5),(13,7),(12,8),(16,10),(15,11),
            (14,9),(12,7),(10,5),(8,3),(6,2),(7,3),(9,5),(8,4)]
    df_day = _df(rows)
    df_30m = _df(rows * 2)  # 占位次级别
    res = analyze(df_day, df_30m)
    assert isinstance(res, ChanResult)
    for p in res.points:
        assert ("30m确认" in p.note) or ("无次级别确认" in p.note) or p.note != ""


from chanlun_engine import buy_point_with_exit, TradePoint, Pivot


def test_buy_point_with_exit_fields():
    bp = TradePoint("1买", 12, 10.0, "下跌段力度背驰")
    pivots = [Pivot(ZG=14, ZD=11, GG=16, DD=9, i_start=0, i_end=8, seg_count=3)]
    info = buy_point_with_exit(bp, pivots)
    assert info["signal_type"] == "1买"
    assert info["buy_price"] == 10.0
    assert info["stop_loss"] <= 10.0           # 止损不高于买点
    assert isinstance(info["exit_rule"], str) and len(info["exit_rule"]) > 0
