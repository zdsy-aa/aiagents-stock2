# 缠论选股 — 单股全历史信号查询（实时计算）设计

日期：2026-05-30
分支：`feat/chanlun-single-stock-signals`

## 背景与目标

现有「缠论选股」页（`chanlun_ui.py` → `display_chanlun_selector`）只读 `chanlun_signals.db`
的某个批次（`scan_date`），展示该批次内所有股票**最近 7 个交易日**的买点及其配对卖点。

需求：在缠论选股页内新增一个功能——**输入单只股票代码，实时计算并展示该股全历史所有缠论买卖点信号**。

关键决策（与用户确认）：
- 单股查询**不读批量库**，而是**实时跑缠论引擎**，得到全 K 线历史的所有信号（批量库只存近 7 日，无法满足"所有信号"）。
- 展示**全部 6 类**买卖点：1买/2买/3买 + 1卖/2卖/3卖。
- 实时计算**加载 30 分钟次级别确认**，与批量扫描行为一致（理由栏标注「30m确认/无次级别确认」）。
- 输入方式：**代码输入框**（支持 `600519` / `sh600519` 等写法）。
- 切换方式：页面**顶部 `st.radio`** 在「批量选股 / 个股信号查询」间切换，互不影响。

## 隔离性原则

- 批量选股链路（`chanlun_signal_db.py` / `chanlun_selector.py` / `chanlun_batch.main`）**零改动**。
- 新增独立模块 `chanlun_single.py`（IO + 组装），复用纯函数引擎 `chanlun_engine`。
- `chanlun_ui.py` 只增加一个 radio 分支，原批量分支代码逻辑不变。

## 组件设计

### 1. 新模块 `chanlun_single.py`

职责：给定股票代码，加载 K 线 → 跑引擎 → 把全部买卖点组装成展示用 DataFrame。

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

说明：
- `_load` 复用 `chanlun_batch._load`（经 `akshare_gw.local.get_kline` 取标准 OHLCV、索引=日期）。
- `analyze(df_day, df_30m)` 返回全历史所有 `TradePoint`（6 类）。`p.note` 已含次级别确认标注。
- 止损位仅对买点计算（`stop_loss_for`）；卖点该列留空（`None`）。
- 全历史范围由本地源 K 线长度决定（日线最多取 500 根）。

### 2. UI 改动 `chanlun_ui.py`

在 `display_chanlun_selector` 内，标题 + caption 之后插入 radio，按选择走两个分支：

```python
mode = st.radio("功能", ["批量选股", "个股信号查询"], horizontal=True,
                label_visibility="collapsed", key="chanlun_mode")
if mode == "个股信号查询":
    _display_single_stock()
    return
# ↓↓↓ 以下为原批量选股逻辑，完全不变 ↓↓↓
```

新增私有渲染函数与缓存：

```python
@st.cache_data(ttl=1800, show_spinner="计算中…")
def _cached_single(code: str):
    from chanlun_single import query_stock_signals
    return query_stock_signals(code)


def _display_single_stock():
    from chanlun_single import DISPLAY_NAMES as SINGLE_NAMES
    st.caption("输入单只股票代码，实时计算该股全历史所有缠论买卖点（1/2/3买 + 1/2/3卖，"
               "日线本级别 + 30分钟次级别确认）。与批量选股相互独立。")
    code = st.text_input("股票代码", placeholder="如 600519 或 sh600519", key="chanlun_single_code")
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
```

## 数据流

```
用户输入代码
  → chanlun_ui._display_single_stock
  → _cached_single(code)  [st.cache_data 30min]
  → chanlun_single.query_stock_signals
      → chanlun_batch._load(day 500) / _load(30min 2000)   [akshare_gw.local，TDX 本地源]
      → chanlun_engine.analyze(df_day, df_30m)             [纯函数，全历史 6 类点]
      → stop_loss_for(买点)                                 [纯函数]
  → DataFrame(信号类型/日期/参考价/止损/理由/级别) 倒序
  → st.dataframe 中文表头展示
```

## 错误处理

| 情况 | 行为 |
|------|------|
| 代码非 6 位数字 | 返回提示「请输入 6 位股票代码」，不查询 |
| 本地无数据/日线<60根 | 返回提示「无足够日线数据」 |
| 引擎无任何买卖点 | 返回提示「全历史未检出缠论买卖点信号」 |
| 输入框为空 | UI 直接 `st.info` 提示，不调用引擎 |
| `_load`/`analyze` 抛异常 | `query_stock_signals` 内 try/except 捕获，返回 `(False, None, "…计算失败…")` 友好提示，不抛到页面 |

## 测试策略

- 引擎为纯函数、已有手工 K 线单测锚定，不重复测。
- 新增 `chanlun_single` 的轻量单测（不依赖真实本地源）：
  - `_normalize`：`sh600519`/`SZ000001`/`600519 ` → `600519` / `000001` / `600519`。
  - `query_stock_signals` 非法代码（如 `abc`、`12345`）→ 返回 `(False, None, 含"6 位")`。
  - 用 monkeypatch 把 `chanlun_single._load` 替换为返回构造好的 DataFrame，再验证：
    - 无数据/<60 根 → `(False, None, …)`；
    - 有买卖点 → 返回 df 列为 `KEEP_COLS`、按日期倒序、买点 stop_loss 非空 / 卖点为空。
- UI 用现有 AppTest 无头网页测试法（见项目记忆）冒烟：切到「个股信号查询」、输入代码、断言无异常。

## 不做（YAGNI）

- 不加 K 线图/画点可视化（仅表格）。
- 不把单股结果落库（纯实时，不污染 `chanlun_signals.db`）。
- 不做股票名称联想/下拉（用户选定纯代码输入框）。
- 不改批量选股任何行为。
