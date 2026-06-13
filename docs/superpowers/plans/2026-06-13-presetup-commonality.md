# 起涨前蓄势窗口共性挖掘(mine_presetup) 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增"起涨前蓄势窗口"共性挖掘：在 zz6 切出的 ≥6% 上涨段，取突破启动前的蓄势窗口为正样本，方案A/B 遍历全参数找 >50% 段级共性。

**Architecture:** 新增 `swing_samples.presetup_windows_from_pivots`（窗口源）+ 独立 `mine_presetup.py`（自含 accumulate，**import 复用** mine_commonality 的 finalize/filter_rank/_write_board/_expand_params 与 build_features_v2 的 K线加载）。仅 buy 向、仅 zz6、多进程。**不修改 mine_commonality.py**。

**Tech Stack:** Python3 + numpy + 既有 zigzag_segments / param_signals / mine_commonality(只 import) / multiprocessing。容器 agentsstock1 内 `/app/data/profit_mining`。测试用合成序列，`python3 test_*.py`。

参考 spec：`docs/superpowers/specs/2026-06-13-presetup-commonality-design.md`

---

### Task 1: presetup_windows_from_pivots（窗口源）

**Files:**
- Modify: `data/profit_mining/swing_samples.py`（在文件末追加函数）
- Test: `data/profit_mining/test_presetup_windows.py`（新建）

- [ ] **Step 1: 写失败测试**

`data/profit_mining/test_presetup_windows.py`：
```python
import swing_samples as SW

def _seg(pivots):
    return SW.Z.segments_from_pivots(pivots)

def test_far_branch_no_prev_up():
    # 单个上涨段: L@10 -> H@20。无上一涨段 -> 远分支 [10-7, 10]
    pivots = [(10, "L"), (20, "H")]
    wins = SW.presetup_windows_from_pivots(pivots, near_n=20, far=7)
    assert wins == [list(range(3, 11))], wins   # [L-7 .. L] 含L, 共8根

def test_far_branch_clip_negative():
    pivots = [(3, "L"), (15, "H")]               # L=3, L-7<0 -> 截到0
    wins = SW.presetup_windows_from_pivots(pivots, near_n=20, far=7)
    assert wins == [list(range(0, 4))], wins

def test_near_branch_prev_cycle():
    # 上涨段1: L0@0->H0@10; 下降段 H0@10->L1@25(gap=25-10=15<=20 近);
    # 上涨段2: L1@25->H1@40。 seg2 窗口 = [L0=0 .. L1=25] 含L1
    pivots = [(0, "L"), (10, "H"), (25, "L"), (40, "H")]
    wins = SW.presetup_windows_from_pivots(pivots, near_n=20, far=7)
    # seg1(L0): 无上一涨段 -> 远 [0-7截0 .. 0] = [0]
    # seg2(L1=25): 近 -> [0 .. 25]
    assert wins[0] == [0], wins[0]
    assert wins[1] == list(range(0, 26)), wins[1]

def test_near_falls_to_far_when_gap_big():
    # gap=30>20 -> seg2 走远分支 [25-7 .. 25]
    pivots = [(0, "L"), (10, "H"), (40, "L"), (55, "H")]
    wins = SW.presetup_windows_from_pivots(pivots, near_n=20, far=7)
    assert wins[1] == list(range(33, 41)), wins[1]

if __name__ == "__main__":
    test_far_branch_no_prev_up(); test_far_branch_clip_negative()
    test_near_branch_prev_cycle(); test_near_falls_to_far_when_gap_big()
    print("ALL presetup_windows OK")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd data/profit_mining && python3 test_presetup_windows.py`
Expected: FAIL（`AttributeError: module 'swing_samples' has no attribute 'presetup_windows_from_pivots'`）

- [ ] **Step 3: 实现**

在 `data/profit_mining/swing_samples.py` 末尾追加（文件已 `import zigzag_segments as Z`）：
```python
def presetup_windows_from_pivots(pivots, near_n=20, far=7):
    """每个上涨段(L->H)的"起涨前蓄势窗口"(buy向, 含波谷L, 截止于L无泄漏)。
    近(上一涨段终点H_prev到L的间隔 gap<=near_n): 窗口=[上一涨段起点L_prev, L];
    远(gap>near_n 或无上一涨段): 窗口=[L-far, L]。返回 list[list[int]](升序bar索引)。"""
    segs = Z.segments_from_pivots(pivots)
    wins = []
    prev_up = None                       # (L_prev_idx, H_prev_idx)
    for start, end, d in segs:
        if d != "up":
            continue
        L = start
        if prev_up is not None and (L - prev_up[1]) <= near_n:
            lo = prev_up[0]              # 上一涨段起点
        else:
            lo = max(0, L - far)
        wins.append(list(range(lo, L + 1)))   # 含L
        prev_up = (start, end)
    return wins
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd data/profit_mining && python3 test_presetup_windows.py`
Expected: `ALL presetup_windows OK`

- [ ] **Step 5: 提交**

```bash
git add data/profit_mining/swing_samples.py data/profit_mining/test_presetup_windows.py
git commit -m "feat(presetup): swing_samples 加起涨前蓄势窗口 presetup_windows_from_pivots"
```

---

### Task 2: 单股累加 accumulate_presetup

**Files:**
- Create: `data/profit_mining/mine_presetup.py`
- Test: `data/profit_mining/test_presetup_accum.py`（新建）

- [ ] **Step 1: 写失败测试**

`data/profit_mining/test_presetup_accum.py`：
```python
import numpy as np, pandas as pd
import mine_presetup as MP

def _df(n=120):
    # 构造有明显 zz6 上涨段的合成K线: 前低位震荡, 后台阶上行
    base = [10.0]*40 + [10.0 + 0.5*i for i in range(40)] + [30.0]*40
    close = pd.Series(base[:n])
    return pd.DataFrame({"Open": close, "High": close*1.01,
                         "Low": close*0.99, "Close": close})

def test_accumulate_keys_and_shape():
    df = _df()
    counts = MP.accumulate_presetup(df)
    assert counts, "应有计数"
    for k, v in counts.items():
        group, plan, side, pct, params = k
        assert group == "ALL" and side == "buy" and pct == 0.06
        assert plan in ("A", "B")
        assert len(v) == 6 and v[1] >= 1   # seg_total>=1
        break

def test_seg_total_equals_num_up_segments():
    df = _df()
    counts = MP.accumulate_presetup(df)
    import swing_samples as SW
    piv = SW.Z.zigzag_pivots(df["High"].tolist(), df["Low"].tolist(), 0.06)
    n_up = len(SW.presetup_windows_from_pivots(piv))
    # 任取一行, seg_total 应等于上涨段数
    any_v = next(iter(counts.values()))
    assert any_v[1] == n_up, (any_v[1], n_up)

if __name__ == "__main__":
    test_accumulate_keys_and_shape(); test_seg_total_equals_num_up_segments()
    print("ALL presetup_accum OK")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd data/profit_mining && python3 test_presetup_accum.py`
Expected: FAIL（`ModuleNotFoundError: No module named 'mine_presetup'`）

- [ ] **Step 3: 实现 accumulate_presetup（mine_presetup.py 第一部分）**

新建 `data/profit_mining/mine_presetup.py`：
```python
# mine_presetup.py —— 起涨前蓄势窗口共性挖掘(buy向/仅zz6)。
# 窗口=每个>=6%上涨段起涨前的蓄势期(近=上一涨段+下降段/远=前7天,含波谷L)。
# 段级覆盖率: 窗口内任一bar触发即该段命中。复用 mine_commonality 的 finalize/写榜。
import os, sys, csv as _csv, time
from collections import defaultdict
import numpy as np

import swing_samples as SW
import param_signals as PS
from mine_commonality import (finalize, filter_rank, _write_board, _expand_params,
                              _load_kline)   # 复用; _load_kline 见下注

PCT = 0.06
NEAR_N = 20
FAR = 7


def _win_arrays(windows, n):
    st = np.fromiter((w[0] for w in windows), dtype=np.int64, count=len(windows))
    en = np.fromiter((w[-1] for w in windows), dtype=np.int64, count=len(windows))
    np.clip(st, 0, n - 1, out=st); np.clip(en, 0, n - 1, out=en)
    return st, en


def accumulate_presetup(df, pct=PCT, near_n=NEAR_N, far=FAR):
    """单股 -> counts dict key=("ALL",plan,"buy",pct,params) val=[seg_hit,seg_total,
    fires_pos,bars_pos,fires_all,n]。窗口=presetup(buy向)。"""
    out = defaultdict(lambda: [0, 0, 0, 0, 0, 0])
    n = len(df)
    if n == 0:
        return dict(out)
    piv = SW.Z.zigzag_pivots(df["High"].tolist(), df["Low"].tolist(), pct)
    wins = SW.presetup_windows_from_pivots(piv, near_n, far)
    if not wins:
        return dict(out)
    st, en = _win_arrays(wins, n)
    seg_total = len(wins)
    macd_cache, fib_cache, bbi_cache = {}, {}, {}

    def tally(plan, params, sig):
        csum = np.concatenate(([0], np.cumsum(sig, dtype=np.int64)))
        fires_all = int(sig.sum())
        wf = csum[en + 1] - csum[st]            # 每窗口命中bar数
        seg_hit = int(np.count_nonzero(wf)); fires_pos = int(wf.sum())
        bars_pos = int((en - st + 1).sum())     # 近窗口可能重叠,bars_pos为窗口求和(lift近似,coverage精确)
        a = out[("ALL", plan, "buy", pct, params)]
        a[0] += seg_hit; a[1] += seg_total; a[2] += fires_pos
        a[3] += bars_pos; a[4] += fires_all; a[5] += n

    for params in PS.PLAN_A_GRID:
        N, r, b, f, s, sg = params
        m = fib_cache.get((N, r, b))
        if m is None:
            m = PS.fib_support_hold(df, N, r, b).to_numpy(); fib_cache[(N, r, b)] = m
        mc = macd_cache.get((f, s, sg))
        if mc is None:
            mc = PS.macd_golden(df, f, s, sg).to_numpy(); macd_cache[(f, s, sg)] = mc
        tally("A", params, m & mc)
    for params in PS.PLAN_B_GRID:
        periods, form, f, s, sg = params
        bb = bbi_cache.get((periods, form))
        if bb is None:
            bb = PS._bbi_form(df, periods, form, "buy").to_numpy(); bbi_cache[(periods, form)] = bb
        mc = macd_cache.get((f, s, sg))
        if mc is None:
            mc = PS.macd_golden(df, f, s, sg).to_numpy(); macd_cache[(f, s, sg)] = mc
        tally("B", params, bb & mc)
    return dict(out)


def merge_counts(dst, src):
    for k, v in src.items():
        a = dst[k]
        for i in range(6):
            a[i] += v[i]
```

注：`_load_kline` 若 mine_commonality 未暴露同名，改为复用 `build_features_v2._load`（见 Task 4 实现时按实际函数名对齐；本 import 行在 Task 4 落地 main 时校正）。Task 2 仅测 accumulate，不触发该 import 路径失败的话保留；若 import 报错，先把 `_load_kline` 从 import 行移除（Task 4 再加回正确来源）。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd data/profit_mining && python3 test_presetup_accum.py`
Expected: `ALL presetup_accum OK`
（若因 `_load_kline` import 失败：把该名从 Task 3 的 import 行删去，仅保留 `finalize, filter_rank, _write_board, _expand_params`，重跑。）

- [ ] **Step 5: 提交**

```bash
git add data/profit_mining/mine_presetup.py data/profit_mining/test_presetup_accum.py
git commit -m "feat(presetup): mine_presetup 单股 accumulate_presetup(段级,buy向,zz6)"
```

---

### Task 3: 报告写入 write_presetup_reports

**Files:**
- Modify: `data/profit_mining/mine_presetup.py`（追加）
- Test: `data/profit_mining/test_presetup_report.py`（新建）

- [ ] **Step 1: 写失败测试**

`data/profit_mining/test_presetup_report.py`：
```python
import os, tempfile, glob
import mine_presetup as MP

def test_write_reports_creates_files():
    # 构造两行 finalize 结果(A达标/B不达标)
    rows = [
        {"group":"ALL","plan":"A","side":"buy","pct":0.06,
         "params":(20,0.618,0.01,5,17,5),"seg_hit":6,"seg_total":10,
         "fires_all":100,"coverage":0.6,"rate_all":0.02,"lift":2.5,"precision":0.7},
        {"group":"ALL","plan":"B","side":"buy","pct":0.06,
         "params":((3,6,12,24),"cross",6,19,9),"seg_hit":3,"seg_total":10,
         "fires_all":80,"coverage":0.3,"rate_all":0.02,"lift":1.8,"precision":0.6},
    ]
    d = tempfile.mkdtemp()
    paths = MP.write_presetup_reports(rows, out_dir=d, ts="T")
    names = sorted(os.path.basename(p) for p in paths)
    assert any("方案A_起涨前蓄势_zz6_T.csv" == n for n in names), names
    assert any("最佳可达" in n for n in names), names
    assert any(n.endswith(".md") for n in names), names
    # A 达标主榜应含该行; B 主榜应空(coverage 0.3<0.5)
    a_main = [p for p in paths if "方案A_起涨前蓄势_zz6_T.csv" in p][0]
    assert "0.618" in open(a_main, encoding="utf-8-sig").read()

if __name__ == "__main__":
    test_write_reports_creates_files(); print("ALL presetup_report OK")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd data/profit_mining && python3 test_presetup_report.py`
Expected: FAIL（`AttributeError: ... 'write_presetup_reports'`）

- [ ] **Step 3: 实现 write_presetup_reports（追加到 mine_presetup.py）**

```python
def write_presetup_reports(rows, out_dir="/app/data/commonality_reports", ts=None,
                           cover_min=0.50, topn=30):
    """rows(finalize后,仅group=ALL/buy/zz6) -> 每方案两类CSV + 横向对比md。"""
    ts = ts or time.strftime("%Y%m%d_%H%M%S")
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    summary = []
    for plan in ("A", "B"):
        sub = [r for r in rows if r["plan"] == plan]
        # 主榜: coverage>=门槛
        main = filter_rank(sub, cover_min=cover_min)
        main_path = os.path.join(out_dir, f"方案{plan}_起涨前蓄势_zz6_{ts}.csv")
        _write_board(main_path, plan, "buy", PCT, main); paths.append(main_path)
        # 最佳可达: 不卡覆盖率,按lift取Top
        best = sorted([r for r in sub if r["rate_all"] > 0 and r["lift"] != float("inf")],
                      key=lambda r: r["lift"], reverse=True)[:topn]
        best_path = os.path.join(out_dir, f"方案{plan}_起涨前蓄势最佳可达_zz6_{ts}.csv")
        _write_board(best_path, plan, "buy", PCT, best); paths.append(best_path)
        if main:
            b = main[0]
            summary.append(f"- **方案{plan} 起涨前蓄势 zz6**：达标{len(main)}组，"
                           f"最佳 {_expand_params(plan, b['params'])} 覆盖{b['coverage']:.2f} "
                           f"提升度{b['lift']:.2f} 精确{b['precision']:.2f}")
        elif best:
            b = best[0]
            summary.append(f"- **方案{plan} 起涨前蓄势 zz6**：无≥{cover_min}达标；"
                           f"最佳可达 {_expand_params(plan, b['params'])} 覆盖{b['coverage']:.2f} "
                           f"提升度{b['lift']:.2f} 精确{b['precision']:.2f}")
        else:
            summary.append(f"- **方案{plan} 起涨前蓄势 zz6**：无数据")
    md_path = os.path.join(out_dir, f"起涨前蓄势_横向对比_{ts}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# 起涨前蓄势窗口共性 横向对比\n\n生成 {ts}，zz6，buy向，覆盖率门槛 {cover_min}，"
                f"近窗口=上一涨段+下降段(gap≤{NEAR_N})/远窗口=前{FAR}天(均含波谷L)\n\n")
        f.write("\n".join(summary) + "\n")
    paths.append(md_path)
    return paths
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd data/profit_mining && python3 test_presetup_report.py`
Expected: `ALL presetup_report OK`

- [ ] **Step 5: 提交**

```bash
git add data/profit_mining/mine_presetup.py data/profit_mining/test_presetup_report.py
git commit -m "feat(presetup): write_presetup_reports(主榜+最佳可达+横向对比md)"
```

---

### Task 4: main 入口 + 全市场多进程

**Files:**
- Modify: `data/profit_mining/mine_presetup.py`（追加 _load_pool / _proc / main）

- [ ] **Step 1: 确认 K线加载与池来源函数名**

Run: `cd data/profit_mining && python3 -c "import mine_commonality as M; print([n for n in dir(M) if 'load' in n.lower() or 'pool' in n.lower() or 'universe' in n.lower()])"`
Expected: 打印出 mine_commonality 里加载K线/池的函数名（如 `_load_kline` / `_pool` / `_universe`）。**记下实际名**，下一步用它。

- [ ] **Step 2: 实现 main（追加到 mine_presetup.py）**

将 `<LOADK>` 替换为 Step1 查到的 K 线加载函数（mine_commonality 内，签名 `(code)->df`；若不存在则 `from build_features_v2 import _load as _load_kline` 并用 `_load_kline`）；`<POOLSRC>` 替换为池来源（events_labeled 去重股票，mine_commonality 已有同名函数则复用，否则按下方自带实现）：
```python
def _load_pool():
    """events_labeled.csv 去重股票代码。"""
    path = "/app/data/profit_mining/events_labeled.csv"
    codes = []
    seen = set()
    with open(path, encoding="utf-8-sig") as f:
        for r in _csv.DictReader(f):
            c = r.get("股票代码")
            if c and c not in seen:
                seen.add(c); codes.append(c)
    return codes


def _proc(code):
    try:
        df = _load_kline(code)            # 见 Step1: mine_commonality._load_kline 或 build_features_v2._load
        if df is None or len(df) < 60:
            return {}
        return accumulate_presetup(df)
    except Exception:
        return {}


def main():
    from multiprocessing import Pool
    t0 = time.time()
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    codes = _load_pool()
    if limit:
        codes = codes[:limit]
    nproc = int(os.getenv("NPROC", "8"))
    acc = defaultdict(lambda: [0, 0, 0, 0, 0, 0])
    with Pool(nproc) as p:
        for k, c in enumerate(p.imap_unordered(_proc, codes, chunksize=8), 1):
            merge_counts(acc, c)
            if k % 500 == 0:
                print(f"  …{k}/{len(codes)}，{int(time.time()-t0)}s", flush=True)
    rows = finalize(acc)
    run_ts = time.strftime("%Y%m%d_%H%M%S")
    paths = write_presetup_reports(rows, out_dir="/app/data/commonality_reports", ts=run_ts)
    print(f"[起涨前蓄势] 股票{len(codes)} 组合keys{len(rows)} 用时{int(time.time()-t0)}s", flush=True)
    for pth in paths:
        print("  写", pth, flush=True)


if __name__ == "__main__":
    main()
```
并把 Task 3 import 行里的 `_load_kline` 来源最终确定（与 Step1 一致）。

- [ ] **Step 3: limit 冒烟（容器内,真实K线）**

Run:
```bash
docker exec -w /app/data/profit_mining agentsstock1 sh -c 'NPROC=4 python3 mine_presetup.py 30'
```
Expected: 打印 `[起涨前蓄势] 股票30 ...` 且写出 `方案A/B_起涨前蓄势_zz6_*.csv` + 最佳可达 + 横向对比 md（在 /app/data/commonality_reports/）。无异常。

- [ ] **Step 4: 校验冒烟产物结构**

Run:
```bash
docker exec agentsstock1 sh -c 'ls -t /app/data/commonality_reports/*起涨前蓄势* | head; head -2 /app/data/commonality_reports/$(ls -t /app/data/commonality_reports/ | grep 方案A_起涨前蓄势 | head -1)'
```
Expected: 文件存在；表头 = `plan,side,pct,N,ratio,band,fast,slow,signal,seg_hit,seg_total,coverage,rate_all,lift,precision`。

- [ ] **Step 5: 提交**

```bash
git add data/profit_mining/mine_presetup.py
git commit -m "feat(presetup): mine_presetup main 全市场多进程入口 + 冒烟验证"
```

---

### Task 5: 全量跑 + 归档（交付）

**Files:** 无代码改动（运行 + 归档）

- [ ] **Step 1: 后台全量跑（容器内,NPROC=10）**

Run（宿主后台持有会话）:
```bash
docker exec agentsstock1 sh -c 'cd /app/data/profit_mining && NPROC=10 python3 mine_presetup.py > /app/data/profit_mining/_presetup_run.log 2>&1'
```
（用 run_in_background；勿用 docker exec -d，本环境分离会留不住——见本会话教训。等完成通知。）

- [ ] **Step 2: 完成后核验 + 归档到 report/**

Run:
```bash
TS=$(date +%Y%m%d_%H%M%S); DEST=/home/tdxback/report/起涨前蓄势_共性挖掘_$TS; mkdir -p "$DEST"
cp /home/tdxback/aiagents-stock/data/profit_mining/_presetup_run.log "$DEST"/
cp /home/tdxback/aiagents-stock/data/commonality_reports/*起涨前蓄势* "$DEST"/ 2>/dev/null
ls "$DEST"
```
Expected: 归档目录含全部 起涨前蓄势 CSV + md + 日志。

- [ ] **Step 3: 读结论并报告用户**

读 `起涨前蓄势_横向对比_*.md`：方案A/B 在起涨前蓄势窗口能否凑出 >50% 段级共性、最佳可达覆盖/提升度/精确度；与"拐点后[L,L+4]"变体对比。

- [ ] **Step 4: 提交（研究脚本已入库,产物 gitignore；登记 DATA_FILES.md）**

在 `data/profit_mining/DATA_FILES.md` 的中间产物表追加 `mine_presetup.py` 产物说明行，提交：
```bash
git add data/profit_mining/DATA_FILES.md
git commit -m "docs(presetup): DATA_FILES 登记起涨前蓄势报告产物"
```

---

## Self-Review

**1. Spec coverage:**
- 窗口定义(近=[L_prev,L]/远=[L-7,L]含L) → Task 1 ✓
- 段级覆盖率(任一bar亮即命中) → Task 2 accumulate seg_hit/seg_total ✓
- 方案A/B全网格 → Task 2 用 PS.PLAN_A_GRID/PLAN_B_GRID ✓
- 仅buy/仅zz6 → accumulate 写死 side="buy"/pct=0.06 ✓
- >50%主榜+最佳可达Top30 → Task 3 ✓
- 输出 data/commonality_reports + 归档 report → Task 4/5 ✓
- 不动 mine_commonality → 仅 import,Task 全程不修改它 ✓
- 合成序列单测 → Task1/2/3 ✓

**2. Placeholder scan:** 仅 Task4 的 `<LOADK>`/`<POOLSRC>` 为"按实际函数名对齐"占位，已用 Step1 显式查名 + fallback(build_features_v2._load / 自带 _load_pool) 消解，非悬空。

**3. Type consistency:** counts 6元组 [seg_hit,seg_total,fires_pos,bars_pos,fires_all,n] 与 mine_commonality.finalize 解包一致；finalize 行 dict 键(coverage/lift/precision/rate_all/params/...)与 _write_board/filter_rank 期望一致；presetup_windows_from_pivots 返回 list[list[int]] 与 _win_arrays 输入一致。
