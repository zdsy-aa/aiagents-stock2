"""缠论图解：未来条件反推 / 未来交易日推算 / 画图冒烟。"""
import pandas as pd

from chanlun_engine import ChanResult, Pivot, TradePoint, Segment
from chanlun_chart_ui import forward_conditions, _next_trading_days


def _result(pivots=None, points=None, segments=None):
    return ChanResult(kbars=[], fractals=[], strokes=[],
                      segments=segments or [], pivots=pivots or [], points=points or [])


def _df(n=80):
    idx = pd.bdate_range("2026-01-01", periods=n)
    base = list(range(10, 10 + n))
    return pd.DataFrame({"Open": base, "High": [x + 0.5 for x in base],
                         "Low": [x - 0.5 for x in base], "Close": base,
                         "Volume": [1000] * n}, index=idx)


def test_forward_3buy_3sell_from_pivot():
    r = _result(pivots=[Pivot(ZG=12.0, ZD=10.0, GG=13.0, DD=9.0, i_start=5, i_end=20, seg_count=3)])
    conds = {c["signal"]: c for c in forward_conditions(r, _df())}
    assert conds["3买"]["level"] == 12.0
    assert conds["3卖"]["level"] == 10.0


def test_forward_no_pivot_no_3buy():
    conds = {c["signal"]: c for c in forward_conditions(_result(), _df())}
    assert "3买" not in conds and "3卖" not in conds


def test_forward_2buy_from_last_one_buy():
    r = _result(points=[TradePoint("1买", 30, 9.3, "背驰")])
    conds = {c["signal"]: c for c in forward_conditions(r, _df())}
    assert conds["2买"]["level"] == 9.3


def test_forward_1buy_from_down_segment_low_is_approx():
    r = _result(segments=[Segment(dir="down", i_start=40, i_end=50, p_start=11.0, p_end=8.5)])
    conds = {c["signal"]: c for c in forward_conditions(r, _df())}
    assert conds["1买"]["level"] == 8.5
    assert "近似" in conds["1买"]["confidence"]


def test_next_trading_days_skips_weekend():
    days = _next_trading_days("2026-06-19", n=3, is_trading_day=lambda d: pd.Timestamp(d).weekday() < 5)
    assert [str(d) for d in days] == ["2026-06-22", "2026-06-23", "2026-06-24"]


def test_build_chart_returns_figure():
    import plotly.graph_objects as go
    from chanlun_chart_ui import build_chart
    df = _df()
    r = _result(
        pivots=[Pivot(ZG=12.0, ZD=10.0, GG=13.0, DD=9.0, i_start=5, i_end=20, seg_count=3)],
        points=[TradePoint("1买", 30, 9.3, "背驰"), TradePoint("3买", 50, 12.5, "上破中枢")],
        segments=[Segment(dir="down", i_start=40, i_end=50, p_start=11.0, p_end=8.5)],
    )
    fut = [pd.Timestamp("2026-06-22").date(), pd.Timestamp("2026-06-23").date(),
           pd.Timestamp("2026-06-24").date()]
    fig = build_chart(df, r, fut)
    assert isinstance(fig, go.Figure)
    assert len(fig.data) >= 1


def test_build_chart_has_stroke_and_segment_lines():
    import plotly.graph_objects as go
    from chanlun_engine import Stroke, Fractal
    from chanlun_chart_ui import build_chart
    df = _df()
    strokes = [Stroke(dir="up", start=Fractal("bottom", 0, 2, 8.0), end=Fractal("top", 0, 10, 12.0)),
               Stroke(dir="down", start=Fractal("top", 0, 10, 12.0), end=Fractal("bottom", 0, 18, 9.0))]
    segs = [Segment(dir="up", i_start=2, i_end=10, p_start=8.0, p_end=12.0),
            Segment(dir="down", i_start=10, i_end=18, p_start=12.0, p_end=9.0)]
    r = _result(segments=segs)
    r.strokes = strokes
    fig = build_chart(df, r, [])
    names = [t.name for t in fig.data]
    assert "笔" in names
    assert "线段" in names


def test_build_chart_has_fractal_and_diverge_traces():
    from chanlun_engine import Fractal
    from chanlun_chart_ui import build_chart
    df = _df()
    r = _result(
        segments=[Segment(dir="down", i_start=40, i_end=50, p_start=11.0, p_end=8.5)],
        points=[TradePoint("1买", 50, 8.5, "下跌段力度背驰")],
    )
    r.fractals = [Fractal("bottom", 0, 50, 8.5), Fractal("top", 0, 30, 12.0)]
    fig = build_chart(df, r, [])
    names = [t.name for t in fig.data]
    assert "分型" in names
    assert "背驰段" in names
