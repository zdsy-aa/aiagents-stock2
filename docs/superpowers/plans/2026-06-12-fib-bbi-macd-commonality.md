# 方案A/B 涨跌前期共性挖掘 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 独立验证方案A(斐波回调线+MACD)/方案B(BBI+MACD)在 ZigZag 切出的"上涨前/下跌前"样本上、遍历指标参数后哪些组合有≥70%覆盖共性且提升度高。

**Architecture:** 四个单一职责模块串联：`zigzag_segments`(切段)→`swing_samples`(W=5正样本窗口)→`param_signals`(参数化斐波/BBI/MACD信号,复用features.py公式)→`mine_commonality`(逐股累加计数→覆盖率/提升度/精确度→筛≥0.70→报告)。前三者纯计算、本地合成数据TDD；末者main()在容器全市场跑。

**Tech Stack:** Python3, pandas, numpy, multiprocessing.Pool；复用 `data/profit_mining/features.py` 的 `EMA/MA/HHV/LLV`；本地K源 `akshare_gateway.akshare_gw.local.get_kline`。

**Spec:** `docs/superpowers/specs/2026-06-12-fib-bbi-macd-commonality-design.md`

**约定:** 所有新文件落 `data/profit_mining/`。测试为无pytest脚本，在该目录下 `python3 test_xxx.py` 运行，断言+`print("OK ...")`。全市场run在容器：`docker exec -w /app agentsstock1 python3 /app/data/profit_mining/mine_commonality.py`。

---

### Task 1: ZigZag 切段 zigzag_segments.py

**Files:**
- Create: `data/profit_mining/zigzag_segments.py`
- Test: `data/profit_mining/test_zigzag.py`

- [ ] **Step 1: Write the failing test**

```python
# test_zigzag.py —— ZigZag 拐点与切段合成数据测试（python3 test_zigzag.py）
import zigzag_segments as Z


def test_pivots_v_then_up():
    # 100→80(跌20%)→100(涨25%)，pct=0.15：应得 H@0, L@2
    high = [100, 90, 80, 90, 100]
    low  = [100, 90, 80, 90, 100]
    piv = Z.zigzag_pivots(high, low, 0.15)
    assert piv == [(0, "H"), (2, "L")], piv
    print("OK pivots_v_then_up")


def test_pivots_full():
    # 低100→高130(+30%)→低104(-20%)：从首根起先上后下
    high = [110, 120, 130, 120, 104]
    low  = [100, 110, 120, 110, 104]
    piv = Z.zigzag_pivots(high, low, 0.15)
    # 起点低候选@0(low100)，涨到130确认L@0、H@2，再回落到104(<130*0.85=110.5)确认H@2、L@4
    assert piv[0] == (0, "L"), piv
    assert (2, "H") in piv and (4, "L") in piv, piv
    print("OK pivots_full")


def test_segments():
    piv = [(0, "L"), (2, "H"), (4, "L")]
    segs = Z.segments_from_pivots(piv)
    assert segs == [(0, 2, "up"), (2, 4, "down")], segs
    print("OK segments")


def test_empty():
    assert Z.zigzag_pivots([], [], 0.15) == []
    assert Z.segments_from_pivots([]) == []
    print("OK empty")


if __name__ == "__main__":
    test_pivots_v_then_up()
    test_pivots_full()
    test_segments()
    test_empty()
    print("ALL OK")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd data/profit_mining && python3 test_zigzag.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'zigzag_segments'`

- [ ] **Step 3: Write minimal implementation**

```python
# zigzag_segments.py —— ZigZag 摆动切段：日K高低 → 拐点 → 上涨/下跌段。纯计算。
from __future__ import annotations


def zigzag_pivots(high, low, pct):
    """ZigZag 拐点。high/low 等长序列(时间升序)，pct 反向摆动确认阈值(0.15=15%)。
    返回 [(idx, kind)]，kind ∈ {"L","H"}，时间升序且方向交替。"""
    n = len(high)
    if n == 0:
        return []
    h = list(high); lo = list(low)
    pivots = []
    trend = 0                      # +1 上行寻顶 / -1 下行寻底 / 0 未定
    hi_v, hi_i = h[0], 0
    lo_v, lo_i = lo[0], 0
    for i in range(1, n):
        if trend > 0:
            if h[i] > hi_v:
                hi_v, hi_i = h[i], i
            elif lo[i] <= hi_v * (1 - pct):
                pivots.append((hi_i, "H")); trend = -1
                lo_v, lo_i = lo[i], i
        elif trend < 0:
            if lo[i] < lo_v:
                lo_v, lo_i = lo[i], i
            elif h[i] >= lo_v * (1 + pct):
                pivots.append((lo_i, "L")); trend = 1
                hi_v, hi_i = h[i], i
        else:
            if h[i] > hi_v:
                hi_v, hi_i = h[i], i
            if lo[i] < lo_v:
                lo_v, lo_i = lo[i], i
            if h[i] >= lo_v * (1 + pct):
                pivots.append((lo_i, "L")); trend = 1
                hi_v, hi_i = h[i], i
            elif lo[i] <= hi_v * (1 - pct):
                pivots.append((hi_i, "H")); trend = -1
                lo_v, lo_i = lo[i], i
    return pivots


def segments_from_pivots(pivots):
    """相邻拐点 → 段。返回 [(start_idx, end_idx, direction)]，
    direction: "up"(L→H) / "down"(H→L)。非交替对跳过。"""
    segs = []
    for (i0, k0), (i1, k1) in zip(pivots, pivots[1:]):
        if k0 == "L" and k1 == "H":
            segs.append((i0, i1, "up"))
        elif k0 == "H" and k1 == "L":
            segs.append((i0, i1, "down"))
    return segs
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd data/profit_mining && python3 test_zigzag.py`
Expected: `ALL OK`

- [ ] **Step 5: Commit**

```bash
git add data/profit_mining/zigzag_segments.py data/profit_mining/test_zigzag.py
git commit -m "feat: ZigZag 摆动切段(拐点+上涨/下跌段)"
```

---

### Task 2: 正样本窗口 swing_samples.py

**Files:**
- Create: `data/profit_mining/swing_samples.py`
- Test: `data/profit_mining/test_swing_samples.py`

- [ ] **Step 1: Write the failing test**

```python
# test_swing_samples.py —— W=5 正样本窗口测试
import swing_samples as S


def test_windows():
    # 拐点 L@10, H@20, L@30 → 上涨段(10→20)取波谷10前含10的5根[6..10]；
    # 下跌段(20→30)取波峰20前含20的5根[16..20]
    high = [100] * 40
    low = [100] * 40
    # 直接喂拐点，绕过 zigzag（用 monkeypatch 思路：传入 pivots）
    up, down = S.windows_from_pivots([(10, "L"), (20, "H"), (30, "L")], W=5)
    assert up == [[6, 7, 8, 9, 10]], up
    assert down == [[16, 17, 18, 19, 20]], down
    print("OK windows")


def test_truncate_head():
    # 拐点 L@2：窗口不足5根，截到[0,1,2]
    up, down = S.windows_from_pivots([(2, "L"), (8, "H")], W=5)
    assert up == [[0, 1, 2]], up
    print("OK truncate_head")


def test_positive_windows_end2end():
    # 真实序列：先跌后涨再跌，验证 positive_windows 串起 zigzag
    high = [110, 100, 130, 120, 104]
    low = [100, 90, 120, 110, 104]
    up, down = S.positive_windows(high, low, 0.15, W=3)
    assert isinstance(up, list) and isinstance(down, list)
    print("OK end2end")


if __name__ == "__main__":
    test_windows()
    test_truncate_head()
    test_positive_windows_end2end()
    print("ALL OK")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd data/profit_mining && python3 test_swing_samples.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'swing_samples'`

- [ ] **Step 3: Write minimal implementation**

```python
# swing_samples.py —— 由 ZigZag 段生成 W=5 正样本窗口（上涨前买 / 下跌前卖）。
import zigzag_segments as Z


def windows_from_pivots(pivots, W=5):
    """拐点 → (up_windows, down_windows)。
    每个 up 段(L→H)取波谷 L 当根及前 W-1 根；down 段(H→L)取波峰 H 当根及前 W-1 根。
    段起点即对应拐点(L 或 H)。窗口边界 < 0 时头部截断。"""
    segs = Z.segments_from_pivots(pivots)
    up, down = [], []
    for start, _end, d in segs:
        win = list(range(max(0, start - (W - 1)), start + 1))
        (up if d == "up" else down).append(win)
    return up, down


def positive_windows(high, low, pct, W=5):
    """日K高低 → (up_windows, down_windows)。"""
    pivots = Z.zigzag_pivots(high, low, pct)
    return windows_from_pivots(pivots, W)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd data/profit_mining && python3 test_swing_samples.py`
Expected: `ALL OK`

- [ ] **Step 5: Commit**

```bash
git add data/profit_mining/swing_samples.py data/profit_mining/test_swing_samples.py
git commit -m "feat: 由ZigZag段生成W=5上涨前/下跌前正样本窗口"
```

---

### Task 3: 参数化信号(斐波/BBI/MACD) param_signals.py

**Files:**
- Create: `data/profit_mining/param_signals.py`
- Test: `data/profit_mining/test_param_signals.py`

- [ ] **Step 1: Write the failing test**

```python
# test_param_signals.py —— 参数化信号合成数据测试
import pandas as pd
import param_signals as P


def _df(o, h, l, c):
    n = len(c)
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c,
                         "Volume": [1000.0] * n}, index=idx)


def test_macd_golden_dead():
    # 构造先跌后涨：DIF 上穿 DEA 处应有金叉
    c = [10, 9.5, 9, 9.2, 9.6, 10.2, 10.8, 11.5]
    df = _df(c, c, c, c)
    g = P.macd_golden(df, 5, 10, 3)
    d = P.macd_dead(df, 5, 10, 3)
    assert g.sum() >= 1, g.tolist()
    assert (g & d).sum() == 0          # 金叉死叉互斥
    print("OK macd_golden_dead")


def test_fib_support_hold():
    # 近N=4 高=110 低=100，range=10，ratio0.5→support=105。
    # 末根 low=104(<=105*1.01=106.05 触及) 且 close=106(>=105) → 回踩企稳成立
    df = _df([105]*5, [110, 108, 106, 107, 106],
             [100, 103, 104, 104, 104], [108, 106, 105, 106, 106])
    sig = P.fib_support_hold(df, N=4, ratio=0.5, band=0.01)
    assert bool(sig.iloc[-1]) is True, sig.tolist()
    print("OK fib_support_hold")


def test_bbi_cross_up_down():
    c = [10, 10, 10, 10, 9, 9, 9.5, 11, 12]
    df = _df(c, c, c, c)
    up = P.bbi_cross_up(df, (2, 3, 4, 5))
    dn = P.bbi_cross_down(df, (2, 3, 4, 5))
    assert up.sum() >= 1, up.tolist()
    assert (up & dn).sum() == 0
    print("OK bbi_cross")


def test_combiners_and_grids():
    c = [10, 9.5, 9, 9.2, 9.6, 10.2, 10.8, 11.5, 12.0, 12.5]
    df = _df(c, [x + 0.5 for x in c], [x - 0.5 for x in c], c)
    a = P.plan_a_signal(df, 4, 0.5, 0.02, 5, 10, 3, "buy")
    b = P.plan_b_signal(df, (2, 3, 4, 5), 5, 10, 3, "buy")
    assert a.dtype == bool and b.dtype == bool
    assert len(P.PLAN_A_GRID) == 144, len(P.PLAN_A_GRID)
    assert len(P.PLAN_B_GRID) == 12, len(P.PLAN_B_GRID)
    print("OK combiners_grids")


if __name__ == "__main__":
    test_macd_golden_dead()
    test_fib_support_hold()
    test_bbi_cross_up_down()
    test_combiners_and_grids()
    print("ALL OK")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd data/profit_mining && python3 test_param_signals.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'param_signals'`

- [ ] **Step 3: Write minimal implementation**

```python
# param_signals.py —— 方案A/B 参数化信号。复用 features.py 的 EMA/MA/HHV/LLV。
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import features as F   # MA/EMA/HHV/LLV 纯pandas，本地可import


# ---- MACD ----
def _macd_lines(close, fast, slow, signal):
    dif = F.EMA(close, fast) - F.EMA(close, slow)
    dea = F.EMA(dif, signal)
    return dif, dea


def macd_golden(df, fast=12, slow=26, signal=9):
    dif, dea = _macd_lines(df["Close"], fast, slow, signal)
    return ((dif > dea) & (dif.shift(1) <= dea.shift(1))).fillna(False)


def macd_dead(df, fast=12, slow=26, signal=9):
    dif, dea = _macd_lines(df["Close"], fast, slow, signal)
    return ((dif < dea) & (dif.shift(1) >= dea.shift(1))).fillna(False)


# ---- 斐波回调线 ----
def _fib_levels(df, N, ratio):
    hh = F.HHV(df["High"], N)
    ll = F.LLV(df["Low"], N)
    rng = hh - ll
    return hh - rng * ratio, ll + rng * ratio    # support, resistance


def fib_support_hold(df, N=20, ratio=0.618, band=0.01):
    support, _ = _fib_levels(df, N, ratio)
    return ((df["Low"] <= support * (1 + band)) & (df["Close"] >= support)).fillna(False)


def fib_resist_reject(df, N=20, ratio=0.618, band=0.01):
    _, resistance = _fib_levels(df, N, ratio)
    return ((df["High"] >= resistance * (1 - band)) & (df["Close"] <= resistance)).fillna(False)


# ---- BBI ----
def _bbi(close, periods):
    return sum(F.MA(close, p) for p in periods) / len(periods)


def bbi_cross_up(df, periods=(3, 6, 12, 24)):
    b = _bbi(df["Close"], periods)
    return ((df["Close"] > b) & (df["Close"].shift(1) <= b.shift(1))).fillna(False)


def bbi_cross_down(df, periods=(3, 6, 12, 24)):
    b = _bbi(df["Close"], periods)
    return ((df["Close"] < b) & (df["Close"].shift(1) >= b.shift(1))).fillna(False)


# ---- 方案组合 ----
def plan_a_signal(df, N, ratio, band, fast, slow, signal, side):
    macd = macd_golden(df, fast, slow, signal) if side == "buy" else macd_dead(df, fast, slow, signal)
    fib = (fib_support_hold(df, N, ratio, band) if side == "buy"
           else fib_resist_reject(df, N, ratio, band))
    return (fib & macd).fillna(False)


def plan_b_signal(df, periods, fast, slow, signal, side):
    macd = macd_golden(df, fast, slow, signal) if side == "buy" else macd_dead(df, fast, slow, signal)
    bb = (bbi_cross_up(df, periods) if side == "buy" else bbi_cross_down(df, periods))
    return (bb & macd).fillna(False)


# ---- 参数网格（spec §4 起点，可调）----
_MACD = ((12, 26, 9), (8, 17, 9), (6, 19, 9), (5, 35, 5))
PLAN_A_GRID = [(N, r, b, f, s, sig)
               for N in (10, 20, 30, 60)
               for r in (0.382, 0.5, 0.618)
               for b in (0.005, 0.01, 0.02)
               for (f, s, sig) in _MACD]
PLAN_B_GRID = [(p, f, s, sig)
               for p in ((3, 6, 12, 24), (5, 10, 20, 40), (2, 5, 10, 20))
               for (f, s, sig) in _MACD]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd data/profit_mining && python3 test_param_signals.py`
Expected: `ALL OK`

> 若 `import features` 在本地报错（缺 numpy/pandas 之外的依赖），改用容器跑该测试：`docker exec -w /app/data/profit_mining agentsstock1 python3 test_param_signals.py`。

- [ ] **Step 5: Commit**

```bash
git add data/profit_mining/param_signals.py data/profit_mining/test_param_signals.py
git commit -m "feat: 参数化斐波回踩/BBI穿越/MACD金叉死叉信号+方案A/B网格"
```

---

### Task 4: 计数核心 count_for_signal（mine_commonality 第一部分）

**Files:**
- Create: `data/profit_mining/mine_commonality.py`
- Test: `data/profit_mining/test_mine_commonality.py`

- [ ] **Step 1: Write the failing test**

```python
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


if __name__ == "__main__":
    test_count_for_signal()
    test_count_out_of_range_window()
    print("ALL OK")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd data/profit_mining && python3 test_mine_commonality.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'mine_commonality'`

- [ ] **Step 3: Write minimal implementation**

```python
# mine_commonality.py —— 方案A/B 涨跌前期共性挖掘：逐股累加→覆盖率/提升度/精确度→报告。
import numpy as np


def count_for_signal(signal, windows):
    """signal: bool序列(len=n_bars)；windows: list[list[int]] (每段的W=5正样本bar索引)。
    返回 (seg_hit, seg_total, fires_pos, bars_pos, fires_all, bars_all)。
    seg_hit: 窗口内任一根信号True则该段命中；bars_pos: 所有窗口索引去重后的根数；
    fires_pos: 正样本根里信号True数；fires_all/bars_all: 全体。"""
    sig = np.asarray(signal, dtype=bool)
    n = len(sig)
    seg_total = len(windows)
    seg_hit = 0
    pos_idx = set()
    for w in windows:
        idx = [i for i in w if 0 <= i < n]
        if any(bool(sig[i]) for i in idx):
            seg_hit += 1
        pos_idx.update(idx)
    pos_idx = sorted(pos_idx)
    bars_pos = len(pos_idx)
    fires_pos = int(sum(bool(sig[i]) for i in pos_idx))
    fires_all = int(sig.sum())
    bars_all = n
    return seg_hit, seg_total, fires_pos, bars_pos, fires_all, bars_all
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd data/profit_mining && python3 test_mine_commonality.py`
Expected: `ALL OK`

- [ ] **Step 5: Commit**

```bash
git add data/profit_mining/mine_commonality.py data/profit_mining/test_mine_commonality.py
git commit -m "feat: 共性挖掘计数核心 count_for_signal"
```

---

### Task 5: 聚合与排序 finalize/filter_rank

**Files:**
- Modify: `data/profit_mining/mine_commonality.py`
- Test: `data/profit_mining/test_mine_commonality.py`

- [ ] **Step 1: Write the failing test (append to test file)**

```python
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
```
并在 `__main__` 增加 `test_finalize_and_rank()`。

- [ ] **Step 2: Run test to verify it fails**

Run: `cd data/profit_mining && python3 test_mine_commonality.py`
Expected: FAIL — `AttributeError: module 'mine_commonality' has no attribute 'finalize'`

- [ ] **Step 3: Write minimal implementation (append to mine_commonality.py)**

```python
# key = (plan, side, pct, paramtuple)；paramtuple: A=(N,ratio,band,f,s,sig) B=(periods,f,s,sig)
def finalize(counts):
    """counts(已跨股累加) → list[dict] 含 coverage/lift/precision 等。"""
    rows = []
    for (plan, side, pct, params), c in counts.items():
        seg_hit, seg_total, fires_pos, bars_pos, fires_all, bars_all = c
        coverage = seg_hit / seg_total if seg_total else 0.0
        rate_pos = fires_pos / bars_pos if bars_pos else 0.0
        rate_all = fires_all / bars_all if bars_all else 0.0
        lift = rate_pos / rate_all if rate_all > 0 else float("inf")
        precision = fires_pos / fires_all if fires_all else 0.0
        rows.append({"plan": plan, "side": side, "pct": pct, "params": params,
                     "seg_hit": seg_hit, "seg_total": seg_total,
                     "coverage": coverage, "rate_all": rate_all,
                     "lift": lift, "precision": precision})
    return rows


def filter_rank(rows, cover_min=0.70):
    """筛 coverage≥门槛 且 rate_all>0(剔除退化/哪都不亮)，按提升度降序。"""
    keep = [r for r in rows
            if r["seg_total"] > 0 and r["coverage"] >= cover_min and r["rate_all"] > 0]
    return sorted(keep, key=lambda r: r["lift"], reverse=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd data/profit_mining && python3 test_mine_commonality.py`
Expected: `ALL OK`

- [ ] **Step 5: Commit**

```bash
git add data/profit_mining/mine_commonality.py data/profit_mining/test_mine_commonality.py
git commit -m "feat: 共性挖掘聚合 finalize+按提升度筛排 filter_rank"
```

---

### Task 6: 单股累加器 accumulate_stock

**Files:**
- Modify: `data/profit_mining/mine_commonality.py`
- Test: `data/profit_mining/test_mine_commonality.py`

- [ ] **Step 1: Write the failing test (append)**

```python
def test_accumulate_stock():
    import pandas as pd
    # 造一段足够长、含明显涨跌的K线
    base = list(range(20, 60)) + list(range(60, 20, -1))   # 上后下
    c = [float(x) for x in base]
    df = pd.DataFrame({"Open": c, "High": [x + 1 for x in c],
                       "Low": [x - 1 for x in c], "Close": c,
                       "Volume": [1000.0] * len(c)},
                      index=pd.date_range("2020-01-01", periods=len(c), freq="D"))
    counts = M.accumulate_stock(df, pcts=(0.15,))
    # 至少应有 方案A/B × buy/sell × 0.15 的若干 key，计数为6元list
    assert any(k[0] == "A" and k[1] == "buy" and k[2] == 0.15 for k in counts), list(counts)[:3]
    sample = next(iter(counts.values()))
    assert len(sample) == 6
    print("OK accumulate_stock")
```
并在 `__main__` 增 `test_accumulate_stock()`。

- [ ] **Step 2: Run test to verify it fails**

Run: `cd data/profit_mining && python3 test_mine_commonality.py`
Expected: FAIL — `AttributeError: ... has no attribute 'accumulate_stock'`

- [ ] **Step 3: Write minimal implementation (append)**

```python
import swing_samples as SW
import param_signals as PS
from collections import defaultdict

DEFAULT_PCTS = (0.10, 0.15, 0.20)


def accumulate_stock(df, pcts=DEFAULT_PCTS, W=5):
    """单股 → 计数dict key=(plan,side,pct,params) val=[6元累计]。
    df 需含 High/Low/Close 列、时间升序。"""
    out = defaultdict(lambda: [0, 0, 0, 0, 0, 0])
    high = df["High"].tolist(); low = df["Low"].tolist()
    for pct in pcts:
        up_win, down_win = SW.positive_windows(high, low, pct, W)
        for side, windows in (("buy", up_win), ("sell", down_win)):
            if not windows:
                continue
            for params in PS.PLAN_A_GRID:
                sig = PS.plan_a_signal(df, *params, side=side).to_numpy()
                _merge(out[("A", side, pct, params)], count_for_signal(sig, windows))
            for params in PS.PLAN_B_GRID:
                sig = PS.plan_b_signal(df, *params, side=side).to_numpy()
                _merge(out[("B", side, pct, params)], count_for_signal(sig, windows))
    return dict(out)


def _merge(acc, c):
    for i in range(6):
        acc[i] += c[i]


def merge_counts(dst, src):
    """跨股合并：把 src(单股dict) 累加进 dst(defaultdict)。"""
    for k, v in src.items():
        a = dst[k]
        for i in range(6):
            a[i] += v[i]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd data/profit_mining && python3 test_mine_commonality.py`
Expected: `ALL OK`

> 若本地 import features 失败，本测试同样可在容器跑：`docker exec -w /app/data/profit_mining agentsstock1 python3 test_mine_commonality.py`

- [ ] **Step 5: Commit**

```bash
git add data/profit_mining/mine_commonality.py data/profit_mining/test_mine_commonality.py
git commit -m "feat: 单股累加器 accumulate_stock + 跨股 merge_counts"
```

---

### Task 7: 报告输出 write_reports

**Files:**
- Modify: `data/profit_mining/mine_commonality.py`
- Test: `data/profit_mining/test_mine_commonality.py`

- [ ] **Step 1: Write the failing test (append)**

```python
def test_write_reports(tmpdir_path="/tmp/mc_test_out"):
    import os, glob, shutil
    shutil.rmtree(tmpdir_path, ignore_errors=True)
    os.makedirs(tmpdir_path, exist_ok=True)
    rows = [
        {"plan": "A", "side": "buy", "pct": 0.15, "params": (20, 0.618, 0.01, 12, 26, 9),
         "seg_hit": 7, "seg_total": 10, "coverage": 0.7, "rate_all": 0.02,
         "lift": 10.0, "precision": 0.4},
        {"plan": "B", "side": "sell", "pct": 0.10, "params": ((3, 6, 12, 24), 12, 26, 9),
         "seg_hit": 8, "seg_total": 10, "coverage": 0.8, "rate_all": 0.03,
         "lift": 5.0, "precision": 0.3},
    ]
    paths = M.write_reports(rows, out_dir=tmpdir_path, ts="20260612_000000")
    csvs = glob.glob(os.path.join(tmpdir_path, "*.csv"))
    md = glob.glob(os.path.join(tmpdir_path, "*.md"))
    assert len(csvs) >= 1 and len(md) == 1, (csvs, md)
    # A买点榜应含 N/ratio/band/fast 展开列
    head = open([p for p in csvs if "方案A" in p and "上涨前" in p][0],
                encoding="utf-8-sig").readline()
    assert "ratio" in head and "coverage" in head, head
    print("OK write_reports")
```
并在 `__main__` 增 `test_write_reports()`。

- [ ] **Step 2: Run test to verify it fails**

Run: `cd data/profit_mining && python3 test_mine_commonality.py`
Expected: FAIL — `AttributeError: ... has no attribute 'write_reports'`

- [ ] **Step 3: Write minimal implementation (append)**

```python
import os, csv as _csv

SIDE_CN = {"buy": "上涨前", "sell": "下跌前"}


def _expand_params(plan, params):
    if plan == "A":
        N, ratio, band, f, s, sig = params
        return {"N": N, "ratio": ratio, "band": band, "fast": f, "slow": s, "signal": sig}
    periods, f, s, sig = params
    return {"periods": "/".join(map(str, periods)), "fast": f, "slow": s, "signal": sig}


def write_reports(rows, out_dir="/home/tdxback/report", ts=None, cover_min=0.70):
    """已 finalize 的 rows → 按 (plan,side,pct) 分文件写 CSV + 一份横向对比 md。
    rows 传全量 finalize 结果；本函数内部对每个 CSV 各自按 coverage 门槛筛+排序。"""
    import time
    ts = ts or time.strftime("%Y%m%d_%H%M%S")
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    groups = {}
    for r in rows:
        groups.setdefault((r["plan"], r["side"], r["pct"]), []).append(r)
    md_lines = ["# 方案A/B 涨跌前期共性 横向对比", "", f"生成 {ts}，覆盖率门槛 {cover_min}", ""]
    for (plan, side, pct), grp in sorted(groups.items()):
        kept = filter_rank(grp, cover_min)
        zz = f"zz{int(pct*100)}"
        fname = f"方案{plan}_{SIDE_CN[side]}共性_{zz}_{ts}.csv"
        fpath = os.path.join(out_dir, fname)
        base_cols = ["plan", "side", "pct"]
        pcols = (["N", "ratio", "band", "fast", "slow", "signal"] if plan == "A"
                 else ["periods", "fast", "slow", "signal"])
        metric_cols = ["seg_hit", "seg_total", "coverage", "rate_all", "lift", "precision"]
        with open(fpath, "w", newline="", encoding="utf-8-sig") as f:
            w = _csv.writer(f)
            w.writerow(base_cols + pcols + metric_cols)
            for r in kept:
                ep = _expand_params(plan, r["params"])
                w.writerow([r["plan"], r["side"], r["pct"]] +
                           [ep[c] for c in pcols] +
                           [r[c] for c in metric_cols])
        paths.append(fpath)
        if kept:
            top = kept[0]
            ep = _expand_params(plan, top["params"])
            md_lines.append(
                f"- **方案{plan} {SIDE_CN[side]} {zz}**：最佳 {ep} → "
                f"覆盖{top['coverage']:.2f} 提升度{top['lift']:.2f} 精确{top['precision']:.2f}"
                f"（达标 {len(kept)} 组）")
        else:
            md_lines.append(f"- **方案{plan} {SIDE_CN[side]} {zz}**：无≥{cover_min}覆盖组合")
    md_path = os.path.join(out_dir, f"方案AB_共性横向对比_{ts}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines) + "\n")
    paths.append(md_path)
    return paths
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd data/profit_mining && python3 test_mine_commonality.py`
Expected: `ALL OK`

- [ ] **Step 5: Commit**

```bash
git add data/profit_mining/mine_commonality.py data/profit_mining/test_mine_commonality.py
git commit -m "feat: 共性榜CSV(各组分档)+横向对比md输出 write_reports"
```

---

### Task 8: 全市场驱动 main()（容器跑）

**Files:**
- Modify: `data/profit_mining/mine_commonality.py`

- [ ] **Step 1: 写 main() 驱动（无单测，靠 Task 9 冒烟验证）**

在 `mine_commonality.py` 末尾追加：

```python
def _load_kline(code):
    """容器内本地K源 → 标准列 df（时间升序）。复用 build_features_v2 同款读取。"""
    from akshare_gateway import akshare_gw
    df = akshare_gw.local.get_kline(code, kline_type="day", limit=10000)
    if df is None or df.empty:
        return None
    rename = {"开盘": "Open", "最高": "High", "最低": "Low", "收盘": "Close", "成交量": "Volume"}
    return (df.rename(columns=rename).set_index("日期").sort_index()
            [["Open", "High", "Low", "Close", "Volume"]])


def _universe():
    """股票池：events_labeled.csv 去重股票代码（≈全A历史，已证可加载）。"""
    import csv as c2
    path = "/app/data/profit_mining/events_labeled.csv"
    codes = set()
    with open(path, encoding="utf-8-sig") as f:
        for r in c2.DictReader(f):
            codes.add(r["股票代码"])
    return sorted(codes)


def _proc(code):
    df = _load_kline(code)
    if df is None or len(df) < 80:
        return {}
    return accumulate_stock(df, pcts=DEFAULT_PCTS, W=5)


def main():
    import sys, time, os
    from multiprocessing import Pool
    codes = _universe()
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    if limit:
        codes = codes[:limit]
    total = defaultdict(lambda: [0, 0, 0, 0, 0, 0])
    t0 = time.time()
    nproc = int(os.getenv("NPROC", "8"))
    with Pool(nproc) as p:
        for k, sc in enumerate(p.imap_unordered(_proc, codes, chunksize=20), 1):
            merge_counts(total, sc)
            if k % 500 == 0:
                print(f"  …{k}/{len(codes)}，{int(time.time()-t0)}s", flush=True)
    rows = finalize(dict(total))
    paths = write_reports(rows, out_dir="/app/report")
    print(f"[共性挖掘] 股票{len(codes)} 组合keys{len(rows)} 用时{int(time.time()-t0)}s", flush=True)
    for pth in paths:
        print("  写", pth, flush=True)


if __name__ == "__main__":
    main()
```

> 路径说明：容器 `/app/report` 挂载到宿主 `/home/tdxback/report`（与现有报告同位）。脚本经 `./data:/app/data` 挂载即时生效，**无需重建镜像**（与盘中化项目同款：data/profit_mining 下脚本即改即跑）。

- [ ] **Step 2: 语法自检**

Run: `cd data/profit_mining && python3 -c "import ast; ast.parse(open('mine_commonality.py').read()); print('SYNTAX OK')"`
Expected: `SYNTAX OK`

- [ ] **Step 3: Commit**

```bash
git add data/profit_mining/mine_commonality.py
git commit -m "feat: 全市场共性挖掘驱动 main(events股票池/多进程/写/app/report)"
```

---

### Task 9: 容器限量冒烟 + 全量跑

**Files:** 无（运行验证）

- [ ] **Step 1: 全套单测在容器回归**

Run:
```bash
for t in test_zigzag test_swing_samples test_param_signals test_mine_commonality; do
  docker exec -w /app/data/profit_mining agentsstock1 python3 $t.py || echo "FAIL $t"; done
```
Expected: 每个都 `ALL OK`，无 `FAIL`。

- [ ] **Step 2: 限量冒烟（前 30 只）**

Run: `docker exec -w /app agentsstock1 python3 /app/data/profit_mining/mine_commonality.py 30`
Expected: 打印 `[共性挖掘] 股票30 ...` 并列出写入的 CSV/md 路径（约 2 plan×2 side×3 pct=12 个 CSV + 1 md）。

- [ ] **Step 3: 核验产物**

Run: `ls -lt /home/tdxback/report/方案*共性* /home/tdxback/report/方案AB_共性横向对比_* | head`
Expected: 见到带时间戳的 CSV 与 md；`head -3` 任一 CSV 列头含 `coverage,lift,precision`。

- [ ] **Step 4: 全量跑（无 limit）**

Run: `docker exec -w /app agentsstock1 python3 /app/data/profit_mining/mine_commonality.py 2>&1 | tail -20`
Expected: 完成并写出全量报告。记录用时；若过慢可 `NPROC=16` 提速。

- [ ] **Step 5: 提交产物清单说明（不提交大CSV，仅记日志）**

人工查看 `方案AB_共性横向对比_*.md`，确认每档 ZigZag 下方案A/B 买卖向的最佳参数与覆盖/提升度合理（覆盖≥0.70 且提升度明显>1）。把结论回报用户，更新记忆。

---

## Self-Review

**Spec 覆盖核对：**
- §3.1 ZigZag(10/15/20%) → Task1 + Task6 `DEFAULT_PCTS` ✓
- §3.2 W=5 段命中/覆盖率 → Task2 窗口 + Task4 `count_for_signal`(段级seg_hit) ✓
- §3.3 斐波回踩/反弹(N/ratio/band) → Task3 `fib_support_hold`/`fib_resist_reject` ✓
- §3.4 BBI 上穿/跌破 → Task3 `bbi_cross_up/down` ✓
- §3.5 MACD 金叉/死叉 → Task3 `macd_golden/dead` ✓
- §3.6 方案A/B组合 → Task3 `plan_a_signal`/`plan_b_signal` ✓
- §4 参数网格 144/12 → Task3 `PLAN_A_GRID`/`PLAN_B_GRID`（测试断言数量）✓
- §2/§6 覆盖率/提升度/精确度 → Task5 `finalize` ✓
- §6 分档CSV+横向对比md，落 report 加时间戳 → Task7 `write_reports` ✓
- §5 复用 features.py MACD/BBI、本地K源、events股票池 → Task3 import F、Task8 `_load_kline`/`_universe` ✓
- §8 TDD合成序列单测 → Task1-7 每个均先写测试 ✓
- §9 不动缠论管线/不接前台/不发邮件 → 全部新文件，无改动既有脚本 ✓

**占位符扫描：** 无 TBD/TODO；每个代码步骤含完整代码。✓

**类型/签名一致性：**
- `count_for_signal` 返回 6 元组，`finalize`/`accumulate_stock`/`_merge` 均按 6 元处理 ✓
- key 统一 `(plan, side, pct, params)`，`finalize` 解包、`write_reports._expand_params` 按 plan 解 params ✓
- `plan_a_signal(df, N, ratio, band, fast, slow, signal, side)` 与 `PLAN_A_GRID` 6 元 params + `side=` 调用一致；`plan_b_signal(df, periods, fast, slow, signal, side)` 与 `PLAN_B_GRID` 4 元一致 ✓
- `positive_windows(high, low, pct, W)` 签名在 Task2 定义、Task6 `accumulate_stock` 调用一致 ✓
```
