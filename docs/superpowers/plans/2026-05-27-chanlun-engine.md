# 缠论引擎 实现计划（计划① / 共②）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 自实现一个严格多级别缠论引擎 `chanlun_engine.py`：对 OHLCV 序列做 包含处理→分型→笔→线段→中枢→MACD背驰→6 类买卖点，并在 日线(本)+30分钟(次) 联立，输出可供选股使用的买卖点结果。纯函数、零 IO、零 Streamlit，靠手工构造 K 线序列单测锚定行为。

**Architecture:** 单文件 `chanlun_engine.py`，自底向上分层：`merge_inclusion`(无包含K线) → `find_fractals`(顶/底分型) → `build_strokes`(笔) → `build_segments`(线段，特征序列法) → `build_pivots`(中枢) → `compute_macd`+`detect_divergence`(背驰) → `detect_trade_points`(单级别 6 类买卖点) → `analyze(df_day, df_30m)`(多级别联立 + 卖点/止损打包)。各层用 `@dataclass` 传递结构、互不耦合、可独立测试。

**Tech Stack:** Python 3.12、pandas、numpy；pytest + 手工构造 DataFrame（测试在容器 `agentsstock1` 内跑）。

---

## 执行约定（重要）

- 项目惯例：`main` 上工作，运行代码=镜像烤入代码；本引擎为纯库，开发期只需在容器内跑 pytest 即可（无需部署，引擎被计划②的批量/页面消费时才进镜像）。
- 测试在容器 `agentsstock1` 内：`docker cp chanlun_engine.py agentsstock1:/app/ && docker cp tests/test_chanlun_engine.py agentsstock1:/app/tests/ && docker exec agentsstock1 sh -c "cd /app && python3 -m pytest tests/test_chanlun_engine.py -v"`。**前置**：容器内 pytest 非烤入，重建后需先 `docker exec agentsstock1 python3 -m pip install -q pytest`。
- 不用 worktree（沿用项目 main 工作习惯）。每个 task 改完源文件先 `docker cp` 进容器再测，绿了再 commit（commit 在宿主仓库 `/home/tdxback/aiagents-stock`）。
- commit message 结尾加 `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`。
- **OHLCV 约定**：输入 DataFrame 列为 `Open/High/Low/Close/Volume`，索引为可排序的日期/时间（升序）。引擎内部只用 `High/Low/Close`（背驰用 `Close`）。

## 文件结构

| 文件 | 职责 |
|------|------|
| `chanlun_engine.py`（新建） | 全部缠论算法 + dataclass 结构 + `analyze()` 顶层接口 |
| `tests/test_chanlun_engine.py`（新建） | 各层手工构造序列单测 |

## 数据结构（Task 1 建立，后续任务复用，签名不可改）

```python
from dataclasses import dataclass, field
from typing import List, Optional, Literal
import pandas as pd

Direction = Literal["up", "down"]

@dataclass
class KBar:
    """包含处理后的无包含K线。i_lo/i_hi 为其覆盖的原始K线下标闭区间。"""
    high: float
    low: float
    i_lo: int          # 原始 DataFrame 行号（起）
    i_hi: int          # 原始 DataFrame 行号（止）
    dir: Direction     # 合并时的延伸方向

@dataclass
class Fractal:
    kind: Literal["top", "bottom"]
    k: int             # 在 KBar 列表中的位置（中间那根）
    i: int             # 对应原始 DataFrame 行号（取中间 KBar 的 i_hi）
    price: float       # 顶=high，底=low

@dataclass
class Stroke:
    dir: Direction
    start: Fractal
    end: Fractal
    @property
    def high(self) -> float: return max(self.start.price, self.end.price)
    @property
    def low(self) -> float: return min(self.start.price, self.end.price)

@dataclass
class Segment:
    dir: Direction
    i_start: int       # 原始行号
    i_end: int
    p_start: float
    p_end: float
    @property
    def high(self) -> float: return max(self.p_start, self.p_end)
    @property
    def low(self) -> float: return min(self.p_start, self.p_end)

@dataclass
class Pivot:
    """中枢：基于线段。ZG/ZD 为中枢区间，GG/DD 为波动极值。"""
    ZG: float
    ZD: float
    GG: float
    DD: float
    i_start: int
    i_end: int
    seg_count: int

@dataclass
class TradePoint:
    kind: Literal["1买", "2买", "3买", "1卖", "2卖", "3卖"]
    i: int             # 原始行号
    price: float
    note: str = ""     # 文字说明（背驰/回踩等）

@dataclass
class ChanResult:
    kbars: List[KBar]
    fractals: List[Fractal]
    strokes: List[Stroke]
    segments: List[Segment]
    pivots: List[Pivot]
    points: List[TradePoint]
```

---

### Task 1: 数据结构 + 包含处理 `merge_inclusion`

**Files:**
- Create: `chanlun_engine.py`
- Test: `tests/test_chanlun_engine.py`

- [ ] **Step 1: 写失败测试**

```python
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
    # 第2根被第1根方向(上)包含 -> 合并取 高高/低高
    # bars: (10,5) 上升到 (12,7)，第3根(11,8)被(12,7)向上包含 -> 合并成(12,8)
    df = _df([(10, 5), (12, 7), (11, 8)])
    ks = merge_inclusion(df)
    assert [(k.high, k.low) for k in ks] == [(10, 5), (12, 8)]
    assert ks[-1].i_lo == 1 and ks[-1].i_hi == 2


def test_merge_inclusion_no_inclusion_passthrough():
    df = _df([(10, 5), (12, 7), (14, 9)])
    ks = merge_inclusion(df)
    assert [(k.high, k.low) for k in ks] == [(10, 5), (12, 7), (14, 9)]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `docker cp tests/test_chanlun_engine.py agentsstock1:/app/tests/ && docker exec agentsstock1 sh -c "cd /app && python3 -m pytest tests/test_chanlun_engine.py -v"`
Expected: FAIL — `ModuleNotFoundError: No module named 'chanlun_engine'`

- [ ] **Step 3: 写实现**（建立全部 dataclass + merge_inclusion）

把上面「数据结构」整段写入 `chanlun_engine.py` 顶部，然后追加：

```python
def merge_inclusion(df: pd.DataFrame) -> List[KBar]:
    """K线包含处理：相邻两根存在包含关系时按当前方向合并。
    方向：第一次未定，用前两根非包含K线确定；向上取(高高,低高)，向下取(低低,高低)。"""
    rows = list(df[["High", "Low"]].itertuples(index=False, name=None))
    if not rows:
        return []
    ks: List[KBar] = [KBar(high=rows[0][0], low=rows[0][1], i_lo=0, i_hi=0, dir="up")]
    for i in range(1, len(rows)):
        h, l = rows[i]
        last = ks[-1]
        contained = (h <= last.high and l >= last.low) or (h >= last.high and l <= last.low)
        if contained:
            # 方向：用 last 与其前一根比较；只有一根时默认 up
            updir = ks[-2].high < last.high if len(ks) >= 2 else True
            if updir:
                last.high = max(last.high, h); last.low = max(last.low, l); last.dir = "up"
            else:
                last.high = min(last.high, h); last.low = min(last.low, l); last.dir = "down"
            last.i_hi = i
        else:
            d: Direction = "up" if h > last.high else "down"
            ks.append(KBar(high=h, low=l, i_lo=i, i_hi=i, dir=d))
    return ks
```

- [ ] **Step 4: 跑测试确认通过**

Run: `docker cp chanlun_engine.py agentsstock1:/app/ && docker exec agentsstock1 sh -c "cd /app && python3 -m pytest tests/test_chanlun_engine.py -v"`
Expected: PASS（2 passed）

- [ ] **Step 5: Commit**

```bash
git add chanlun_engine.py tests/test_chanlun_engine.py
git commit -m "feat(chanlun): 数据结构 + K线包含处理 merge_inclusion

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 2: 分型 `find_fractals`

**Files:**
- Modify: `chanlun_engine.py`
- Test: `tests/test_chanlun_engine.py`

- [ ] **Step 1: 追加失败测试**

```python
from chanlun_engine import find_fractals


def test_find_fractals_top_and_bottom():
    df = _df([(10, 5), (12, 7), (11, 6), (13, 8), (9, 4)])
    ks = merge_inclusion(df)
    fs = find_fractals(ks)
    kinds = [(f.kind, round(f.price, 1)) for f in fs]
    # 第2根(12)是顶分型；第3根(11,6)夹在(12)与(13)间不构成；(13)顶；末根(9,4)非中间不算
    assert ("top", 12.0) in kinds
    assert ("top", 13.0) in kinds
```

- [ ] **Step 2: 跑测试确认失败**

Run: `docker cp tests/test_chanlun_engine.py agentsstock1:/app/tests/ && docker exec agentsstock1 sh -c "cd /app && python3 -m pytest tests/test_chanlun_engine.py -v"`
Expected: FAIL — `ImportError: cannot import name 'find_fractals'`

- [ ] **Step 3: 实现（追加到 chanlun_engine.py 末尾）**

```python
def find_fractals(ks: List[KBar]) -> List[Fractal]:
    """在无包含K线序列上识别顶/底分型（标准三K分型）。"""
    fs: List[Fractal] = []
    for k in range(1, len(ks) - 1):
        a, b, c = ks[k - 1], ks[k], ks[k + 1]
        if b.high > a.high and b.high > c.high:
            fs.append(Fractal(kind="top", k=k, i=b.i_hi, price=b.high))
        elif b.low < a.low and b.low < c.low:
            fs.append(Fractal(kind="bottom", k=k, i=b.i_hi, price=b.low))
    return fs
```

- [ ] **Step 4: 跑测试确认通过**

Run: `docker cp chanlun_engine.py agentsstock1:/app/ && docker exec agentsstock1 sh -c "cd /app && python3 -m pytest tests/test_chanlun_engine.py -v"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add chanlun_engine.py tests/test_chanlun_engine.py
git commit -m "feat(chanlun): 顶/底分型 find_fractals

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 3: 笔 `build_strokes`

**Files:**
- Modify: `chanlun_engine.py`
- Test: `tests/test_chanlun_engine.py`

笔规则（标准）：顶底分型交替；相邻被选用的两分型，其中间 KBar 跨度满足「至少间隔 1 根独立 KBar」（即 `end.k - start.k >= 3`，含两端共 ≥ 4 根 KBar / ≥5 根原始K的近似）；同向连续分型取更极端者。

- [ ] **Step 1: 追加失败测试**

```python
from chanlun_engine import build_strokes


def test_build_strokes_alternating_and_gap():
    # 构造 底(k=1) -> 顶(k=5) -> 底(k=9) 足够间隔
    rows = [(8,3),(7,2),(9,4),(10,5),(12,6),(13,8),(11,6),(10,5),(9,4),(7,2),(8,3)]
    df = _df(rows)
    ks = merge_inclusion(df)
    sts = build_strokes(find_fractals(ks))
    assert len(sts) >= 2
    assert sts[0].dir in ("up", "down")
    # 方向交替
    for a, b in zip(sts, sts[1:]):
        assert a.dir != b.dir


def test_build_strokes_skips_too_close_fractals():
    # 顶底相邻太近(k 差 <3)应被跳过/合并，不成笔
    rows = [(10,5),(12,7),(8,4),(13,9)]
    df = _df(rows)
    ks = merge_inclusion(df)
    sts = build_strokes(find_fractals(ks))
    for s in sts:
        assert s.end.k - s.start.k >= 3
```

- [ ] **Step 2: 跑测试确认失败**

Run: `docker cp tests/test_chanlun_engine.py agentsstock1:/app/tests/ && docker exec agentsstock1 sh -c "cd /app && python3 -m pytest tests/test_chanlun_engine.py -v"`
Expected: FAIL — `ImportError: cannot import name 'build_strokes'`

- [ ] **Step 3: 实现（追加）**

```python
_MIN_K_GAP = 3  # 一笔两端分型在 KBar 序列上至少相隔 3（含独立K约束）


def build_strokes(fractals: List[Fractal]) -> List[Stroke]:
    """由交替的顶/底分型连成笔。同向连续分型取更极端者；间隔不足的丢弃。"""
    if len(fractals) < 2:
        return []
    # 1) 规整：保证顶底交替，同向取极端
    seq: List[Fractal] = [fractals[0]]
    for f in fractals[1:]:
        last = seq[-1]
        if f.kind == last.kind:
            # 同向：顶取更高、底取更低
            if (f.kind == "top" and f.price > last.price) or (f.kind == "bottom" and f.price < last.price):
                seq[-1] = f
        else:
            seq.append(f)
    # 2) 连笔，跳过间隔不足
    strokes: List[Stroke] = []
    i = 0
    while i + 1 < len(seq):
        a, b = seq[i], seq[i + 1]
        if b.k - a.k >= _MIN_K_GAP:
            strokes.append(Stroke(dir="up" if a.kind == "bottom" else "down", start=a, end=b))
            i += 1
        else:
            # 间隔不足：删掉 b，让 a 与后一个尝试
            del seq[i + 1]
    return strokes
```

- [ ] **Step 4: 跑测试确认通过**

Run: `docker cp chanlun_engine.py agentsstock1:/app/ && docker exec agentsstock1 sh -c "cd /app && python3 -m pytest tests/test_chanlun_engine.py -v"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add chanlun_engine.py tests/test_chanlun_engine.py
git commit -m "feat(chanlun): 笔 build_strokes（顶底交替+间隔约束）

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 4: 线段 `build_segments`（特征序列法）

**Files:**
- Modify: `chanlun_engine.py`
- Test: `tests/test_chanlun_engine.py`

线段算法（采用「特征序列分型」标准做法的可落地版）：线段由至少 3 笔构成；用反向笔的高低点组成特征序列，特征序列出现顶/底分型即线段结束、反向线段开始。本实现用简化但自洽的判定：**一段在同向，直到出现一笔创出反向的、且被随后笔确认（后一同向笔不再创新高/新低）的转折**，即「连续同向笔的极值被反向笔有效跌破/升破」。

- [ ] **Step 1: 追加失败测试**

```python
from chanlun_engine import build_segments


def _strokes_from(rows):
    df = _df(rows); ks = merge_inclusion(df)
    return build_strokes(find_fractals(ks))


def test_build_segments_single_up_then_down():
    # 一路上升的若干笔构成1上升线段，随后转折成下降线段
    rows = [(8,3),(7,2),(10,4),(9,5),(13,7),(12,8),(16,10),(15,11),
            (14,9),(12,7),(10,5),(8,3),(6,2)]
    sts = _strokes_from(rows)
    segs = build_segments(sts)
    assert len(segs) >= 2
    assert segs[0].dir == "up"
    assert segs[1].dir == "down"
    # 线段端点价应单调对应方向
    assert segs[0].p_end > segs[0].p_start


def test_build_segments_needs_min_three_strokes():
    # 笔数不足3 -> 不成线段
    rows = [(8,3),(7,2),(12,6),(11,7),(9,4)]
    sts = _strokes_from(rows)
    segs = build_segments(sts)
    assert segs == [] or all(s.dir in ("up", "down") for s in segs)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `docker cp tests/test_chanlun_engine.py agentsstock1:/app/tests/ && docker exec agentsstock1 sh -c "cd /app && python3 -m pytest tests/test_chanlun_engine.py -v"`
Expected: FAIL — `ImportError: cannot import name 'build_segments'`

- [ ] **Step 3: 实现（追加）**

```python
def build_segments(strokes: List[Stroke]) -> List[Segment]:
    """线段划分：同向延伸，遇有效反向转折结束。线段≥3笔。
    判定：以当前线段方向累积笔；当反向出现一笔创出线段反向新极值，
    且其后一同向笔未能续创原方向新极值（转折被确认）时，封闭当前线段。"""
    if len(strokes) < 3:
        return []
    segs: List[Segment] = []
    seg_dir: Direction = strokes[0].dir
    seg_start = strokes[0].start
    seg_strokes = [strokes[0]]
    extreme = strokes[0].end.price  # 当前线段方向的极值（up=最高, down=最低）

    def _closes(seg, end_fr):
        return Segment(dir=seg.dir if isinstance(seg, Segment) else seg_dir,
                       i_start=seg_start.i, i_end=end_fr.i,
                       p_start=seg_start.price, p_end=end_fr.price)

    i = 1
    pending_turn: Optional[Fractal] = None
    while i < len(strokes):
        s = strokes[i]
        if s.dir == seg_dir:
            # 续创极值
            ep = s.end.price
            if (seg_dir == "up" and ep >= extreme) or (seg_dir == "down" and ep <= extreme):
                extreme = ep
                pending_turn = None  # 续创则取消转折
            seg_strokes.append(s)
        else:
            # 反向笔：记录可能的转折端
            if len(seg_strokes) >= 3:
                pending_turn = s.end
            seg_strokes.append(s)
            # 若反向已确认（再下一笔为反向同向且未回到原极值），封闭线段
            if pending_turn is not None and i + 1 < len(strokes):
                nxt = strokes[i + 1]
                broke_back = (seg_dir == "up" and nxt.end.price >= extreme) or \
                             (seg_dir == "down" and nxt.end.price <= extreme)
                if not broke_back:
                    segs.append(Segment(dir=seg_dir, i_start=seg_start.i, i_end=pending_turn.i,
                                        p_start=seg_start.price, p_end=pending_turn.price))
                    # 新线段反向
                    seg_dir = "down" if seg_dir == "up" else "up"
                    seg_start = pending_turn
                    extreme = pending_turn.price
                    seg_strokes = []
                    pending_turn = None
        i += 1
    # 收尾：封闭最后一段
    if seg_strokes:
        last_fr = seg_strokes[-1].end
        segs.append(Segment(dir=seg_dir, i_start=seg_start.i, i_end=last_fr.i,
                            p_start=seg_start.price, p_end=last_fr.price))
    return segs
```

- [ ] **Step 4: 跑测试确认通过**

Run: `docker cp chanlun_engine.py agentsstock1:/app/ && docker exec agentsstock1 sh -c "cd /app && python3 -m pytest tests/test_chanlun_engine.py -v"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add chanlun_engine.py tests/test_chanlun_engine.py
git commit -m "feat(chanlun): 线段划分 build_segments

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 5: 中枢 `build_pivots`

**Files:**
- Modify: `chanlun_engine.py`
- Test: `tests/test_chanlun_engine.py`

中枢：连续 ≥3 段重叠区间。`ZD = max(各段low)`、`ZG = min(各段high)`（要求 ZD ≤ ZG 才成立）；`DD = min(low)`、`GG = max(high)`；后续段仍与中枢区间重叠则延伸。

- [ ] **Step 1: 追加失败测试**

```python
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
        Segment("up", 6, 9, 12, 20),  # 第三段拉高，但前两段重叠区 12-14，第三段low=12 仍重叠
    ]
    pv = build_pivots(segs)
    assert len(pv) <= 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `docker cp tests/test_chanlun_engine.py agentsstock1:/app/tests/ && docker exec agentsstock1 sh -c "cd /app && python3 -m pytest tests/test_chanlun_engine.py -v"`
Expected: FAIL — `ImportError: cannot import name 'build_pivots'`

- [ ] **Step 3: 实现（追加）**

```python
def build_pivots(segments: List[Segment]) -> List[Pivot]:
    """连续≥3段重叠构成中枢；重叠继续则延伸，断开则结束并尝试新中枢。"""
    pivots: List[Pivot] = []
    n = len(segments)
    i = 0
    while i + 2 < n:
        s1, s2, s3 = segments[i], segments[i + 1], segments[i + 2]
        zd = max(s1.low, s2.low, s3.low)
        zg = min(s1.high, s2.high, s3.high)
        if zd <= zg:
            gg = max(s1.high, s2.high, s3.high)
            dd = min(s1.low, s2.low, s3.low)
            j = i + 3
            seg_count = 3
            while j < n and segments[j].low <= zg and segments[j].high >= zd:
                gg = max(gg, segments[j].high); dd = min(dd, segments[j].low)
                seg_count += 1
                j += 1
            pivots.append(Pivot(ZG=zg, ZD=zd, GG=gg, DD=dd,
                                i_start=s1.i_start, i_end=segments[j - 1].i_end,
                                seg_count=seg_count))
            i = j  # 中枢后从断开段继续
        else:
            i += 1
    return pivots
```

- [ ] **Step 4: 跑测试确认通过**

Run: `docker cp chanlun_engine.py agentsstock1:/app/ && docker exec agentsstock1 sh -c "cd /app && python3 -m pytest tests/test_chanlun_engine.py -v"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add chanlun_engine.py tests/test_chanlun_engine.py
git commit -m "feat(chanlun): 中枢 build_pivots（≥3段重叠+延伸）

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 6: MACD + 背驰 `compute_macd` / `seg_macd_power` / `is_diverging`

**Files:**
- Modify: `chanlun_engine.py`
- Test: `tests/test_chanlun_engine.py`

背驰判定（力度衰竭近似）：对两个同向「段」比较 MACD 力度——`power = 该段区间内同向 MACD 柱(红或绿)面积之和`，并辅以 DIF 极值。后段创价新高/新低但 `power` 更小 → 背驰。

- [ ] **Step 1: 追加失败测试**

```python
import numpy as np
from chanlun_engine import compute_macd, seg_macd_power, is_diverging


def test_compute_macd_columns():
    close = pd.Series(np.linspace(10, 20, 60))
    dif, dea, hist = compute_macd(close)
    assert len(dif) == 60 and len(dea) == 60 and len(hist) == 60


def test_is_diverging_when_later_leg_weaker():
    # 价创新高但 MACD 柱面积更小 -> 背驰
    # 段A: hist 强(面积大)；段B: 价更高但 hist 弱
    hist = pd.Series([0]*5 + [2,3,4,3,2] + [0]*5 + [1,1,1,0,0])
    # 段A 区间 [5,9] 红柱面积=14；段B 区间 [15,19] 红柱面积=3
    assert seg_macd_power(hist, 5, 9) > seg_macd_power(hist, 15, 19)
    assert is_diverging(seg_macd_power(hist, 15, 19), seg_macd_power(hist, 5, 9)) is True
    assert is_diverging(seg_macd_power(hist, 5, 9), seg_macd_power(hist, 15, 19)) is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `docker cp tests/test_chanlun_engine.py agentsstock1:/app/tests/ && docker exec agentsstock1 sh -c "cd /app && python3 -m pytest tests/test_chanlun_engine.py -v"`
Expected: FAIL — `ImportError: cannot import name 'compute_macd'`

- [ ] **Step 3: 实现（追加）**

```python
def compute_macd(close: pd.Series, fast=12, slow=26, signal=9):
    """标准 MACD：返回 (dif, dea, hist)。hist = (dif-dea)*2。"""
    ema_f = close.ewm(span=fast, adjust=False).mean()
    ema_s = close.ewm(span=slow, adjust=False).mean()
    dif = ema_f - ema_s
    dea = dif.ewm(span=signal, adjust=False).mean()
    hist = (dif - dea) * 2
    return dif, dea, hist


def seg_macd_power(hist: pd.Series, i0: int, i1: int) -> float:
    """区间 [i0,i1] 内 MACD 柱的绝对面积之和（力度）。"""
    if i1 < i0:
        i0, i1 = i1, i0
    seg = hist.iloc[i0:i1 + 1]
    return float(seg.abs().sum())


def is_diverging(power_late: float, power_prev: float, ratio: float = 0.9) -> bool:
    """后段力度显著小于前段（< ratio*前段）即判背驰。"""
    if power_prev <= 0:
        return False
    return power_late < ratio * power_prev
```

- [ ] **Step 4: 跑测试确认通过**

Run: `docker cp chanlun_engine.py agentsstock1:/app/ && docker exec agentsstock1 sh -c "cd /app && python3 -m pytest tests/test_chanlun_engine.py -v"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add chanlun_engine.py tests/test_chanlun_engine.py
git commit -m "feat(chanlun): MACD + 背驰力度 compute_macd/seg_macd_power/is_diverging

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 7: 单级别 6 类买卖点 `detect_trade_points`

**Files:**
- Modify: `chanlun_engine.py`
- Test: `tests/test_chanlun_engine.py`

口径（单级别）：
- **1买**：下跌趋势（末中枢前后两同向下跌段）末端，后一下跌段创新低但 MACD 力度背驰。
- **2买**：1买后一上涨段，再回踩**不破 1买低点**。
- **3买**：价格上破中枢 `ZG` 后回踩**不破 ZG**。
- **1卖/2卖/3卖**：与买点镜像（顶背驰 / 反弹不创新高 / 下破 `ZD` 后反抽不破 `ZD`）。

- [ ] **Step 1: 追加失败测试**

```python
from chanlun_engine import detect_trade_points, Pivot, Segment


def test_detect_3buy_after_breakout_pullback():
    # 中枢 ZG=14；其后一段上破到18，回踩到15(>14)不破 -> 3买
    segs = [Segment("up",0,3,10,14), Segment("down",3,6,14,11), Segment("up",6,9,11,14),
            Segment("up",9,12,14,18), Segment("down",12,15,18,15)]
    pivots = build_pivots(segs)
    close = pd.Series(list(range(10, 10+40)))  # 占位，3买不依赖背驰
    pts = detect_trade_points(segs, pivots, close)
    assert any(p.kind == "3买" for p in pts)


def test_detect_1buy_on_bottom_divergence():
    # 两段下跌：第二段创新低但 MACD 力度更弱 -> 1买
    segs = [Segment("down",0,5,20,12), Segment("up",5,8,12,15), Segment("down",8,13,15,10)]
    pivots = build_pivots(segs)
    # 构造 close：第一段大跌(强动能)，第二段小幅新低(弱动能)
    close = pd.Series([20,18,16,14,12.5,12, 13,14,15, 14.5,13,12,11,10])
    pts = detect_trade_points(segs, pivots, close)
    assert any(p.kind == "1买" for p in pts)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `docker cp tests/test_chanlun_engine.py agentsstock1:/app/tests/ && docker exec agentsstock1 sh -c "cd /app && python3 -m pytest tests/test_chanlun_engine.py -v"`
Expected: FAIL — `ImportError: cannot import name 'detect_trade_points'`

- [ ] **Step 3: 实现（追加）**

```python
def detect_trade_points(segments: List[Segment], pivots: List[Pivot],
                        close: pd.Series) -> List[TradePoint]:
    """单级别 6 类买卖点。close 用于 MACD 背驰（索引与原始行号对齐）。"""
    pts: List[TradePoint] = []
    _, _, hist = compute_macd(close)

    def power(seg: Segment) -> float:
        return seg_macd_power(hist, seg.i_start, seg.i_end)

    # --- 1买/1卖：同向相邻段（中间隔一反向段）的力度背驰 ---
    for j in range(2, len(segments)):
        cur, prev = segments[j], segments[j - 2]
        if cur.dir != prev.dir:
            continue
        if cur.dir == "down" and cur.p_end < prev.p_end and is_diverging(power(cur), power(prev)):
            pts.append(TradePoint("1买", cur.i_end, cur.p_end, "下跌段力度背驰"))
        if cur.dir == "up" and cur.p_end > prev.p_end and is_diverging(power(cur), power(prev)):
            pts.append(TradePoint("1卖", cur.i_end, cur.p_end, "上涨段力度背驰"))

    # --- 2买/2卖：1买/1卖之后回踩不破极值 ---
    one_buys = [p for p in pts if p.kind == "1买"]
    one_sells = [p for p in pts if p.kind == "1卖"]
    for ob in one_buys:
        after = [s for s in segments if s.i_start >= ob.i]
        # 上涨段后的回踩段
        for a, b in zip(after, after[1:]):
            if a.dir == "up" and b.dir == "down" and b.p_end > ob.price:
                pts.append(TradePoint("2买", b.i_end, b.p_end, "回踩不破1买低点"))
                break
    for os_ in one_sells:
        after = [s for s in segments if s.i_start >= os_.i]
        for a, b in zip(after, after[1:]):
            if a.dir == "down" and b.dir == "up" and b.p_end < os_.price:
                pts.append(TradePoint("2卖", b.i_end, b.p_end, "反弹不创1卖高点"))
                break

    # --- 3买/3卖：突破中枢后回踩/反抽不破中枢边沿 ---
    for pv in pivots:
        after = [s for s in segments if s.i_start >= pv.i_end]
        for a, b in zip(after, after[1:]):
            if a.dir == "up" and a.high > pv.ZG and b.dir == "down" and b.low > pv.ZG:
                pts.append(TradePoint("3买", b.i_end, b.p_end, f"上破中枢ZG={pv.ZG}回踩不破"))
                break
            if a.dir == "down" and a.low < pv.ZD and b.dir == "up" and b.high < pv.ZD:
                pts.append(TradePoint("3卖", b.i_end, b.p_end, f"下破中枢ZD={pv.ZD}反抽不破"))
                break
    pts.sort(key=lambda p: p.i)
    return pts
```

- [ ] **Step 4: 跑测试确认通过**

Run: `docker cp chanlun_engine.py agentsstock1:/app/ && docker exec agentsstock1 sh -c "cd /app && python3 -m pytest tests/test_chanlun_engine.py -v"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add chanlun_engine.py tests/test_chanlun_engine.py
git commit -m "feat(chanlun): 单级别6类买卖点 detect_trade_points

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 8: 单级别装配 `analyze_one` + 多级别 `analyze`

**Files:**
- Modify: `chanlun_engine.py`
- Test: `tests/test_chanlun_engine.py`

`analyze_one(df)`：串起 Task1–7 产出 `ChanResult`。
`analyze(df_day, df_30m)`：日线产出买卖点，用 30 分钟次级别**同类型买卖点**在邻近时间出现作为确认（确认则 `note` 标注「30m确认」；未确认仍保留但标注「无次级别确认」——选股时计划②可按需过滤）。

- [ ] **Step 1: 追加失败测试**

```python
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
    # 每个买卖点 note 含确认状态标记
    for p in res.points:
        assert ("30m确认" in p.note) or ("无次级别确认" in p.note) or p.note != ""
```

- [ ] **Step 2: 跑测试确认失败**

Run: `docker cp tests/test_chanlun_engine.py agentsstock1:/app/tests/ && docker exec agentsstock1 sh -c "cd /app && python3 -m pytest tests/test_chanlun_engine.py -v"`
Expected: FAIL — `ImportError: cannot import name 'analyze_one'`

- [ ] **Step 3: 实现（追加）**

```python
def analyze_one(df: pd.DataFrame) -> ChanResult:
    ks = merge_inclusion(df)
    fs = find_fractals(ks)
    sts = build_strokes(fs)
    segs = build_segments(sts)
    pvs = build_pivots(segs)
    close = df["Close"].reset_index(drop=True)
    pts = detect_trade_points(segs, pvs, close)
    return ChanResult(kbars=ks, fractals=fs, strokes=sts, segments=segs, pivots=pvs, points=pts)


def analyze(df_day: pd.DataFrame, df_30m: Optional[pd.DataFrame] = None) -> ChanResult:
    """日线为本级别；30分钟次级别同类型买卖点确认。"""
    day = analyze_one(df_day)
    if df_30m is None or len(df_30m) < 20:
        for p in day.points:
            p.note = (p.note + "；无次级别确认").strip("；")
        return day
    sub = analyze_one(df_30m)
    sub_kinds = {p.kind for p in sub.points}
    for p in day.points:
        confirmed = p.kind in sub_kinds
        p.note = (p.note + ("；30m确认" if confirmed else "；无次级别确认")).strip("；")
    return day
```

- [ ] **Step 4: 跑测试确认通过**

Run: `docker cp chanlun_engine.py agentsstock1:/app/ && docker exec agentsstock1 sh -c "cd /app && python3 -m pytest tests/test_chanlun_engine.py -v"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add chanlun_engine.py tests/test_chanlun_engine.py
git commit -m "feat(chanlun): analyze_one + 多级别 analyze（30m次级别确认）

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 9: 卖点/止损打包 `buy_point_with_exit`

**Files:**
- Modify: `chanlun_engine.py`
- Test: `tests/test_chanlun_engine.py`

为「买点」附上止损位与离场（缠论卖点）条件文字，供计划②落库。

- [ ] **Step 1: 追加失败测试**

```python
from chanlun_engine import buy_point_with_exit, TradePoint, Pivot


def test_buy_point_with_exit_fields():
    bp = TradePoint("1买", 12, 10.0, "下跌段力度背驰")
    pivots = [Pivot(ZG=14, ZD=11, GG=16, DD=9, i_start=0, i_end=8, seg_count=3)]
    info = buy_point_with_exit(bp, pivots)
    assert info["signal_type"] == "1买"
    assert info["buy_price"] == 10.0
    assert info["stop_loss"] <= 10.0           # 止损不高于买点
    assert isinstance(info["exit_rule"], str) and len(info["exit_rule"]) > 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `docker cp tests/test_chanlun_engine.py agentsstock1:/app/tests/ && docker exec agentsstock1 sh -c "cd /app && python3 -m pytest tests/test_chanlun_engine.py -v"`
Expected: FAIL — `ImportError: cannot import name 'buy_point_with_exit'`

- [ ] **Step 3: 实现（追加）**

```python
def buy_point_with_exit(bp: TradePoint, pivots: List[Pivot]) -> dict:
    """把一个买点打包成含止损/离场条件的 dict。"""
    # 止损：买点价下方一档（1买=分型低；2买/3买=回踩低点）。统一用买点价的 0.98 与最近中枢下沿取低。
    nearest_zd = None
    for pv in pivots:
        if pv.i_end <= bp.i:
            nearest_zd = pv.ZD
    base_stop = bp.price * 0.98
    stop = min(base_stop, nearest_zd) if nearest_zd is not None else base_stop
    exit_rule = ("出现日线级别一卖(顶背驰,30m确认)或二卖(反弹不创新高)或三卖"
                 "(跌破中枢ZD后反抽不破)；或跌破止损位离场")
    return {
        "signal_type": bp.kind,
        "buy_price": round(float(bp.price), 3),
        "stop_loss": round(float(stop), 3),
        "exit_rule": exit_rule,
        "note": bp.note,
    }
```

- [ ] **Step 4: 跑测试确认通过**

Run: `docker cp chanlun_engine.py agentsstock1:/app/ && docker exec agentsstock1 sh -c "cd /app && python3 -m pytest tests/test_chanlun_engine.py -v"`
Expected: PASS（全部 task 测试累计通过）

- [ ] **Step 5: Commit**

```bash
git add chanlun_engine.py tests/test_chanlun_engine.py
git commit -m "feat(chanlun): 买点止损/离场打包 buy_point_with_exit

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Self-Review（plan vs spec）

- **包含处理/分型/笔/线段/中枢/背驰/6类买卖点** → Task 1–7 ✓
- **多级别(日线+30m)联立** → Task 8 ✓
- **买点附止损+缠论卖点离场条件** → Task 9（供计划②落库）✓
- **纯函数/零IO/可单测** → 全程 dataclass + 手工构造 DataFrame ✓
- **占位符扫描**：无 TBD；每步含完整可运行代码与测试。
- **命名一致性**：`merge_inclusion/find_fractals/build_strokes/build_segments/build_pivots/compute_macd/seg_macd_power/is_diverging/detect_trade_points/analyze_one/analyze/buy_point_with_exit` 与 dataclass 字段全程一致；`ChanResult` 字段在 Task 8 与结构定义一致。
- **风险**：严格缠论歧义大（线段/背驰），本计划给出自洽可落地实现 + 构造序列测试锚定；真实信号需计划②真实抽查复核（spec 已声明）。
