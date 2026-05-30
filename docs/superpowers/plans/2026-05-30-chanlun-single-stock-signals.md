# 缠论选股 — 单股全历史信号查询 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在缠论选股页内新增「个股信号查询」模式：输入单只股票代码，实时跑缠论引擎，列出该股全历史所有买卖点（6 类），与批量选股相互独立。

**Architecture:** 新增纯 IO+组装模块 `chanlun_single.py`，复用 `chanlun_batch._load`（TDX 本地源加载）与纯函数引擎 `chanlun_engine.analyze / stop_loss_for`，**不读批量库 `chanlun_signals.db`**。`chanlun_ui.py` 顶部加 `st.radio` 在「批量选股 / 个股信号查询」间切换，原批量分支逻辑零改动。

**Tech Stack:** Python, Streamlit, pandas, pytest（monkeypatch）, Streamlit AppTest 无头测试。

**Spec:** `docs/superpowers/specs/2026-05-30-chanlun-single-stock-signals-design.md`

---

## File Structure

- Create: `chanlun_single.py` — 单股查询数据层（代码规整、加载、跑引擎、组装展示 DataFrame）。
- Create: `tests/test_chanlun_single.py` — `_normalize` 与 `query_stock_signals`（monkeypatch `_load`）单测。
- Modify: `chanlun_ui.py` — 加 radio 模式切换 + `_display_single_stock` 渲染函数与缓存。
- Modify(可选): `tests/test_chanlun_ui_smoke.py`（若已存在 AppTest 冒烟则追加；否则新建）。

---

## Task 1: 单股查询数据层 `chanlun_single.py`

**Files:**
- Create: `chanlun_single.py`
- Test: `tests/test_chanlun_single.py`

- [ ] **Step 1: Write the failing test**

创建 `tests/test_chanlun_single.py`：

```python
# tests/test_chanlun_single.py
import pandas as pd
import chanlun_single
from chanlun_single import _normalize, query_stock_signals, KEEP_COLS


def _fake_day(n=80):
    """构造一段先跌后涨的日线，确保引擎能产出买卖点。索引为日期。"""
    import numpy as np
    idx = pd.date_range("2026-01-01", periods=n, freq="D")
    # 锯齿 + 趋势：保证有分型/笔/段
    base = list(range(n, 0, -1)) if False else None
    highs, lows = [], []
    price = 50.0
    for i in range(n):
        # 前半段下行、后半段上行的之字形
        drift = -0.6 if i < n // 2 else 0.6
        wob = 1.5 if i % 2 == 0 else -1.5
        price = max(5.0, price + drift + wob)
        highs.append(price + 1.0)
        lows.append(price - 1.0)
    close = [(h + l) / 2 for h, l in zip(highs, lows)]
    return pd.DataFrame({"Open": close, "High": highs, "Low": lows,
                         "Close": close, "Volume": [1] * n}, index=idx)


def test_normalize_strips_prefix_and_space():
    assert _normalize("sh600519") == "600519"
    assert _normalize("SZ000001") == "000001"
    assert _normalize(" 600519 ") == "600519"


def test_invalid_code_rejected():
    ok, df, msg = query_stock_signals("abc")
    assert ok is False and df is None and "6 位" in msg
    ok2, _, _ = query_stock_signals("12345")
    assert ok2 is False


def test_no_data_returns_friendly(monkeypatch):
    monkeypatch.setattr(chanlun_single, "_load", lambda *a, **k: None)
    ok, df, msg = query_stock_signals("600519")
    assert ok is False and df is None and "日线" in msg


def test_signals_assembled_sorted_desc(monkeypatch):
    day = _fake_day()

    def fake_load(sym, kind, limit):
        return day if kind == "day" else None  # 30min 返回 None → 无次级别确认分支

    monkeypatch.setattr(chanlun_single, "_load", fake_load)
    ok, df, msg = query_stock_signals("600519")
    assert ok is True and df is not None
    assert list(df.columns) == KEEP_COLS
    # 倒序：第一行日期 >= 最后一行
    assert df["signal_date"].iloc[0] >= df["signal_date"].iloc[-1]
    # 买点有止损、卖点止损为空
    buys = df[df["signal_type"].isin(["1买", "2买", "3买"])]
    sells = df[df["signal_type"].isin(["1卖", "2卖", "3卖"])]
    assert (buys["stop_loss"].notna()).all()
    if len(sells):
        assert (sells["stop_loss"].isna()).all()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_chanlun_single.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'chanlun_single'`

- [ ] **Step 3: Write minimal implementation**

创建 `chanlun_single.py`：

```python
# chanlun_single.py
"""缠论单股查询：实时加载某股日线+30分钟K线，跑引擎，列出全历史所有买卖点(6类)。
与批量库(chanlun_signals.db)完全解耦——本模块只读 TDX 本地源、纯实时计算。"""
from typing import Tuple, Optional
import pandas as pd
from chanlun_batch import _load                       # 复用本地源加载(标准 OHLCV)
from chanlun_engine import analyze, stop_loss_for

_BUY = ("1买", "2买", "3买")

KEEP_COLS = ["signal_type", "signal_date", "price", "stop_loss", "reason", "level"]
DISPLAY_NAMES = {"signal_type": "信号类型", "signal_date": "信号日期",
                 "price": "信号参考价", "stop_loss": "止损位",
                 "reason": "缠论理由", "level": "级别"}


def _normalize(code: str) -> str:
    """规整为纯 6 位数字代码(去掉 sh/sz/bj 前缀与空白)。"""
    c = code.strip().lower()
    for pre in ("sh", "sz", "bj"):
        if c.startswith(pre):
            c = c[len(pre):]
    return c.strip()


def query_stock_signals(code: str) -> Tuple[bool, Optional[pd.DataFrame], str]:
    sym = _normalize(code)
    if not sym.isdigit() or len(sym) != 6:
        return False, None, "请输入 6 位股票代码（如 600519）"
    try:
        df_day = _load(sym, "day", 500)
        if df_day is None or len(df_day) < 60:
            return False, None, f"{sym} 本地无足够日线数据（需≥60根），无法计算"
        df_30m = _load(sym, "30min", 2000)
        res = analyze(df_day, df_30m)
    except Exception as e:  # 本地源/引擎异常不抛到页面，给友好提示
        return False, None, f"{sym} 计算失败：{type(e).__name__}: {str(e)[:80]}"
    if not res.points:
        return False, None, f"{sym} 全历史未检出缠论买卖点信号"
    day_index = list(df_day.index)
    rows = []
    for p in res.points:
        if p.i < 0 or p.i >= len(day_index):
            continue
        rows.append({
            "signal_type": p.kind,
            "signal_date": pd.Timestamp(day_index[p.i]).strftime("%Y-%m-%d"),
            "price": round(float(p.price), 3),
            "stop_loss": stop_loss_for(p, res.pivots) if p.kind in _BUY else None,
            "reason": p.note,
            "level": "日线",
        })
    df = pd.DataFrame(rows, columns=KEEP_COLS).sort_values(
        "signal_date", ascending=False).reset_index(drop=True)
    return True, df, f"{sym} 全历史共 {len(df)} 个缠论信号（含买卖点）"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_chanlun_single.py -v`
Expected: PASS（4 个测试全过）

注意：测试用例 `test_signals_assembled_sorted_desc` 依赖引擎对构造数据产出至少 1 个买点。若该锯齿序列恰好不产买点导致 `ok is False`，调整 `_fake_day` 的 `drift/wob` 幅度（如增大波幅到 2.5）直至 `res.points` 非空——这是测试夹具调参，不改实现。

- [ ] **Step 5: Commit**

```bash
git add chanlun_single.py tests/test_chanlun_single.py
git commit -m "feat(chanlun): 单股全历史信号查询数据层 chanlun_single

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: UI 模式切换与单股渲染 `chanlun_ui.py`

**Files:**
- Modify: `chanlun_ui.py`
- Test: `tests/test_chanlun_ui_smoke.py`

- [ ] **Step 1: Write the failing smoke test**

创建/追加 `tests/test_chanlun_ui_smoke.py`（用 Streamlit AppTest 无头跑页面，验证两个模式都不抛异常）：

```python
# tests/test_chanlun_ui_smoke.py
"""缠论选股页 AppTest 冒烟：切换两个模式不抛异常。不触真实本地源。"""
import pandas as pd
from streamlit.testing.v1 import AppTest


_SCRIPT = """
import streamlit as st
import chanlun_single
import pandas as pd

# 桩掉实时查询，避免依赖本地源
def _fake_query(code):
    df = pd.DataFrame({
        "signal_type": ["1买", "1卖"], "signal_date": ["2026-05-28", "2026-05-20"],
        "price": [10.0, 12.0], "stop_loss": [9.8, None],
        "reason": ["下跌段力度背驰；30m确认", "上涨段力度背驰；30m确认"],
        "level": ["日线", "日线"],
    }, columns=chanlun_single.KEEP_COLS)
    return True, df, "600519 全历史共 2 个缠论信号（含买卖点）"

chanlun_single.query_stock_signals = _fake_query
from chanlun_ui import display_chanlun_selector
display_chanlun_selector()
"""


def test_batch_mode_renders():
    at = AppTest.from_string(_SCRIPT).run()
    assert not at.exception
    # 默认批量模式：radio 存在且默认第一项
    assert at.radio[0].value == "批量选股"


def test_single_mode_renders_after_input():
    at = AppTest.from_string(_SCRIPT).run()
    at.radio[0].set_value("个股信号查询").run()
    assert not at.exception
    at.text_input[0].set_value("600519").run()
    assert not at.exception
    # 桩数据的 msg 出现在 info 中
    assert any("全历史共 2" in str(i.value) for i in at.info)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_chanlun_ui_smoke.py -v`
Expected: FAIL —— 因 `chanlun_ui` 尚无 radio，`at.radio[0]` 索引越界或断言失败。

- [ ] **Step 3: Implement UI changes**

修改 `chanlun_ui.py`。在文件顶部 import 后、`display_chanlun_selector` 之前加缓存与渲染函数；并在 `display_chanlun_selector` 的 caption 之后插入 radio 分支。

完整新版 `chanlun_ui.py`：

```python
# chanlun_ui.py
"""缠论选股页：①批量选股(只读 chanlun_signals.db 批次，买点+配对卖点)；
②个股信号查询(实时跑引擎，列单股全历史全部买卖点)。两模式顶部 radio 切换、互不影响。"""
import streamlit as st
from chanlun_selector import ChanlunSelector, DISPLAY_NAMES

_TYPES = ["1买", "2买", "3买"]


# 缠论信号每日收盘后批量预计算、当天只读，故缓存读取结果，避免每次多选交互都重开
# SQLite 查询。TTL 30 分钟远短于「每日 20:00 更新一次」，不会读到跨日陈旧数据。
@st.cache_data(ttl=1800, show_spinner=False)
def _cached_picks(types_key: tuple, scan_date: str):
    return ChanlunSelector().get_chanlun_picks(types=list(types_key), scan_date=scan_date)


# 单股查询为实时计算(加载2000根30分钟K线+分析)，较重，按代码缓存。TTL 同批量。
@st.cache_data(ttl=1800, show_spinner="计算中…")
def _cached_single(code: str):
    from chanlun_single import query_stock_signals
    return query_stock_signals(code)


def _display_single_stock():
    from chanlun_single import DISPLAY_NAMES as SINGLE_NAMES
    st.caption("输入单只股票代码，实时计算该股全历史所有缠论买卖点（1/2/3买 + 1/2/3卖，"
               "日线本级别 + 30分钟次级别确认）。与批量选股相互独立。")
    code = st.text_input("股票代码", placeholder="如 600519 或 sh600519",
                         key="chanlun_single_code")
    if not code.strip():
        st.info("请输入股票代码后查询")
        return
    ok, df, msg = _cached_single(code.strip())
    st.info(msg)
    if not ok or df is None:
        return
    st.dataframe(df.rename(columns=SINGLE_NAMES), width='stretch', height=460)
    st.caption("信号参考价=买卖点当根收盘/极值价；止损位仅买点给出（买点前最近中枢下沿 ZD 与 价×0.98 取低）。"
               "缠论理由含背驰/回踩/突破依据及次级别确认。全历史范围取决于本地日线长度（最多 500 根）。")


def display_chanlun_selector():
    st.markdown('<div class="ftc-section">🌀 缠论选股</div>', unsafe_allow_html=True)

    mode = st.radio("功能", ["批量选股", "个股信号查询"], horizontal=True,
                    label_visibility="collapsed", key="chanlun_mode")
    if mode == "个股信号查询":
        _display_single_stock()
        return

    st.caption("严格多级别缠论（日线本级别 + 30分钟次级别确认）·"
               " 选出最近 7 个交易日出现一买/二买/三买的股票。数据源：TDX 本地库。"
               " 信号每日收盘后批量预计算，本页只读结果（初筛候选，请人工复核）。")

    dates = ChanlunSelector().list_dates()
    if not dates:
        st.info("暂无缠论买点信号（批量扫描尚未运行）")
        return

    col1, col2 = st.columns([2, 1])
    with col1:
        picked = st.multiselect("买点类型", _TYPES, default=_TYPES)
    with col2:
        scan_date = st.selectbox("扫描日期", dates, index=0)  # 倒序，默认最新

    ok, df, msg = _cached_picks(tuple(picked), scan_date)
    st.info(msg)
    if not ok or df is None:
        return
    st.dataframe(df.rename(columns=DISPLAY_NAMES), width='stretch', height=460)
    st.caption("买入理由=该买点的缠论依据(背驰/回踩/突破，含次级别确认)；止损=买点下方关键位"
               "(买点前最近中枢下沿与买点价×0.98取低)。卖点=该买点之后出现的首个缠论卖点"
               "(一卖/二卖/三卖)，含信号日期与卖出理由；尚未出现则留空。")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_chanlun_ui_smoke.py -v`
Expected: PASS（两个测试全过）

- [ ] **Step 5: Run full chanlun test suite (回归确认批量链路零破坏)**

Run: `python3 -m pytest tests/test_chanlun_selector.py tests/test_chanlun_signal_db.py tests/test_chanlun_single.py tests/test_chanlun_ui_smoke.py -v`
Expected: PASS（全过；批量选股相关测试未受影响）

- [ ] **Step 6: Commit**

```bash
git add chanlun_ui.py tests/test_chanlun_ui_smoke.py
git commit -m "feat(chanlun): 缠论选股页加个股信号查询模式(顶部 radio 切换)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review Notes

- **Spec coverage**：①实时计算不读批量库 → Task 1 `query_stock_signals`（`_load`+`analyze`，无 DB import）。②全 6 类买卖点 → 遍历 `res.points` 不过滤类型。③30分钟确认 → `_load(sym,"30min",2000)` 传入 `analyze`。④代码输入框 → Task 2 `st.text_input`。⑤顶部 radio 切换、批量零改动 → Task 2 `display_chanlun_selector` 保留原分支整段。⑥错误处理表 → `query_stock_signals` 的非法码/无数据/无信号/异常四分支 + UI 空输入分支。⑦测试策略 → Task 1 monkeypatch 单测 + Task 2 AppTest 冒烟。
- **Placeholder scan**：无 TBD/TODO；唯一"调参"说明在 Task 1 Step 4，属测试夹具数值微调、非实现占位。
- **Type consistency**：`KEEP_COLS` / `DISPLAY_NAMES` / `_normalize` / `query_stock_signals` 在 Task 1 定义，Task 2 与测试引用一致；`_cached_single` / `_display_single_stock` 在 Task 2 内自洽。
```
