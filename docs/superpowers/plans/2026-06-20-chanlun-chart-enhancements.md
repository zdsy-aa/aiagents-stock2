# 缠论图解页 4 项增强 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在缠论图解页加 分型点标注 / 背驰段高亮 / 未来条件图上提示框 / 多级别30m联立。

**Architecture:** 全部改 `chanlun_chart_ui.py`：`build_chart` 加分型/背驰段 trace + 可选 conditions 提示框；`display_chanlun_chart` 改用 `analyze(df_day, df_30m)` 并补 30m 确认统计。复用 chanlun_engine 既有产物 + `chanlun_batch._load` 取 30m。

**Tech Stack:** Streamlit + plotly + pandas + chanlun_engine。

**关键约束（已核对）：**
- `ChanResult.fractals`：`Fractal(kind in {"top","bottom"}, i 行号, price)`。
- 买卖点 `TradePoint.i` == 触发线段的 `i_end`；「背驰段」= `segments` 中 `i_end==point.i` 那段；仅 note 含「背驰」的点(1买/1卖)需高亮。
- 30m：`chanlun_batch._load(code, "30min", 2000)` 返回标准 OHLCV（索引=日期）或 None；`chanlun_engine.analyze(df_day, df_30m)` 给买卖点 note 追加「30m确认」/「无次级别确认」。
- `forward_conditions` 返回 `[{signal,direction('up'/'down'),level,text,confidence}]`（已实现）。
- `build_chart(df, result, future_days)` 现签名（Task 2 加 `conditions=None`）；现有调用 `build_chart(dfn,res,fut)` 须保持兼容（默认 None）。
- 纯画图/逻辑 host 可测；30m 取数仅在容器（display 内 lazy import）。
- develop on main；改 root 需 `docker compose build agentsstock`+`up -d agentsstock` recreate。

---

## File Structure

| 文件 | 改动 |
|------|------|
| `chanlun_chart_ui.py` | build_chart 加分型/背驰段/conditions 提示框；display 加 30m 联立 + 确认统计 + `_load_kline_30m` |
| `tests/test_chanlun_chart.py` | 追加分型/背驰段/条件框 trace 与 annotation 断言 |

---

## Task 1: build_chart 加 分型点 + 背驰段

**Files:**
- Modify: `chanlun_chart_ui.py`（build_chart 内，在「笔/线段」trace 之后、中枢之前插入）
- Test: `tests/test_chanlun_chart.py`

- [ ] **Step 1: 追加失败测试**

```python
def test_build_chart_has_fractal_and_diverge_traces():
    import plotly.graph_objects as go
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
```

- [ ] **Step 2: 跑确认失败**

Run: `python3 -m pytest tests/test_chanlun_chart.py -k fractal_and_diverge -q`
Expected: FAIL（无「分型」「背驰段」trace）

- [ ] **Step 3: 实现**（加到 build_chart，在 `# 中枢矩形（半透明）` 之前）

```python
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
```

- [ ] **Step 4: 跑确认通过**

Run: `python3 -m pytest tests/test_chanlun_chart.py -q`
Expected: PASS（8 passed）

- [ ] **Step 5: Commit**

```bash
git add chanlun_chart_ui.py tests/test_chanlun_chart.py
git commit -m "feat(chanlun-chart): 分型点标注(顶▽/底△) + 背驰段高亮(金色粗线)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: build_chart 未来条件图上提示框

**Files:**
- Modify: `chanlun_chart_ui.py`（build_chart 加 `conditions=None` 参数 + 决策区标注）
- Test: `tests/test_chanlun_chart.py`

- [ ] **Step 1: 追加失败测试**

```python
def test_build_chart_draws_condition_annotations():
    from chanlun_chart_ui import build_chart, forward_conditions
    df = _df()
    r = _result(pivots=[Pivot(ZG=12.0, ZD=10.0, GG=13.0, DD=9.0, i_start=5, i_end=20, seg_count=3)])
    conds = forward_conditions(r, df)
    fut = [pd.Timestamp("2026-06-22").date(), pd.Timestamp("2026-06-23").date(),
           pd.Timestamp("2026-06-24").date()]
    fig = build_chart(df, r, fut, conditions=conds)
    texts = " ".join(a.text for a in fig.layout.annotations)
    assert "3买" in texts and "站上" in texts
```

- [ ] **Step 2: 跑确认失败**

Run: `python3 -m pytest tests/test_chanlun_chart.py -k condition_annotations -q`
Expected: FAIL（build_chart 不接 conditions / 无标注）

- [ ] **Step 3: 实现**
1) 改 build_chart 签名：`def build_chart(df, result, future_days, conditions=None):`
2) 在「未来3交易日决策区」block **之后**（决策区已把 x 轴 range 扩到 future）追加：

```python
    # 未来条件提示框：决策区内对每条 condition 在阈值价处标注（图文对应）
    if conditions and future_days:
        x_mid = pd.Timestamp(future_days[len(future_days) // 2])
        for c in conditions:
            verb = "站上" if c["direction"] == "up" else "跌破"
            fig.add_annotation(x=x_mid, y=c["level"], text=f"{c['signal']} {verb}{c['level']}",
                               showarrow=False, font=dict(size=9, color="#333"),
                               bgcolor="rgba(255,245,200,0.9)", bordercolor="#caa", borderwidth=1)
```

- [ ] **Step 4: 跑确认通过**

Run: `python3 -m pytest tests/test_chanlun_chart.py -q`
Expected: PASS（9 passed）

- [ ] **Step 5: Commit**

```bash
git add chanlun_chart_ui.py tests/test_chanlun_chart.py
git commit -m "feat(chanlun-chart): 未来条件在决策区图上提示框(图文对应)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: display 多级别30m联立 + 确认统计

**Files:**
- Modify: `chanlun_chart_ui.py`（加 `_load_kline_30m`；改 `display_chanlun_chart`）

无独立单测（30m 取数依赖容器），由 Task 4 容器端到端覆盖；本任务做语法 + 现有测试不回退。

- [ ] **Step 1: 加 `_load_kline_30m` 助手**（放在 `_load_kline_day` 之后）

```python
def _load_kline_30m(code):
    """取 30m K线(标准 OHLCV)，失败/无数据返回 None。复用 chanlun_batch._load。"""
    try:
        import sys
        if "/app/data/profit_mining" not in sys.path:
            sys.path.insert(0, "/app/data/profit_mining")
        if "/app" not in sys.path:
            sys.path.insert(0, "/app")
        from chanlun_batch import _load
        return _load(code, "30min", 2000)
    except Exception:
        logger.info("30m K线取数失败，退回单级别")
        return None
```

- [ ] **Step 2: 改 `display_chanlun_chart` 的分析与画图段**

把原 `res = analyze_one(dfn.reset_index(drop=True))` 与 `build_chart(dfn, res, fut)` 段替换为：

```python
    from chanlun_engine import analyze   # 多级别入口

    dfn = df.tail(N_BARS).copy()
    df_30m = _load_kline_30m(code)
    df_30m_r = df_30m.reset_index(drop=True) if df_30m is not None else None
    res = analyze(dfn.reset_index(drop=True), df_30m_r)

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
                   f"（买卖点 hover 可见各自确认情况）。")
    else:
        st.caption("📎 多级别(30m)：未取到 30 分钟K线，本次仅日线本级别判断。")
```

（注意：删除原先重复的 `res=analyze_one(...)`、`fig=build_chart(dfn,res,fut)`、旧条件表与旧 30m 无关段，避免重复渲染；`analyze_one` import 可保留或移除——`analyze` 已涵盖。免责 caption 保持在末尾不动。）

- [ ] **Step 3: 语法检查 + 现有纯逻辑测试不回退**

Run:
```bash
python3 -c "import ast; ast.parse(open('chanlun_chart_ui.py').read()); print('syntax OK')"
python3 -m pytest tests/test_chanlun_chart.py -q
```
Expected: `syntax OK` + PASS（9 passed；display 的 30m/streamlit 均函数内 import，不影响模块导入）

- [ ] **Step 4: Commit**

```bash
git add chanlun_chart_ui.py
git commit -m "feat(chanlun-chart): display 多级别30m联立(analyze+30m确认统计,取不到回退)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: 全量回归 + 重建镜像 + 容器端到端

**Files:** 无（构建+验证）

- [ ] **Step 1: 全量回归**

Run: `python3 -m pytest tests/ -q`
Expected: 全绿（基线 290 passed 之上 +2 增强测试；0 failed/1 skipped）

- [ ] **Step 2: 重建镜像 + recreate**

Run:
```bash
docker compose build agentsstock
docker compose up -d agentsstock
```
Expected: 构建成功 + agentsstock1 healthy。

- [ ] **Step 3: 容器端到端（真实代码，验证四增强出图 + 30m 联立）**

Run:
```bash
docker exec -w /app agentsstock1 python3 -c "
import sys; sys.path.insert(0, '/app/data/profit_mining')
from chanlun_engine import analyze
from chanlun_chart_ui import build_chart, forward_conditions, _next_trading_days, _load_kline_day, _load_kline_30m
import plotly.graph_objects as go
code='600000'
df=_load_kline_day(code); dfn=df.tail(120).copy()
d30=_load_kline_30m(code)
res=analyze(dfn.reset_index(drop=True), d30.reset_index(drop=True) if d30 is not None else None)
conds=forward_conditions(res, dfn)
fig=build_chart(dfn, res, _next_trading_days(df.index[-1]), conditions=conds)
names=[t.name for t in fig.data]
print('30m取到:', d30 is not None and len(d30))
print('trace:', names)
print('分型trace有:', '分型' in names, '| 背驰段trace有:', '背驰段' in names)
print('决策区标注数:', len(fig.layout.annotations))
print('30m确认点数:', sum(1 for p in res.points if '30m确认' in (p.note or '')))
print('Figure OK', isinstance(fig, go.Figure))
"
```
Expected: 打印 30m 取到根数、trace 含「分型」「背驰段」、决策区标注数≥1、Figure OK True；无 traceback。

- [ ] **Step 4: AppTest 渲染该页无异常**

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
Expected: `exception: None`（空异常）；header 含「📐 缠论图解（含未来3天条件信号）」。

- [ ] **Step 5: 无新代码改动则跳过 commit；功能已在前序 commit。**

---

## Self-Review

**1. Spec 覆盖**
- 分型点标注（默认显示）→ Task 1 「分型」trace ✅
- 背驰段高亮 → Task 1 「背驰段」trace（i_end==point.i + note含背驰）✅
- 未来条件图上提示框 → Task 2 conditions 参数 + 决策区 annotation ✅
- 多级别30m联立 → Task 3 _load_kline_30m + analyze + 确认统计 + 取不到回退 ✅
- 只改 chanlun_chart_ui.py + 测试 → 全部 ✅
- 测试（分型/背驰段 trace、条件 annotation）→ Task 1/2 ✅；30m 端到端 → Task 4 ✅

**2. Placeholder 扫描**：无 TBD/TODO；每步含完整代码。Task 3 Step2 提示「删除原重复段」——是必要的去重操作说明，非占位。

**3. 一致性**：build_chart 新增 `conditions=None`（Task 2）→ Task 3 display 传 `conditions=conds` 一致；`_load_kline_30m`(Task3)→Task4 端到端调用一致；trace 名「分型」「背驰段」在 Task1 定义、Task4 断言一致；forward_conditions 字段 direction('up'/'down')→Task2 verb 映射一致。
