"""缠论图解 + 未来3天条件信号 只读页。

输入股票代码 → 缠论日线图(中枢/买卖点标注 + 未来3交易日决策区关键价位横线)
+ 图下6类买卖点未来条件。复用 chanlun_engine 只读，不下单/不发邮件。
"""
import logging

import pandas as pd

logger = logging.getLogger(__name__)

N_BARS = 120          # 图上展示最近日K根数
FUTURE_DAYS = 3       # 未来决策区交易日数


def forward_conditions(result, df):
    """基于当前 ChanResult 反推各类买卖点关键价位与条件文本。

    返回 list[dict(signal, direction, level, text, confidence)]；仅在对应结构存在时输出该条。
    3买/3卖←最近中枢ZG/ZD；2买/2卖←最近1买/1卖价；1买/1卖←最近下跌/上涨段端点(近似,需背驰确认)。
    """
    out = []
    pv = result.pivots[-1] if result.pivots else None
    if pv is not None:
        out.append({"signal": "3买", "direction": "up", "level": round(pv.ZG, 2),
                    "text": f"若价站上中枢ZG={pv.ZG:.2f}后回踩不破 → 3买（中枢突破）", "confidence": "明确"})
        out.append({"signal": "3卖", "direction": "down", "level": round(pv.ZD, 2),
                    "text": f"若跌破中枢ZD={pv.ZD:.2f}后反抽不破 → 3卖（中枢跌破）", "confidence": "明确"})

    one_buys = [p for p in result.points if p.kind == "1买"]
    one_sells = [p for p in result.points if p.kind == "1卖"]
    if one_buys:
        lv = one_buys[-1].price
        out.append({"signal": "2买", "direction": "up", "level": round(lv, 2),
                    "text": f"若回踩不破最近1买低点{lv:.2f} → 2买", "confidence": "明确"})
    if one_sells:
        lv = one_sells[-1].price
        out.append({"signal": "2卖", "direction": "down", "level": round(lv, 2),
                    "text": f"若反弹不破最近1卖高点{lv:.2f} → 2卖", "confidence": "明确"})

    downs = [s for s in result.segments if s.dir == "down"]
    ups = [s for s in result.segments if s.dir == "up"]
    if downs:
        z = downs[-1].low
        out.append({"signal": "1买", "direction": "down", "level": round(z, 2),
                    "text": f"若跌破前低{z:.2f}且下跌力度较前段衰减（MACD底背驰）→ 1买",
                    "confidence": "近似（需背驰确认）"})
    if ups:
        z = ups[-1].high
        out.append({"signal": "1卖", "direction": "up", "level": round(z, 2),
                    "text": f"若上破前高{z:.2f}且上涨力度衰减（MACD顶背驰）→ 1卖",
                    "confidence": "近似（需背驰确认）"})
    return out


def _next_trading_days(last_date, n=FUTURE_DAYS, is_trading_day=None):
    """从 last_date 之后推 n 个交易日(date 列表)。is_trading_day 可注入(默认用 intraday_quote)。"""
    if is_trading_day is None:
        import sys
        if "/app/data/profit_mining" not in sys.path:
            sys.path.insert(0, "/app/data/profit_mining")
        from intraday_quote import is_cn_trading_day as is_trading_day
    out = []
    d = pd.Timestamp(last_date)
    while len(out) < n:
        d = d + pd.Timedelta(days=1)
        if is_trading_day(d):
            out.append(d.date())
    return out


def build_chart(df, result, future_days, conditions=None):
    """组装 plotly Figure：蜡烛 + 笔/线段 + 分型 + 背驰段 + 中枢 + 买卖点 + 关键价位 + 决策区 + 未来条件框。"""
    import plotly.graph_objects as go

    x = list(df.index)
    fig = go.Figure(data=[go.Candlestick(
        x=x, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
        increasing_line_color="#d33", decreasing_line_color="#3a3", name="K线")])

    # 笔：相邻分型转折点连成的细折线（顶点=笔端点；点击图例可隐藏）
    if result.strokes:
        bx, by = [], []
        first = result.strokes[0]
        if first.start.i < len(df):
            bx.append(df.index[first.start.i]); by.append(first.start.price)
        for s in result.strokes:
            if s.end.i < len(df):
                bx.append(df.index[s.end.i]); by.append(s.end.price)
        if len(bx) >= 2:
            fig.add_trace(go.Scatter(x=bx, y=by, mode="lines", name="笔",
                                     line=dict(color="rgba(230,150,40,0.85)", width=1)))

    # 线段：段端点连成的粗折线（更高级别，盖在笔之上）
    if result.segments:
        sx, sy = [], []
        first = result.segments[0]
        if first.i_start < len(df):
            sx.append(df.index[first.i_start]); sy.append(first.p_start)
        for s in result.segments:
            if s.i_end < len(df):
                sx.append(df.index[s.i_end]); sy.append(s.p_end)
        if len(sx) >= 2:
            fig.add_trace(go.Scatter(x=sx, y=sy, mode="lines", name="线段",
                                     line=dict(color="rgba(40,90,200,0.95)", width=2)))

    # 分型点：顶▽红 / 底△绿（单 trace，逐点 symbol/color；默认显示）
    fr = [f for f in result.fractals if f.i < len(df)]
    if fr:
        fig.add_trace(go.Scatter(
            x=[df.index[f.i] for f in fr], y=[f.price for f in fr], mode="markers", name="分型",
            marker=dict(size=7,
                        symbol=["triangle-down" if f.kind == "top" else "triangle-up" for f in fr],
                        color=["#e44" if f.kind == "top" else "#2a8" for f in fr]),
            hovertext=["顶分型" if f.kind == "top" else "底分型" for f in fr], hoverinfo="text"))

    # 背驰段高亮：note 含「背驰」的买卖点 → i_end==point.i 的线段，金色粗线（单 trace，None 分隔）
    seg_by_end = {s.i_end: s for s in result.segments}
    bx, by = [], []
    for p in result.points:
        if "背驰" in (p.note or "") and p.i in seg_by_end:
            s = seg_by_end[p.i]
            if s.i_start < len(df) and s.i_end < len(df):
                bx += [df.index[s.i_start], df.index[s.i_end], None]
                by += [s.p_start, s.p_end, None]
    if bx:
        fig.add_trace(go.Scatter(x=bx, y=by, mode="lines", name="背驰段",
                                 line=dict(color="rgba(240,180,20,0.95)", width=4)))

    # 中枢矩形（半透明）
    for pv in result.pivots:
        if pv.i_start < len(df) and pv.i_end < len(df):
            fig.add_shape(type="rect", x0=df.index[pv.i_start], x1=df.index[pv.i_end],
                          y0=pv.ZD, y1=pv.ZG, fillcolor="rgba(120,120,220,0.15)",
                          line=dict(color="rgba(120,120,220,0.6)", width=1), layer="below")
            fig.add_annotation(x=df.index[pv.i_end], y=pv.ZG, text=f"ZG{pv.ZG:.2f}",
                               showarrow=False, font=dict(size=9, color="#558"))

    # 买卖点 markers
    buys = [p for p in result.points if "买" in p.kind]
    sells = [p for p in result.points if "卖" in p.kind]
    for pts, color, sym, yoff in [(buys, "#d33", "triangle-up", 0.97), (sells, "#2a8", "triangle-down", 1.03)]:
        sel = [p for p in pts if p.i < len(df)]
        if sel:
            fig.add_trace(go.Scatter(
                x=[df.index[p.i] for p in sel], y=[p.price * yoff for p in sel],
                mode="markers+text", marker=dict(symbol=sym, size=12, color=color),
                text=[p.kind for p in sel], textposition="bottom center",
                hovertext=[f"{p.kind}: {p.note}" for p in sel], hoverinfo="text",
                name=("买点" if color == "#d33" else "卖点")))

    # 关键价位横线（最近中枢 ZG/ZD）
    if result.pivots:
        pv = result.pivots[-1]
        for lvl, label, c in [(pv.ZG, f"中枢ZG {pv.ZG:.2f}", "#558"), (pv.ZD, f"中枢ZD {pv.ZD:.2f}", "#855")]:
            fig.add_hline(y=lvl, line=dict(color=c, width=1, dash="dot"),
                          annotation_text=label, annotation_position="right")

    # 未来3交易日决策区（阴影 + 标注，无虚拟 K 线）
    if future_days:
        x_all = x + [pd.Timestamp(d) for d in future_days]
        fig.add_vrect(x0=pd.Timestamp(future_days[0]) - pd.Timedelta(hours=12),
                      x1=pd.Timestamp(future_days[-1]) + pd.Timedelta(hours=12),
                      fillcolor="rgba(200,200,200,0.18)", line_width=0,
                      annotation_text="未来3日决策区(无真实K线)", annotation_position="top left")
        fig.update_xaxes(range=[x_all[0], x_all[-1]])

    # 未来条件提示框：决策区内对每条 condition 在阈值价处标注（图文对应）
    if conditions and future_days:
        x_mid = pd.Timestamp(future_days[len(future_days) // 2])
        for c in conditions:
            verb = "站上" if c["direction"] == "up" else "跌破"
            fig.add_annotation(x=x_mid, y=c["level"], text=f"{c['signal']} {verb}{c['level']}",
                               showarrow=False, font=dict(size=9, color="#333"),
                               bgcolor="rgba(255,245,200,0.9)", bordercolor="#caa", borderwidth=1)

    fig.update_layout(height=560, xaxis_rangeslider_visible=False,
                      margin=dict(l=10, r=60, t=30, b=10), showlegend=True)
    return fig


def _load_kline_day(code):
    import sys
    if "/app/data/profit_mining" not in sys.path:
        sys.path.insert(0, "/app/data/profit_mining")
    from mine_commonality import _load_kline
    return _load_kline(code)


def _load_kline_30m(code):
    """取 30m K线(标准 OHLCV)，失败/无数据返回 None。复用 chanlun_batch._load。"""
    try:
        import sys
        for p in ("/app", "/app/data/profit_mining"):
            if p not in sys.path:
                sys.path.insert(0, p)
        from chanlun_batch import _load
        return _load(code, "30min", 2000)
    except Exception:
        logger.info("30m K线取数失败，退回单级别")
        return None


def display_chanlun_chart():
    import streamlit as st
    from chanlun_engine import analyze

    st.header("📐 缠论图解（含未来3天条件信号）")
    st.caption("输入股票代码 → 缠论日线图标注中枢/买卖点，并推演未来3个交易日的买卖点触发条件。")

    code = st.text_input("股票代码（6位，如 600000 / 000001）", value="").strip()
    if not st.button("📊 分析", type="primary") and not code:
        st.info("请输入股票代码后点「分析」。")
        return
    if not code:
        st.warning("请输入股票代码。")
        return

    try:
        df = _load_kline_day(code)
    except Exception as e:
        logger.exception("缠论图解取K线失败")
        st.error(f"取K线失败：{e}")
        return
    if df is None or len(df) < 60:
        st.warning("无数据或样本不足（需≥60根日K）。请确认代码或本地K线覆盖。")
        return

    # 日期索引的 dfn 用于作图；reset_index 后行号 0..n-1 对齐缠论引擎(TradePoint.i/Pivot.i_*)
    dfn = df.tail(N_BARS).copy()
    df_30m = _load_kline_30m(code)
    df_30m_r = df_30m.reset_index(drop=True) if df_30m is not None else None
    res = analyze(dfn.reset_index(drop=True), df_30m_r)   # 多级别(日线本级别 + 30m 次级别确认)

    fut = _next_trading_days(dfn.index[-1])
    conds = forward_conditions(res, dfn)
    fig = build_chart(dfn, res, fut, conditions=conds)
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("🔮 未来3个交易日 · 买卖点触发条件")
    if not conds:
        st.info("当前结构未识别出可推演的买卖点条件（无中枢/买卖点）。")
    else:
        earliest = fut[0].strftime("%Y-%m-%d") if fut else ""
        rows = [{"信号": c["signal"], "方向": c["direction"], "阈值价": c["level"],
                 "最早可能日": earliest, "条件": c["text"], "置信": c["confidence"]} for c in conds]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    # 30m 次级别确认统计
    confirmed = sum(1 for p in res.points if "30m确认" in (p.note or ""))
    unconfirmed = sum(1 for p in res.points if "无次级别确认" in (p.note or ""))
    if df_30m is not None:
        st.caption(f"📎 多级别(30m)联立：本级别买卖点中 {confirmed} 个获 30m 确认 / {unconfirmed} 个未确认"
                   "（买卖点 hover 可见各自确认情况）。")
    else:
        st.caption("📎 多级别(30m)：未取到 30 分钟K线，本次仅日线本级别判断。")

    st.caption("⚠️ 缠论为结构化技术判断，非投资建议；未来条件为基于当前结构的推演，需后续K线走出确认；"
               "1买/1卖的背驰条件为近似提示，不保证成立。")
