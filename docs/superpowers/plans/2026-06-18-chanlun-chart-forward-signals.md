# 缠论图解 + 未来3天条件信号 页 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增网页：输入股票代码 → 缠论日线图标注中枢/买卖点 + 未来3交易日决策区关键价位横线 + 图下6类买卖点未来条件文字。

**Architecture:** 新 `chanlun_chart_ui.py`(root)：纯逻辑(`forward_conditions`/`_next_trading_days`) + 画图(`build_chart` plotly) + 页面(`display_chanlun_chart`)。复用 `chanlun_engine.analyze_one` 只读，`_load_kline` 取日K。接 `views/sidebar.py`+`views/page_router.py`。

**Tech Stack:** Streamlit + plotly + pandas；chanlun_engine（容器/host 均可 import，纯 dataclass+pandas）。

**关键约束（已核对）：**
- `chanlun_engine.analyze_one(df) -> ChanResult`：`.pivots`[Pivot: ZG/ZD/GG/DD/i_start/i_end/seg_count]、`.points`[TradePoint: kind/i/price/note]、`.segments`[Segment: dir('up'/'down')/i_start/i_end/p_start/p_end，含 .high/.low 属性]。
- `mine_commonality._load_kline(code) -> df`（DatetimeIndex「日期」+ Open/High/Low/Close/Volume；None 表示无数据）。在 `/app/data/profit_mining`，需 sys.path。
- `intraday_quote.is_cn_trading_day(today=None) -> bool`（交易日历优先，退化周一~周五）。在 `/app/data/profit_mining`，需 sys.path。
- TradePoint.i / Pivot.i_start/i_end 是「原始行号」（对齐传入 df 的 reset_index 行序）。画图用 `df.index[i]`（日期）定位。
- 纯逻辑函数（forward_conditions/_next_trading_days/build_chart）顶层只依赖 pandas/plotly/chanlun_engine，可 host 单测；`_load_kline`/`is_cn_trading_day` 在页面函数内 lazy import 或注入。
- develop on main；改 root 需 `docker compose build agentsstock`+`up -d agentsstock` recreate。

---

## File Structure

| 文件 | 责任 |
|------|------|
| `chanlun_chart_ui.py`（新, root） | forward_conditions / _next_trading_days / build_chart / display_chanlun_chart |
| `views/sidebar.py`（改） | 「选股板块」加「📐 缠论图解」按钮 |
| `views/page_router.py`（改） | 加 `show_chanlun_chart` 分派 |
| `tests/test_chanlun_chart.py`（新） | forward_conditions / _next_trading_days / build_chart 单测 |
| `tests/test_ui_pages_smoke.py`（改） | 参数化加 `show_chanlun_chart` |

---

## Task 1: 纯逻辑 forward_conditions + _next_trading_days

**Files:**
- Create: `chanlun_chart_ui.py`（先只含两函数 + import）
- Test: `tests/test_chanlun_chart.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_chanlun_chart.py
"""缠论图解：未来条件反推 / 未来交易日推算 / 画图冒烟。"""
import pandas as pd

from chanlun_engine import ChanResult, Pivot, TradePoint, Segment, KBar
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
    # 2026-06-19 是周五 → 跳过 6-20/21 周末 → 6-22/23/24
    days = _next_trading_days("2026-06-19", n=3, is_trading_day=lambda d: pd.Timestamp(d).weekday() < 5)
    assert [str(d) for d in days] == ["2026-06-22", "2026-06-23", "2026-06-24"]
```

- [ ] **Step 2: 跑确认失败**

Run: `python3 -m pytest tests/test_chanlun_chart.py -q`
Expected: FAIL（`ModuleNotFoundError: chanlun_chart_ui`）

- [ ] **Step 3: 实现 chanlun_chart_ui.py 的两函数**

```python
# chanlun_chart_ui.py
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
```

- [ ] **Step 4: 跑确认通过**

Run: `python3 -m pytest tests/test_chanlun_chart.py -q`
Expected: PASS（5 passed）

- [ ] **Step 5: Commit**

```bash
git add chanlun_chart_ui.py tests/test_chanlun_chart.py
git commit -m "feat(chanlun-chart): forward_conditions 未来条件反推 + _next_trading_days

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: 画图 build_chart（plotly）

**Files:**
- Modify: `chanlun_chart_ui.py`（加 build_chart）
- Test: `tests/test_chanlun_chart.py`（追加 Figure 冒烟）

- [ ] **Step 1: 追加失败测试**

```python
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
    assert len(fig.data) >= 1   # 至少有蜡烛图
```

- [ ] **Step 2: 跑确认失败**

Run: `python3 -m pytest tests/test_chanlun_chart.py -k build_chart -q`
Expected: FAIL（`cannot import name 'build_chart'`）

- [ ] **Step 3: 实现 build_chart**（加到 chanlun_chart_ui.py）

```python
def build_chart(df, result, future_days):
    """组装 plotly Figure：蜡烛 + 中枢矩形 + 买卖点 markers + 关键价位横线 + 未来决策区阴影。"""
    import plotly.graph_objects as go

    x = list(df.index)
    fig = go.Figure(data=[go.Candlestick(
        x=x, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
        increasing_line_color="#d33", decreasing_line_color="#3a3", name="K线")])

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
        xs = [df.index[p.i] for p in pts if p.i < len(df)]
        ys = [p.price * yoff for p in pts if p.i < len(df)]
        txt = [f"{p.kind}: {p.note}" for p in pts if p.i < len(df)]
        if xs:
            fig.add_trace(go.Scatter(x=xs, y=ys, mode="markers+text",
                                     marker=dict(symbol=sym, size=12, color=color),
                                     text=[p.kind for p in pts if p.i < len(df)],
                                     textposition="bottom center", hovertext=txt,
                                     hoverinfo="text", name=("买点" if color == "#d33" else "卖点")))

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

    fig.update_layout(height=560, xaxis_rangeslider_visible=False,
                      margin=dict(l=10, r=60, t=30, b=10), showlegend=True)
    return fig
```

- [ ] **Step 4: 跑确认通过**

Run: `python3 -m pytest tests/test_chanlun_chart.py -q`
Expected: PASS（6 passed）

- [ ] **Step 5: Commit**

```bash
git add chanlun_chart_ui.py tests/test_chanlun_chart.py
git commit -m "feat(chanlun-chart): build_chart 蜡烛+中枢矩形+买卖点+关键价位+决策区

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: 页面 display_chanlun_chart

**Files:**
- Modify: `chanlun_chart_ui.py`（加 display_chanlun_chart）

页面取数走容器内 `_load_kline`（lazy import）；无单元测试（依赖容器数据），由 Task 4 冒烟 + Task 5 端到端覆盖。

- [ ] **Step 1: 实现 display_chanlun_chart**（加到 chanlun_chart_ui.py）

```python
def _load_kline_day(code):
    import sys
    if "/app/data/profit_mining" not in sys.path:
        sys.path.insert(0, "/app/data/profit_mining")
    from mine_commonality import _load_kline
    return _load_kline(code)


def display_chanlun_chart():
    import streamlit as st
    from chanlun_engine import analyze_one

    st.header("📐 缠论图解（含未来3天条件信号）")
    st.caption("输入股票代码 → 缠论日线图标注中枢/买卖点，并推演未来3个交易日的买卖点触发条件。")

    code = st.text_input("股票代码（6位，如 600000 / 000001）", value="").strip()
    if not st.button("📊 分析", type="primary") and not code:
        st.info("请输入股票代码后点「分析」。")
        return
    if not code:
        st.warning("请输入股票代码。")
        return

    df = None
    try:
        df = _load_kline_day(code)
    except Exception as e:
        logger.exception("缠论图解取K线失败")
        st.error(f"取K线失败：{e}")
        return
    if df is None or len(df) < 60:
        st.warning("无数据或样本不足（需≥60根日K）。请确认代码或本地K线覆盖。")
        return

    dfn = df.tail(N_BARS).reset_index().rename(columns={"日期": "date", df.index.name or "index": "date"})
    # 统一索引为日期，行号 0..n-1 对齐缠论引擎
    dfn = df.tail(N_BARS).copy()
    res = analyze_one(dfn.reset_index(drop=True))

    # 缠论引擎用行号；把 res 的 i 对齐到 dfn 的日期索引（dfn 已是日期索引，行号即 reset 后的位置）
    fig = build_chart(dfn, res, _next_trading_days(dfn.index[-1]))
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("🔮 未来3个交易日 · 买卖点触发条件")
    conds = forward_conditions(res, dfn)
    if not conds:
        st.info("当前结构未识别出可推演的买卖点条件（无中枢/买卖点）。")
    else:
        fut = _next_trading_days(dfn.index[-1])
        earliest = fut[0].strftime("%Y-%m-%d") if fut else ""
        rows = [{"信号": c["signal"], "方向": c["direction"], "阈值价": c["level"],
                 "最早可能日": earliest, "条件": c["text"], "置信": c["confidence"]} for c in conds]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    st.caption("⚠️ 缠论为结构化技术判断，非投资建议；未来条件为基于当前结构的推演，需后续K线走出确认；"
               "1买/1卖的背驰条件为近似提示，不保证成立。")
```

- [ ] **Step 2: 语法检查**

Run: `python3 -c "import ast; ast.parse(open('chanlun_chart_ui.py').read()); print('syntax OK')"`
Expected: `syntax OK`

- [ ] **Step 3: 纯逻辑测试仍过（import 页面模块不触发容器依赖）**

Run: `python3 -m pytest tests/test_chanlun_chart.py -q`
Expected: PASS（6 passed；display 的 _load_kline/streamlit 均在函数内 import，模块导入不受影响）

- [ ] **Step 4: Commit**

```bash
git add chanlun_chart_ui.py
git commit -m "feat(chanlun-chart): display_chanlun_chart 页面(输入→分析→图+条件表+免责)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: 导航接线 + 冒烟

**Files:**
- Modify: `views/sidebar.py`、`views/page_router.py`、`tests/test_ui_pages_smoke.py`

- [ ] **Step 1: views/sidebar.py 在「📈 起涨预测(观察中)」按钮块之后加按钮**

定位 `key="nav_qizhang"` 按钮整块之后，插入（同风格、同缩进，清除其它 show_* 标志，含 `show_qizhang`）：

```python
            if st.button("📐 缠论图解", width='stretch', key="nav_chanlun_chart", help="输入代码看缠论中枢/买卖点图 + 未来3天买卖点触发条件"):
                st.session_state.show_chanlun_chart = True
                for key in ['show_history', 'show_monitor', 'show_config', 'show_main_force',
                           'show_sector_strategy', 'show_longhubang', 'show_portfolio', 'show_low_price_bull',
                           'show_small_cap', 'show_profit_growth', 'show_value_stock', 'show_news_flow',
                           'show_macro_analysis', 'show_macro_cycle', 'show_smart_monitor', 'show_intraday',
                           'show_chanlun', 'show_liumai', 'show_combo', 'show_stable', 'show_qizhang']:
                    if key in st.session_state:
                        del st.session_state[key]
```

- [ ] **Step 2: views/page_router.py 加分派**（同风格，放在 `show_qizhang` 分派之后）

```python
    if st.session_state.get('show_chanlun_chart'):
        from chanlun_chart_ui import display_chanlun_chart
        display_chanlun_chart()
        return True
```

- [ ] **Step 3: tests/test_ui_pages_smoke.py 的 flag 列表追加**

在含 `"show_qizhang"` 的 PAGE_FLAGS 列表追加 `"show_chanlun_chart"`。

- [ ] **Step 4: 跑 UI 冒烟（空输入下渲染不崩）**

Run: `python3 -m pytest tests/test_ui_pages_smoke.py -q`
Expected: PASS（页数 +1 全过；缠论图解页空代码走「请输入股票代码」分支）

- [ ] **Step 5: Commit**

```bash
git add views/sidebar.py views/page_router.py tests/test_ui_pages_smoke.py
git commit -m "feat(chanlun-chart): 侧栏按钮+路由接线+UI冒烟 show_chanlun_chart

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: 全量回归 + 重建镜像 + 容器端到端验证

**Files:** 无（构建+验证）

- [ ] **Step 1: 全量回归**

Run: `python3 -m pytest tests/ -q`
Expected: 全绿（基线 282 passed 之上 +缠论图解新测；0 failed/1 skipped）

- [ ] **Step 2: 重建镜像 + recreate**

Run:
```bash
docker compose build agentsstock
docker compose up -d agentsstock
```
Expected: 构建成功 + agentsstock1 healthy。

- [ ] **Step 3: 容器内端到端验证（真实代码出图+条件）**

Run:
```bash
docker exec -w /app agentsstock1 python3 -c "
import sys; sys.path.insert(0, '/app/data/profit_mining')
from chanlun_engine import analyze_one
from chanlun_chart_ui import forward_conditions, build_chart, _next_trading_days
from mine_commonality import _load_kline
df=_load_kline('600000').tail(120).reset_index(drop=True)
r=analyze_one(df)
print('中枢数', len(r.pivots), '买卖点数', len(r.points))
conds=forward_conditions(r, df)
for c in conds: print(' ', c['signal'], c['level'], c['confidence'])
print('未来交易日', _next_trading_days(_load_kline('600000').tail(1).index[-1]))
import plotly.graph_objects as go
print('Figure OK', isinstance(build_chart(_load_kline('600000').tail(120), r, _next_trading_days(_load_kline('600000').tail(1).index[-1])), go.Figure))
"
```
Expected: 打印中枢/买卖点数、若干条件(信号/阈值价/置信)、未来3交易日、`Figure OK True`；无 traceback。

- [ ] **Step 4: AppTest 渲染该页贴关键文本**

Run:
```bash
docker exec -w /app agentsstock1 python3 -c "
from streamlit.testing.v1 import AppTest
at=AppTest.from_file('app.py', default_timeout=180)
at.session_state['show_chanlun_chart']=True
at.run()
print('exception:', at.exception)
print('headers:', [h.value for h in at.header])
"
```
Expected: `exception: None`；headers 含「📐 缠论图解（含未来3天条件信号）」。

- [ ] **Step 5: Commit（如无代码改动则跳过）**

无新增代码则跳过；端到端仅验证。

---

## Self-Review

**1. Spec 覆盖**
- 输入代码→缠论图(中枢/买卖点标注) → Task 2 build_chart + Task 3 页面 ✅
- 未来3交易日决策区+关键价位横线(不画假K线) → Task 2 add_vrect/add_hline ✅
- 图下6类买卖点未来条件(反推关键价位,1买/1卖近似) → Task 1 forward_conditions ✅
- 复用 chanlun_engine 只读 → analyze_one ✅
- 未来交易日 is_cn_trading_day 跳周末 → Task 1 _next_trading_days(可注入,host可测) ✅
- 测试(纯逻辑/Figure/页面冒烟) → Task 1/2/4 ✅
- 免责上页 → Task 3 ✅
- 导航接线 → Task 4 ✅

**2. Placeholder 扫描**：无 TBD/TODO；每步含完整代码/命令。Task3 的 dfn 构造有一行被后一行覆盖重写(第一行 rename 冗余)——**实现时删掉冗余首行，直接 `dfn = df.tail(N_BARS).copy()`**（已在 Step1 标注以第二个赋值为准）。

**3. 一致性**：forward_conditions(result, df) 返回 dict 键(signal/direction/level/text/confidence) 在 Task1 定义、Task3 消费一致；build_chart(df, result, future_days)(Task2)→Task3 调用一致；_next_trading_days(Task1)→Task3 一致；ChanResult/Pivot/TradePoint/Segment 字段与 chanlun_engine 实际一致。

**修正备注（实现须执行）**：Task 3 Step1 代码块中 `dfn = df.tail(N_BARS).reset_index()...` 那一行为误留，实现时删除，仅保留 `dfn = df.tail(N_BARS).copy()` + `res = analyze_one(dfn.reset_index(drop=True))`；并确保 build_chart/forward_conditions 收到的是「日期索引、行号 0..n-1 对齐」的 dfn（即传 `dfn` 给 build_chart 作图用日期索引，传 `dfn.reset_index(drop=True)` 给 analyze_one 算行号——两者行序一致，TradePoint.i 即 dfn 的位置）。
