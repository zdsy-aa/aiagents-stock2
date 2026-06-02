# 核心/精选层 5★ 分级 · 阶段一回测标定 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在全历史 1 买信号上回测"合成分→样本外胜率"，给核心/精选两层各自定出固定星级阈值（诚实降档），产出 `star_thresholds.json` + 验证报告，供阶段二落地前台。

**Architecture:** 新增一个**纯标准库、可在宿主机直接运行**的脚本 `star_calibrate.py`，读已生成的 `signal_features.csv`（97329 买点，含 `是否盈利`/`区间涨跌幅` 及全部 K 线特征）。复刻 `daily_watchlist` 的层级判定（核心/精选只对 1 买、非陷阱、量能金叉与否），在训练段（≤2023）按特征的样本外胜率增量定权重→合成分→等频切档（要求训练胜率单调、每档样本足够，否则诚实降档），再在样本外段（2024~2025-10）验证胜率单调性，固化阈值并出报告。所有核心逻辑是纯函数，便于 TDD。

**Tech Stack:** Python 3 标准库（`csv`/`json`/`os`/`datetime`），pytest 单测。无 pandas、无 docker、无 akshare 依赖。

---

## 文件结构

| 文件 | 责任 |
|---|---|
| `data/profit_mining/star_calibrate.py`（新增） | 全部标定逻辑：层级重建、特征分箱、权重拟合、分档、样本外评估、产出 json + 报告。纯函数 + `main()`。 |
| `data/profit_mining/test_star_calibrate.py`（新增） | 对纯函数的单元测试，宿主机 pytest 直接跑，不触碰大 CSV。 |
| `data/profit_mining/star_thresholds.json`（运行产物） | 固化的每层权重 + 切点 + 各档训练/样本外胜率。 |
| `/home/tdxback/report/star_calibration_report_<TS>.md`（运行产物） | 人读验证报告（每层每档：样本数 / ≥4%胜率 / +10%大涨率 / 单调性 / 实际档数）。 |

**关键常量（写进 `star_calibrate.py` 顶部）：**

```python
WIN_THRESH = 4.0          # 主口径：区间涨跌幅 >= 4% 记为盈利
BIGRISE_THRESH = 10.0     # 辅口径：区间涨跌幅 >= 10% 记为大涨
TRAIN_END = "2023-12-31"  # walk-forward 训练段截止
OOS_START, OOS_END = "2024-01-01", "2025-10-31"  # 样本外段(完整前向窗,排除2026截断标签)
MIN_BUCKET_N = 200        # 每星档最小样本数
MAX_STARS = 5
BINARY_FEATS = ["极限抄底", "中枢极限底", "中枢底部回升"]   # 0/1 特征
# 连续特征分箱(0/1/2 档)：见 Task 2
```

---

### Task 1: 层级重建 `is_trap` / `reconstruct_tier`（纯函数）

**Files:**
- Create: `data/profit_mining/star_calibrate.py`
- Test: `data/profit_mining/test_star_calibrate.py`

- [ ] **Step 1: 写失败测试**

写入 `data/profit_mining/test_star_calibrate.py`：

```python
import star_calibrate as sc


def test_is_trap_dapan_bull():
    # 大盘多头 → 陷阱(精选层失效)
    assert sc.is_trap({"大盘多头": "1", "相对强弱": "-3"}) is True


def test_is_trap_relstr_nonneg():
    # 相对强弱 >= 0 → 陷阱(超跌反弹转强反失效)
    assert sc.is_trap({"大盘多头": "0", "相对强弱": "0.5"}) is True


def test_is_trap_false():
    assert sc.is_trap({"大盘多头": "0", "相对强弱": "-4"}) is False


def test_reconstruct_tier_core():
    # 1买 + 非陷阱 + 量能金叉 → 核心
    row = {"买点类型": "1买", "大盘多头": "0", "相对强弱": "-4", "量能金叉": "1"}
    assert sc.reconstruct_tier(row) == "核心"


def test_reconstruct_tier_refined():
    # 1买 + 非陷阱 + 无量能金叉 → 精选
    row = {"买点类型": "1买", "大盘多头": "0", "相对强弱": "-4", "量能金叉": "0"}
    assert sc.reconstruct_tier(row) == "精选"


def test_reconstruct_tier_none_when_not_first_buy():
    row = {"买点类型": "2买", "大盘多头": "0", "相对强弱": "-4", "量能金叉": "1"}
    assert sc.reconstruct_tier(row) is None


def test_reconstruct_tier_none_when_trap():
    row = {"买点类型": "1买", "大盘多头": "1", "相对强弱": "-4", "量能金叉": "1"}
    assert sc.reconstruct_tier(row) is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /home/tdxback/aiagents-stock/data/profit_mining && python3 -m pytest test_star_calibrate.py -v`
Expected: FAIL —`ModuleNotFoundError: No module named 'star_calibrate'`。

- [ ] **Step 3: 写最小实现**

新建 `data/profit_mining/star_calibrate.py`，写入文件头常量与这两个函数：

```python
# star_calibrate.py —— 阶段一：全历史1买信号回测"合成分→样本外胜率"，
# 给核心/精选两层各自定固定星级阈值(诚实降档)，产出 star_thresholds.json + 验证报告。
# 运行(宿主机即可，纯标准库)：
#   cd /home/tdxback/aiagents-stock/data/profit_mining
#   PM_DIR=. REPORT_DIR=/home/tdxback/report python3 star_calibrate.py
import os
import csv
import json
import datetime

PM_DIR = os.getenv("PM_DIR", "/app/data/profit_mining")
FEATURES = os.path.join(PM_DIR, "signal_features.csv")
THRESH_OUT = os.path.join(PM_DIR, "star_thresholds.json")
REPORT_DIR = os.getenv("REPORT_DIR", PM_DIR)

WIN_THRESH = 4.0
BIGRISE_THRESH = 10.0
TRAIN_END = "2023-12-31"
OOS_START, OOS_END = "2024-01-01", "2025-10-31"
MIN_BUCKET_N = 200
MAX_STARS = 5

BINARY_FEATS = ["极限抄底", "中枢极限底", "中枢底部回升"]


def _f(v, default=0.0):
    """宽松转 float：空串/None/非数 → default。"""
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def is_trap(row):
    """陷阱(精选层失效)：大盘多头 或 相对强弱>=0。复刻 daily_watchlist 的 trap 判定。"""
    return _f(row.get("大盘多头")) == 1 or _f(row.get("相对强弱")) >= 0


def reconstruct_tier(row):
    """复刻 daily_watchlist 层级：仅1买生效；陷阱→None；量能金叉→核心，否则精选。"""
    if row.get("买点类型") != "1买":
        return None
    if is_trap(row):
        return None
    return "核心" if _f(row.get("量能金叉")) == 1 else "精选"
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /home/tdxback/aiagents-stock/data/profit_mining && python3 -m pytest test_star_calibrate.py -v`
Expected: 7 passed。

- [ ] **Step 5: 提交**

```bash
cd /home/tdxback/aiagents-stock
git add data/profit_mining/star_calibrate.py data/profit_mining/test_star_calibrate.py
git commit -m "feat(star): 层级重建纯函数 is_trap/reconstruct_tier + 单测"
```

---

### Task 2: 特征分箱 `feature_values`（含连续特征分箱）

**Files:**
- Modify: `data/profit_mining/star_calibrate.py`
- Test: `data/profit_mining/test_star_calibrate.py`

- [ ] **Step 1: 写失败测试**（追加到 `test_star_calibrate.py` 末尾）

```python
def test_bin_volratio():
    assert sc.bin_volratio("0.9") == 0
    assert sc.bin_volratio("1.5") == 1
    assert sc.bin_volratio("2.3") == 2


def test_bin_relstr_lower_is_better():
    # 相对强弱越低(越超跌)档位越高
    assert sc.bin_relstr("-6") == 2
    assert sc.bin_relstr("-3") == 1
    assert sc.bin_relstr("-0.5") == 0


def test_feature_values_keys_and_levels():
    row = {"极限抄底": "1", "中枢极限底": "0", "中枢底部回升": "1",
           "量比": "1.5", "相对强弱": "-6"}
    fv = sc.feature_values(row)
    assert fv == {"极限抄底": 1.0, "中枢极限底": 0.0, "中枢底部回升": 1.0,
                  "量比": 1, "相对强弱": 2}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /home/tdxback/aiagents-stock/data/profit_mining && python3 -m pytest test_star_calibrate.py -k "bin_ or feature_values" -v`
Expected: FAIL —`AttributeError: module 'star_calibrate' has no attribute 'bin_volratio'`。

- [ ] **Step 3: 写实现**（追加到 `star_calibrate.py`，放在 `BINARY_FEATS` 定义之后）

```python
def bin_volratio(x):
    """量比分箱：>=2 →2，>=1.3 →1，否则 0（与 daily_watchlist 的 1.3 阈值一致）。"""
    v = _f(x)
    return 2 if v >= 2 else (1 if v >= 1.3 else 0)


def bin_relstr(x):
    """相对强弱分箱(越低越超跌、档位越高；非陷阱已保证 <0)：<=-5 →2，<=-2 →1，否则 0。"""
    v = _f(x)
    return 2 if v <= -5 else (1 if v <= -2 else 0)


CONT_FEATS = {"量比": bin_volratio, "相对强弱": bin_relstr}


def feature_values(row):
    """该信号每个打分特征的档位值（binary 0/1；连续 0/1/2）。"""
    fv = {k: _f(row.get(k)) for k in BINARY_FEATS}
    for k, fn in CONT_FEATS.items():
        fv[k] = fn(row.get(k))
    return fv
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /home/tdxback/aiagents-stock/data/profit_mining && python3 -m pytest test_star_calibrate.py -v`
Expected: 10 passed。

- [ ] **Step 5: 提交**

```bash
cd /home/tdxback/aiagents-stock
git add data/profit_mining/star_calibrate.py data/profit_mining/test_star_calibrate.py
git commit -m "feat(star): 特征分箱 feature_values(量比/相对强弱/缠论底部信号)"
```

---

### Task 3: 权重拟合 `fit_weights` + 合成分 `score_row`

**Files:**
- Modify: `data/profit_mining/star_calibrate.py`
- Test: `data/profit_mining/test_star_calibrate.py`

权重=该特征"激活档位胜率 − 未激活胜率"（训练段、层内）。合成分=Σ 权重·档位值。

- [ ] **Step 1: 写失败测试**（追加）

```python
def test_fit_weights_positive_signal():
    # 极限抄底=1 全胜、=0 全负 → 权重应为正且约等于 1.0
    rows = []
    for _ in range(50):
        rows.append({"fv": {"极限抄底": 1.0}, "win": 1})
        rows.append({"fv": {"极限抄底": 0.0}, "win": 0})
    w = sc.fit_weights(rows, ["极限抄底"])
    assert w["极限抄底"] > 0.9


def test_fit_weights_no_signal_zero_weight():
    # 特征恒为0 → 无对照组 → 权重 0
    rows = [{"fv": {"极限抄底": 0.0}, "win": 1} for _ in range(20)]
    w = sc.fit_weights(rows, ["极限抄底"])
    assert w["极限抄底"] == 0.0


def test_score_row_weighted_sum():
    w = {"极限抄底": 0.2, "量比": 0.1}
    fv = {"极限抄底": 1.0, "量比": 2}
    assert abs(sc.score_row(fv, w) - (0.2 * 1.0 + 0.1 * 2)) < 1e-9
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /home/tdxback/aiagents-stock/data/profit_mining && python3 -m pytest test_star_calibrate.py -k "fit_weights or score_row" -v`
Expected: FAIL —`AttributeError: ... 'fit_weights'`。

- [ ] **Step 3: 写实现**（追加到 `star_calibrate.py`）

```python
def fit_weights(rows, feat_names):
    """rows: [{"fv": {feat: level}, "win": 0/1}]。
    权重 = mean(win | level>0) − mean(win | level==0)。无对照组则 0。"""
    weights = {}
    for f in feat_names:
        on = [r["win"] for r in rows if r["fv"].get(f, 0) > 0]
        off = [r["win"] for r in rows if r["fv"].get(f, 0) == 0]
        if not on or not off:
            weights[f] = 0.0
        else:
            weights[f] = sum(on) / len(on) - sum(off) / len(off)
    return weights


def score_row(fv, weights):
    """合成分 = Σ 权重·档位值。"""
    return sum(weights.get(f, 0.0) * lvl for f, lvl in fv.items())
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /home/tdxback/aiagents-stock/data/profit_mining && python3 -m pytest test_star_calibrate.py -v`
Expected: 13 passed。

- [ ] **Step 5: 提交**

```bash
cd /home/tdxback/aiagents-stock
git add data/profit_mining/star_calibrate.py data/profit_mining/test_star_calibrate.py
git commit -m "feat(star): 权重拟合 fit_weights(样本外胜率增量) + 合成分 score_row"
```

---

### Task 4: 分档 `assign_bucket` / `fit_buckets`（单调 + 诚实降档，核心算法）

**Files:**
- Modify: `data/profit_mining/star_calibrate.py`
- Test: `data/profit_mining/test_star_calibrate.py`

从 5 档往下试，找"每档≥`MIN_BUCKET_N` 且训练胜率单调不降"的最大档数；都不行则 1 档。

- [ ] **Step 1: 写失败测试**（追加）

```python
def test_assign_bucket_by_cuts():
    # cuts=[10,20] → score<10:档0, 10<=score<20:档1, >=20:档2
    assert sc.assign_bucket(5, [10, 20]) == 0
    assert sc.assign_bucket(10, [10, 20]) == 1
    assert sc.assign_bucket(25, [10, 20]) == 2


def test_fit_buckets_clean_5_monotone():
    # 构造分数与胜率严格单调的数据 → 应分满 5 档
    scored = []
    for star in range(5):              # star 0..4 → 胜率 0.2..0.6
        wr = 0.2 + 0.1 * star
        for j in range(300):
            win = 1 if j < int(300 * wr) else 0
            scored.append((float(star), win, 0))
    scored.sort(key=lambda x: x[0])
    n, cuts, stats = sc.fit_buckets(scored, max_stars=5, min_n=200)
    assert n == 5
    wins = [s["train_win"] for s in stats]
    assert all(wins[i] <= wins[i + 1] + 1e-9 for i in range(4))


def test_fit_buckets_honest_downgrade_on_small_sample():
    # 仅 300 样本、min_n=200 → 最多 1 档(2 档需 400)
    scored = [(float(i), i % 2, 0) for i in range(300)]
    scored.sort(key=lambda x: x[0])
    n, cuts, stats = sc.fit_buckets(scored, max_stars=5, min_n=200)
    assert n == 1
    assert cuts == []


def test_fit_buckets_downgrade_when_not_monotone():
    # 5 档会非单调，但合并到 2 档单调 → 应降到能单调的最大档数(<5)
    scored = []
    pattern = [0.5, 0.1, 0.5, 0.1, 0.6]   # 5 等频段胜率(非单调)
    for seg, wr in enumerate(pattern):
        for j in range(300):
            scored.append((float(seg), 1 if j < int(300 * wr) else 0, 0))
    scored.sort(key=lambda x: x[0])
    n, cuts, stats = sc.fit_buckets(scored, max_stars=5, min_n=200)
    assert n < 5
    wins = [s["train_win"] for s in stats]
    assert all(wins[i] <= wins[i + 1] + 1e-9 for i in range(len(wins) - 1))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /home/tdxback/aiagents-stock/data/profit_mining && python3 -m pytest test_star_calibrate.py -k "bucket" -v`
Expected: FAIL —`AttributeError: ... 'assign_bucket'`。

- [ ] **Step 3: 写实现**（追加到 `star_calibrate.py`）

```python
def assign_bucket(score, cuts):
    """按升序切点 cuts 返回档号 0..len(cuts)。score>=cuts[i] 则进更高档。"""
    b = 0
    for c in cuts:
        if score >= c:
            b += 1
        else:
            break
    return b


def _equal_freq_cuts(scored, k):
    """对已按 score 升序排好的 scored 取 k 等频切点(长度 k-1)。"""
    n = len(scored)
    return [scored[int(round(n * i / k))][0] for i in range(1, k)]


def _bucketize(scored, cuts):
    """按 cuts 把 scored 分进 len(cuts)+1 个桶(0=最低分..末=最高分)。"""
    buckets = [[] for _ in range(len(cuts) + 1)]
    for row in scored:
        buckets[assign_bucket(row[0], cuts)].append(row)
    return buckets


def fit_buckets(scored, max_stars=MAX_STARS, min_n=MIN_BUCKET_N):
    """scored: [(score, win, bigwin)] 按 score 升序。
    从 max_stars 往下试，找"每档>=min_n 且 训练胜率单调不降"的最大档数。
    返回 (n_stars, cuts, stats)；stats[i]={"star":i+1,"n":..,"train_win":..}。
    桶号低=分低=低星，故 star = 桶号+1。"""
    n = len(scored)
    for k in range(max_stars, 1, -1):
        if n < min_n * k:
            continue
        cuts = _equal_freq_cuts(scored, k)
        buckets = _bucketize(scored, cuts)
        if any(len(b) < min_n for b in buckets):
            continue
        wr = [sum(w for _, w, _ in b) / len(b) for b in buckets]
        if all(wr[i] <= wr[i + 1] + 1e-9 for i in range(len(wr) - 1)):
            stats = [{"star": i + 1, "n": len(b), "train_win": wr[i]}
                     for i, b in enumerate(buckets)]
            return k, cuts, stats
    wr0 = sum(w for _, w, _ in scored) / max(n, 1)
    return 1, [], [{"star": 1, "n": n, "train_win": wr0}]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /home/tdxback/aiagents-stock/data/profit_mining && python3 -m pytest test_star_calibrate.py -v`
Expected: 17 passed。

- [ ] **Step 5: 提交**

```bash
cd /home/tdxback/aiagents-stock
git add data/profit_mining/star_calibrate.py data/profit_mining/test_star_calibrate.py
git commit -m "feat(star): 分档 fit_buckets(单调约束+诚实降档) + assign_bucket"
```

---

### Task 5: 样本外评估 `eval_buckets`

**Files:**
- Modify: `data/profit_mining/star_calibrate.py`
- Test: `data/profit_mining/test_star_calibrate.py`

- [ ] **Step 1: 写失败测试**（追加）

```python
def test_eval_buckets_oos_winrate_and_bigrise():
    # 2 档：低分档 win=0、大涨=0；高分档 win=1、大涨=1
    oos = [(0.0, 0, 0)] * 100 + [(5.0, 1, 1)] * 100
    cuts = [2.5]
    out = sc.eval_buckets(oos, cuts)
    assert out[0]["star"] == 1 and out[0]["n"] == 100
    assert abs(out[0]["oos_win"] - 0.0) < 1e-9
    assert out[1]["star"] == 2 and abs(out[1]["oos_win"] - 1.0) < 1e-9
    assert abs(out[1]["oos_bigrise"] - 1.0) < 1e-9


def test_eval_buckets_empty_bucket_none():
    oos = [(0.0, 0, 0)] * 50    # 全落最低档，高档为空
    out = sc.eval_buckets(oos, [2.5])
    assert out[1]["n"] == 0 and out[1]["oos_win"] is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /home/tdxback/aiagents-stock/data/profit_mining && python3 -m pytest test_star_calibrate.py -k eval_buckets -v`
Expected: FAIL —`AttributeError: ... 'eval_buckets'`。

- [ ] **Step 3: 写实现**（追加到 `star_calibrate.py`）

```python
def eval_buckets(scored, cuts):
    """样本外评估：返回各档 n / oos_win(>=4%) / oos_bigrise(>=10%)。空档为 None。"""
    buckets = _bucketize(scored, cuts)
    out = []
    for i, b in enumerate(buckets):
        nb = len(b)
        out.append({
            "star": i + 1,
            "n": nb,
            "oos_win": (sum(w for _, w, _ in b) / nb) if nb else None,
            "oos_bigrise": (sum(g for _, _, g in b) / nb) if nb else None,
        })
    return out
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /home/tdxback/aiagents-stock/data/profit_mining && python3 -m pytest test_star_calibrate.py -v`
Expected: 19 passed。

- [ ] **Step 5: 提交**

```bash
cd /home/tdxback/aiagents-stock
git add data/profit_mining/star_calibrate.py data/profit_mining/test_star_calibrate.py
git commit -m "feat(star): 样本外评估 eval_buckets(>=4%胜率 + >=10%大涨率)"
```

---

### Task 6: 主流程 `load_rows` / `split` / `calibrate` / `main` + 报告

**Files:**
- Modify: `data/profit_mining/star_calibrate.py`
- Test: `data/profit_mining/test_star_calibrate.py`

- [ ] **Step 1: 写失败测试**（追加 — 只测纯逻辑 `split_train_oos` 与 `parse_signal_row`，不读大 CSV）

```python
def test_parse_signal_row():
    raw = {"买点类型": "1买", "信号日期": "2024-03-01", "区间涨跌幅": "7.5",
           "极限抄底": "1", "中枢极限底": "0", "中枢底部回升": "0",
           "量比": "1.5", "相对强弱": "-6", "量能金叉": "1", "大盘多头": "0"}
    p = sc.parse_signal_row(raw)
    assert p["tier"] == "核心"
    assert p["win"] == 1          # 7.5 >= 4
    assert p["bigwin"] == 0       # 7.5 < 10
    assert p["date"] == "2024-03-01"


def test_split_train_oos():
    rows = [{"date": "2022-05-01"}, {"date": "2024-06-01"},
            {"date": "2025-12-01"}, {"date": "2026-01-01"}]
    train, oos = sc.split_train_oos(rows)
    assert [r["date"] for r in train] == ["2022-05-01"]
    assert [r["date"] for r in oos] == ["2024-06-01"]   # 2025-12/2026 在 OOS 窗外被排除
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /home/tdxback/aiagents-stock/data/profit_mining && python3 -m pytest test_star_calibrate.py -k "parse_signal_row or split_train_oos" -v`
Expected: FAIL —`AttributeError: ... 'parse_signal_row'`。

- [ ] **Step 3: 写实现**（追加到 `star_calibrate.py`，末尾加 `main()` 与入口）

```python
def parse_signal_row(raw):
    """把 signal_features.csv 一行解析成标定用记录。非1买/陷阱 → tier=None(后续跳过)。"""
    chg = _f(raw.get("区间涨跌幅"))
    return {
        "tier": reconstruct_tier(raw),
        "date": raw.get("信号日期", ""),
        "fv": feature_values(raw),
        "win": 1 if chg >= WIN_THRESH else 0,
        "bigwin": 1 if chg >= BIGRISE_THRESH else 0,
    }


def split_train_oos(rows):
    """按信号日期切：训练 <=TRAIN_END；样本外 OOS_START..OOS_END(排除标签截断的近端)。"""
    train = [r for r in rows if r["date"] <= TRAIN_END]
    oos = [r for r in rows if OOS_START <= r["date"] <= OOS_END]
    return train, oos


def load_rows(path=FEATURES):
    """读 signal_features.csv → 解析后、仅保留 tier 非空(核心/精选)的记录。"""
    out = []
    with open(path, encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            p = parse_signal_row(raw)
            if p["tier"]:
                out.append(p)
    return out


def calibrate(rows):
    """对核心/精选两层分别：训练定权重→打分→分档→样本外评估。返回结构化结果。"""
    feat_names = BINARY_FEATS + list(CONT_FEATS)
    result = {}
    for tier in ("核心", "精选"):
        trows = [r for r in rows if r["tier"] == tier]
        train, oos = split_train_oos(trows)
        weights = fit_weights(
            [{"fv": r["fv"], "win": r["win"]} for r in train], feat_names)
        tr_scored = sorted(
            (score_row(r["fv"], weights), r["win"], r["bigwin"]) for r in train)
        n_stars, cuts, train_stats = fit_buckets(tr_scored)
        oos_scored = [(score_row(r["fv"], weights), r["win"], r["bigwin"])
                      for r in oos]
        oos_stats = eval_buckets(oos_scored, cuts)
        # 合并训练/样本外档位统计
        by_star = {s["star"]: dict(s) for s in train_stats}
        for o in oos_stats:
            if o["star"] in by_star:
                by_star[o["star"]].update(
                    oos_n=o["n"], oos_win=o["oos_win"], oos_bigrise=o["oos_bigrise"])
        result[tier] = {
            "n_stars": n_stars,
            "weights": {k: round(v, 4) for k, v in weights.items()},
            "cuts": [round(c, 4) for c in cuts],
            "train_n": len(train), "oos_n": len(oos),
            "stars": [by_star[s] for s in sorted(by_star)],
        }
    return result


def write_report(result, ts):
    """人读 markdown 报告 → REPORT_DIR/star_calibration_report_<ts>.md。"""
    os.makedirs(REPORT_DIR, exist_ok=True)
    path = os.path.join(REPORT_DIR, f"star_calibration_report_{ts}.md")
    L = [f"# 核心/精选层星级标定报告 {ts}", "",
         f"- 主口径 ≥{WIN_THRESH}% / 辅口径 ≥{BIGRISE_THRESH}%",
         f"- 训练段 ≤{TRAIN_END}；样本外 {OOS_START}~{OOS_END}（排除标签截断的近端）", ""]
    for tier, d in result.items():
        L += [f"## {tier}层（实际 {d['n_stars']} 档，训练 {d['train_n']} / 样本外 {d['oos_n']}）",
              f"权重：{d['weights']}", "",
              "| 星级 | 训练样本 | 训练胜率 | 样本外样本 | 样本外胜率(≥4%) | 样本外大涨率(≥10%) |",
              "|---|---|---|---|---|---|"]
        for s in d["stars"]:
            star = "★" * s["star"]
            ow = f"{s.get('oos_win'):.1%}" if s.get("oos_win") is not None else "—"
            ob = f"{s.get('oos_bigrise'):.1%}" if s.get("oos_bigrise") is not None else "—"
            L.append(f"| {star} | {s['n']} | {s['train_win']:.1%} | "
                     f"{s.get('oos_n', 0)} | {ow} | {ob} |")
        L.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    return path


def main():
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    rows = load_rows()
    result = calibrate(rows)
    payload = {
        "generated": ts, "win_thresh": WIN_THRESH, "bigrise_thresh": BIGRISE_THRESH,
        "train_end": TRAIN_END, "oos": [OOS_START, OOS_END],
        "binary_feats": BINARY_FEATS, "cont_feats": list(CONT_FEATS),
        "tiers": result,
    }
    with open(THRESH_OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    rp = write_report(result, ts)
    for tier, d in result.items():
        print(f"[星级标定] {tier}层 {d['n_stars']}档 训练{d['train_n']}/样本外{d['oos_n']}")
    print(f"[星级标定] 阈值 → {THRESH_OUT}；报告 → {rp}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 跑单测确认通过**

Run: `cd /home/tdxback/aiagents-stock/data/profit_mining && python3 -m pytest test_star_calibrate.py -v`
Expected: 21 passed。

- [ ] **Step 5: 在真实数据上跑标定（宿主机，纯标准库）**

Run:
```bash
cd /home/tdxback/aiagents-stock/data/profit_mining
PM_DIR=. REPORT_DIR=/home/tdxback/report python3 star_calibrate.py
```
Expected: 打印两层档数与产物路径；生成 `./star_thresholds.json` 与 `/home/tdxback/report/star_calibration_report_<TS>.md`。

- [ ] **Step 6: 人读验证报告**

Run: `ls -t /home/tdxback/report/star_calibration_report_*.md | head -1 | xargs cat`
检查：①每层每档**样本外胜率随星级单调上升**（或诚实降档后单调）；②高星档样本外胜率明显高于该层基线与低星档；③核心/精选各自实际档数合理（样本不足层正确降档）。**若样本外严重不单调**，回到 §design 调整分箱阈值或 `MIN_BUCKET_N` 后重跑（属预期内的调参，不是失败）。

- [ ] **Step 7: 提交**

```bash
cd /home/tdxback/aiagents-stock
git add data/profit_mining/star_calibrate.py data/profit_mining/test_star_calibrate.py data/profit_mining/star_thresholds.json
git commit -m "feat(star): 主流程 calibrate/main + 产出 star_thresholds.json 与验证报告"
```
（注：`star_thresholds.json` 提交以便阶段二查表；报告按惯例留在 `/home/tdxback/report/`，不入库。）

---

## 阶段一完成定义

- 21 个单测全绿。
- `star_thresholds.json` 生成，含两层权重 + 切点 + 各档训练/样本外胜率。
- 验证报告显示**每层星级样本外胜率单调（或诚实降档后单调）**，高星显著优于低星与基线。
- 用户阅报告确认后，再启动**阶段二**（改 `daily_watchlist.py` 查表打星 + `stable_ui.py` 展示，另写计划）。
