# 蓄势期特征共性挖掘(mine_setup_commonality) 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用蓄势期特征(低波动收敛/缩量/箱体/筹码集中)替换动量信号,在 zz6 起涨前蓄势窗口上 L1+L2 遍历,找 coverage>0.5 且 lift>1 的起涨前共性。

**Architecture:** 2 个新文件——`presetup_signals.py`(参数化蓄势信号库,逐bar布尔)+ `mine_setup_commonality.py`(段级L1+L2累加+多进程main+自带报告)。复用 `swing_samples.presetup_windows_from_pivots`、`mine_commonality.{finalize,filter_rank,_load_kline,_universe}`、`turnover_features.chip_series`。**不改 mine_presetup/mine_commonality,不复用 _write_board**。

**Tech Stack:** Python3+numpy+pandas+multiprocessing。容器 agentsstock1 内 `/app/data/profit_mining`。测试 `python3 test_*.py`(合成序列,无pytest)。

参考 spec：`docs/superpowers/specs/2026-06-13-setup-feature-commonality-design.md`

确认事实(无需重查)：
- `mine_commonality` 导出 `finalize`(counts→rows,coverage=seg_hit/seg_total,lift=(fires_pos/bars_pos)/(fires_all/bars_all),precision=fires_pos/fires_all)、`filter_rank(rows,cover_min)`(筛 seg_total>0&coverage≥门槛&rate_all>0,按lift降序)、`_load_kline(code)`(→OHLCV df 或 None)、`_universe()`(股票池 list)。
- `turnover_features.chip_series(df, turn)` → DataFrame 含列 `获利盘/活跃筹码/套牢盘/爆破线/堡垒线`(前60 bar NaN);turn=该股换手率%(date-indexed Series)。
- turnover.csv 列 `code,date,turn`(turn 单位%)。
- `_load_kline` 返回的 df index 为 datetime(set_index("日期").sort_index()),列 Open/High/Low/Close/Volume。

---

### Task 1: 蓄势信号库 presetup_signals.py

**Files:**
- Create: `data/profit_mining/presetup_signals.py`
- Test: `data/profit_mining/test_presetup_signals.py`

- [ ] **Step 1: 写失败测试** — `data/profit_mining/test_presetup_signals.py`：
```python
import numpy as np, pandas as pd
import presetup_signals as PSig

def _df(close, vol=None):
    c = pd.Series(close, dtype=float)
    return pd.DataFrame({"Open": c, "High": c*1.01, "Low": c*0.99, "Close": c,
                         "Volume": pd.Series(vol if vol is not None else [1.0]*len(c))})

def test_box_fires_on_flat_not_on_trend():
    flat = _df([10.0]*40)                      # 完全横盘 -> 箱体应亮
    trend = _df([10.0 + i for i in range(40)]) # 单调上行 -> 箱体不亮
    bf = PSig.sig_box(flat, 20, 0.10)
    tf = PSig.sig_box(trend, 20, 0.10)
    assert bf[-1] == True and tf[-1] == False, (bf[-1], tf[-1])

def test_dryup_fires_on_low_volume():
    vol = [100.0]*30 + [10.0]*10               # 后段缩量
    d = _df([10.0]*40, vol=vol)
    f = PSig.sig_dryup(d, 20, 0.8)
    assert f[-1] == True, f[-1]
    # 无 Volume 列 -> 全 False
    d2 = _df([10.0]*40); d2 = d2.drop(columns=["Volume"])
    assert PSig.sig_dryup(d2, 20, 0.8).sum() == 0

def test_lowvol_fires_when_std_compresses():
    # 前段大波动,后段几乎不动 -> 后段低波动应亮
    noisy = [10.0 + (2.0 if i % 2 else -2.0) for i in range(80)]
    calm = [20.0 + 0.001*(i % 2) for i in range(80)]
    d = _df(noisy + calm)
    f = PSig.sig_lowvol(d, 20, 0.3)
    assert f[-1] == True, f[-1]

def test_chip_band_and_none():
    profit = np.array([np.nan]*60 + [55.0, 90.0, 20.0])
    f = PSig.sig_chip(profit, 50, 80)
    assert f[-3] == True and f[-2] == False and f[-1] == False
    assert PSig.sig_chip(None, 50, 80) is None

def test_l1_specs_and_l2_pairs():
    names = [s[0] for s in PSig.L1_SPECS]
    assert len(names) == 17 and len(set(names)) == 17, len(names)
    pairs = PSig.l2_pairs(names)
    assert len(pairs) == 17*16//2, len(pairs)

if __name__ == "__main__":
    test_box_fires_on_flat_not_on_trend(); test_dryup_fires_on_low_volume()
    test_lowvol_fires_when_std_compresses(); test_chip_band_and_none()
    test_l1_specs_and_l2_pairs()
    print("ALL presetup_signals OK")
```

- [ ] **Step 2: 跑测试确认失败** — `cd data/profit_mining && python3 test_presetup_signals.py` → `ModuleNotFoundError: No module named 'presetup_signals'`。

- [ ] **Step 3: 实现** — `data/profit_mining/presetup_signals.py`：
```python
# presetup_signals.py —— 起涨前"蓄势期特征"信号库(逐bar布尔, 参数化)。
# 4类: 低波动率收敛 lowvol / 缩量 dryup / 箱体盘整 box / 筹码集中 chip。
# 纯函数: df(或获利盘数组)-> numpy bool 数组(长度n); 不足回看的bar记False。
from itertools import combinations
import numpy as np


def sig_lowvol(df, win, q):
    """收益率STD(win)跌到自身近120日q分位 = 波动收敛。"""
    ret = df["Close"].pct_change()
    v = ret.rolling(win).std()
    thr = v.rolling(120, min_periods=40).quantile(q)
    return (v <= thr).fillna(False).to_numpy()


def sig_dryup(df, win, ratio):
    """量 <= ratio*MA(量,win) = 缩量。无 Volume 列 -> 全False。"""
    if "Volume" not in df.columns:
        return np.zeros(len(df), dtype=bool)
    vol = df["Volume"]
    return (vol <= ratio * vol.rolling(win).mean()).fillna(False).to_numpy()


def sig_box(df, win, width):
    """(HHV-LLV)/LLV <= width = 窄箱体横盘。"""
    c = df["Close"]
    hhv = c.rolling(win, min_periods=win).max()
    llv = c.rolling(win, min_periods=win).min()
    rng = (hhv - llv) / (llv + 1e-9)
    return (rng <= width).fillna(False).to_numpy()


def sig_chip(profit, lo, hi):
    """获利盘 profit(numpy数组,可含NaN)在[lo,hi] = 筹码集中/超跌。
    profit=None(该股无turnover) -> 返回 None(调用方按全False处理)。"""
    if profit is None:
        return None
    p = np.asarray(profit, dtype=float)
    return (p >= lo) & (p <= hi) & ~np.isnan(p)


# L1 信号谱: (name, kind, params)。kind∈{lowvol,dryup,box,chip}。
L1_SPECS = (
    [(f"lowvol_w{w}_q{q}", "lowvol", (w, q)) for w in (10, 20, 30) for q in (0.2, 0.3)] +
    [(f"dryup_w{w}_r{r}", "dryup", (w, r)) for w in (20, 60) for r in (0.7, 0.8)] +
    [(f"box_w{w}_wd{wd}", "box", (w, wd)) for w in (20, 30) for wd in (0.10, 0.15)] +
    [("chip_50_80", "chip", (50, 80)),
     ("chip_60_85", "chip", (60, 85)),
     ("chip_deep_0_30", "chip", (0, 30))]
)


def eval_l1(spec, df, profit):
    """按 spec 算单股逐bar布尔数组。chip 类用 profit(获利盘数组或None->全False)。"""
    name, kind, params = spec
    if kind == "lowvol":
        return sig_lowvol(df, *params)
    if kind == "dryup":
        return sig_dryup(df, *params)
    if kind == "box":
        return sig_box(df, *params)
    if kind == "chip":
        s = sig_chip(profit, *params)
        return np.zeros(len(df), dtype=bool) if s is None else s
    raise ValueError(kind)


def l2_pairs(names):
    return list(combinations(names, 2))
```

- [ ] **Step 4: 跑测试确认通过** — `cd data/profit_mining && python3 test_presetup_signals.py` → `ALL presetup_signals OK`。删 `__pycache__`。

- [ ] **Step 5: 提交**：
```bash
git add data/profit_mining/presetup_signals.py data/profit_mining/test_presetup_signals.py
git commit -m "feat(setup): presetup_signals 蓄势期特征信号库(lowvol/dryup/box/chip + L1/L2)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: 单股累加 accumulate_setup（含 turnover 全局 + chip）

**Files:**
- Create: `data/profit_mining/mine_setup_commonality.py`
- Test: `data/profit_mining/test_setup_accum.py`

- [ ] **Step 1: 写失败测试** — `data/profit_mining/test_setup_accum.py`：
```python
import numpy as np, pandas as pd
import mine_setup_commonality as MS
import swing_samples as SW

def _df(n=160):
    base = [10.0]*60 + [10.0 + 0.5*i for i in range(40)] + [30.0]*(n-100)
    c = pd.Series(base[:n], dtype=float)
    idx = pd.date_range("2020-01-01", periods=n, freq="D")
    return pd.DataFrame({"Open": c, "High": c*1.01, "Low": c*0.99,
                         "Close": c, "Volume": pd.Series([100.0]*n)}, index=idx)

def test_accumulate_keys_levels_and_segtotal():
    df = _df()
    counts = MS.accumulate_setup(df, "000001", turn=None)  # 无turn -> chip全False但仍计
    assert counts, "应有计数"
    levels = {k[1] for k in counts}
    assert levels == {"L1", "L2"}, levels
    for k, v in counts.items():
        g, level, side, pct, name = k
        assert g == "ALL" and side == "buy" and pct == 0.06
        assert isinstance(name, str) and len(v) == 6
    # seg_total = 蓄势窗口数
    piv = SW.Z.zigzag_pivots(df["High"].tolist(), df["Low"].tolist(), 0.06)
    n_up = len(SW.presetup_windows_from_pivots(piv))
    assert next(iter(counts.values()))[1] == n_up, (next(iter(counts.values()))[1], n_up)

def test_l2_is_and_of_l1():
    # 人工: 取两个 L1 名, 其 L2 命中段数 <= 各自 L1 命中段数(AND 单调)
    df = _df()
    counts = MS.accumulate_setup(df, "000001", turn=None)
    l1 = {k[4]: v for k, v in counts.items() if k[1] == "L1"}
    l2 = {k[4]: v for k, v in counts.items() if k[1] == "L2"}
    assert l2, "应有L2"
    name2, v2 = next(iter(l2.items()))
    a, b = name2.split(" & ")
    assert v2[0] <= l1[a][0] and v2[0] <= l1[b][0], (v2[0], l1[a][0], l1[b][0])

if __name__ == "__main__":
    test_accumulate_keys_levels_and_segtotal(); test_l2_is_and_of_l1()
    print("ALL setup_accum OK")
```

- [ ] **Step 2: 跑测试确认失败** — `cd data/profit_mining && python3 test_setup_accum.py` → `ModuleNotFoundError: No module named 'mine_setup_commonality'`。

- [ ] **Step 3: 实现** — `data/profit_mining/mine_setup_commonality.py`（本任务先到 accumulate_setup + merge_counts；main/report 后续任务）：
```python
# mine_setup_commonality.py —— 蓄势期特征共性挖掘(buy向/仅zz6, L1单+L2两两)。
# 复用 mine_presetup 的起涨前蓄势窗口 + 段级覆盖率; 信号库=presetup_signals(蓄势特征)。
import os, sys, time
from collections import defaultdict
import numpy as np
import pandas as pd

import swing_samples as SW
import presetup_signals as PSig
from mine_commonality import finalize, filter_rank, _load_kline, _universe
from turnover_features import chip_series

PCT = 0.06
NEAR_N = 20
FAR = 7

_TURN = {}   # {code: pd.Series(turn% , index=datetime)}; fork前填,COW共享不pickle


def _win_arrays(windows, n):
    st = np.fromiter((w[0] for w in windows), dtype=np.int64, count=len(windows))
    en = np.fromiter((w[-1] for w in windows), dtype=np.int64, count=len(windows))
    np.clip(st, 0, n - 1, out=st); np.clip(en, 0, n - 1, out=en)
    return st, en


def accumulate_setup(df, code, turn=None):
    """单股 -> counts dict key=("ALL",level,"buy",PCT,name) val=[seg_hit,seg_total,
    fires_pos,bars_pos,fires_all,n]。level∈{L1,L2}; name=信号名(L2='a & b')。
    turn=该股换手率Series(None则chip类全False)。"""
    out = defaultdict(lambda: [0, 0, 0, 0, 0, 0])
    n = len(df)
    if n == 0:
        return dict(out)
    piv = SW.Z.zigzag_pivots(df["High"].tolist(), df["Low"].tolist(), PCT)
    wins = SW.presetup_windows_from_pivots(piv, NEAR_N, FAR)
    if not wins:
        return dict(out)
    st, en = _win_arrays(wins, n)
    seg_total = len(wins)

    # 获利盘序列(chip类需要); turn 缺失 -> None
    profit = None
    if turn is not None:
        try:
            profit = chip_series(df, turn)["获利盘"].to_numpy(float)
        except Exception:
            profit = None

    # 先算所有 L1 布尔数组(缓存供 L2 复用)
    l1_arr = {}
    for spec in PSig.L1_SPECS:
        l1_arr[spec[0]] = PSig.eval_l1(spec, df, profit).astype(bool)

    def tally(level, name, sig):
        csum = np.concatenate(([0], np.cumsum(sig, dtype=np.int64)))
        fires_all = int(sig.sum())
        wf = csum[en + 1] - csum[st]
        seg_hit = int(np.count_nonzero(wf)); fires_pos = int(wf.sum())
        bars_pos = int((en - st + 1).sum())   # 近窗口按构造重叠->bars_pos重复计:coverage精确,lift近似
        a = out[("ALL", level, "buy", PCT, name)]
        a[0] += seg_hit; a[1] += seg_total; a[2] += fires_pos
        a[3] += bars_pos; a[4] += fires_all; a[5] += n

    for name, arr in l1_arr.items():
        tally("L1", name, arr)
    for a, b in PSig.l2_pairs(list(l1_arr.keys())):
        tally("L2", f"{a} & {b}", l1_arr[a] & l1_arr[b])
    return dict(out)


def merge_counts(dst, src):
    for k, v in src.items():
        acc = dst[k]
        for i in range(6):
            acc[i] += v[i]
```

- [ ] **Step 4: 跑测试确认通过** — `cd data/profit_mining && python3 test_setup_accum.py` → `ALL setup_accum OK`。删 `__pycache__`。

- [ ] **Step 5: 提交**：
```bash
git add data/profit_mining/mine_setup_commonality.py data/profit_mining/test_setup_accum.py
git commit -m "feat(setup): accumulate_setup 段级 L1+L2 蓄势特征累加(含chip)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: 报告写入 _write_setup_reports

**Files:**
- Modify: `data/profit_mining/mine_setup_commonality.py`（追加）
- Test: `data/profit_mining/test_setup_report.py`

- [ ] **Step 1: 写失败测试** — `data/profit_mining/test_setup_report.py`：
```python
import os, tempfile
import mine_setup_commonality as MS

def test_write_setup_reports():
    rows = [
        {"group":"ALL","plan":"L1","side":"buy","pct":0.06,"params":"box_w20_wd0.10",
         "seg_hit":7,"seg_total":10,"fires_all":50,"coverage":0.7,"rate_all":0.05,"lift":1.6,"precision":0.4},
        {"group":"ALL","plan":"L2","side":"buy","pct":0.06,"params":"box_w20_wd0.10 & dryup_w20_r0.8",
         "seg_hit":3,"seg_total":10,"fires_all":20,"coverage":0.3,"rate_all":0.02,"lift":2.2,"precision":0.5},
    ]
    d = tempfile.mkdtemp()
    paths = MS._write_setup_reports(rows, out_dir=d, ts="T")
    names = sorted(os.path.basename(p) for p in paths)
    assert any("蓄势特征_共性_zz6_T.csv" == n for n in names), names
    assert any("最佳可达" in n for n in names), names
    assert any(n.endswith(".md") for n in names), names
    main_csv = [p for p in paths if "蓄势特征_共性_zz6_T.csv" in p][0]
    txt = open(main_csv, encoding="utf-8-sig").read()
    assert "box_w20_wd0.10" in txt and "coverage" in txt
    # 主榜只收 coverage>=0.5 -> L1(0.7)在, L2(0.3)不在
    assert "box_w20_wd0.10 & dryup" not in txt

if __name__ == "__main__":
    test_write_setup_reports(); print("ALL setup_report OK")
```

- [ ] **Step 2: 跑测试确认失败** — `cd data/profit_mining && python3 test_setup_report.py` → `AttributeError: ... '_write_setup_reports'`。

- [ ] **Step 3: 实现** — 追加到 `mine_setup_commonality.py`（自带 CSV 写入,不用 _write_board）：
```python
import csv as _csv

_METRIC_COLS = ["seg_hit", "seg_total", "coverage", "rate_all", "lift", "precision"]


def _write_one(fpath, ranked):
    with open(fpath, "w", newline="", encoding="utf-8-sig") as f:
        w = _csv.writer(f)
        w.writerow(["level", "signal"] + _METRIC_COLS)
        for r in ranked:
            w.writerow([r["plan"], r["params"]] + [r[c] for c in _METRIC_COLS])


def _write_setup_reports(rows, out_dir="/app/data/commonality_reports", ts=None,
                         cover_min=0.50, topn=30):
    """rows(finalize后) -> 主榜(coverage>=门槛) + 最佳可达Top + 横向对比md。"""
    ts = ts or time.strftime("%Y%m%d_%H%M%S")
    os.makedirs(out_dir, exist_ok=True)
    main = filter_rank(rows, cover_min=cover_min)                      # coverage>=门槛,按lift降序
    best = sorted([r for r in rows if r["rate_all"] > 0 and r["lift"] != float("inf")],
                  key=lambda r: r["lift"], reverse=True)[:topn]
    main_path = os.path.join(out_dir, f"蓄势特征_共性_zz6_{ts}.csv")
    best_path = os.path.join(out_dir, f"蓄势特征_最佳可达_zz6_{ts}.csv")
    _write_one(main_path, main); _write_one(best_path, best)
    md_path = os.path.join(out_dir, f"蓄势特征_横向对比_{ts}.md")
    # coverage>0.5 且 lift>1 的组合(重点结论)
    edge = [r for r in main if r["lift"] > 1.0]
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# 蓄势期特征共性 横向对比\n\n生成 {ts}，zz6，buy向(起涨前蓄势窗口)，"
                f"覆盖率门槛 {cover_min}；段级覆盖率，重点看 coverage>0.5 且 lift>1\n\n")
        f.write(f"- **达标(coverage≥{cover_min}) 组合数**：{len(main)}；其中 **lift>1 的**：{len(edge)}\n")
        if edge:
            f.write("- **★coverage>0.5 且 lift>1（真 edge）Top10**：\n")
            for r in edge[:10]:
                f.write(f"  - [{r['plan']}] {r['params']}：覆盖{r['coverage']:.2f} 提升度{r['lift']:.2f} 精确{r['precision']:.2f}\n")
        else:
            f.write("- 无 coverage>0.5 且 lift>1 的组合。\n")
        if best:
            b = best[0]
            f.write(f"- 全局最高 lift（不卡覆盖）：[{b['plan']}] {b['params']} "
                    f"覆盖{b['coverage']:.2f} 提升度{b['lift']:.2f} 精确{b['precision']:.2f}\n")
    return [main_path, best_path, md_path]
```

- [ ] **Step 4: 跑测试确认通过** — `cd data/profit_mining && python3 test_setup_report.py` → `ALL setup_report OK`。删 `__pycache__`。

- [ ] **Step 5: 提交**：
```bash
git add data/profit_mining/mine_setup_commonality.py data/profit_mining/test_setup_report.py
git commit -m "feat(setup): _write_setup_reports(主榜+最佳可达+横向对比md,标注lift>1)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: turnover 全局加载 + main + 容器冒烟

**Files:** Modify `data/profit_mining/mine_setup_commonality.py`（追加 _load_turn_by_code + _proc + main）。

- [ ] **Step 1: 实现** — 追加到 `mine_setup_commonality.py`：
```python
def _load_turn_by_code(path="/app/data/profit_mining/turnover.csv"):
    """turnover.csv(code,date,turn) -> {code: Series(turn%, index=datetime)}。填入全局 _TURN。"""
    if not os.path.exists(path):
        return
    df = pd.read_csv(path, dtype={"code": str})
    df["date"] = pd.to_datetime(df["date"])
    for code, g in df.groupby("code", sort=False):
        _TURN[code] = pd.Series(g["turn"].to_numpy(float),
                                index=pd.DatetimeIndex(g["date"].to_numpy()))


def _proc(code):
    try:
        df = _load_kline(code)
        if df is None or len(df) < 70:
            return {}
        return accumulate_setup(df, code, turn=_TURN.get(code))
    except Exception:
        return {}


def main():
    from multiprocessing import Pool
    t0 = time.time()
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    _load_turn_by_code()                       # fork前填全局,worker COW共享
    print(f"  turnover 覆盖 {len(_TURN)} 股", flush=True)
    codes = _universe()
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
    paths = _write_setup_reports(rows, out_dir="/app/data/commonality_reports", ts=run_ts)
    print(f"[蓄势特征] 股票{len(codes)} 信号keys{len(rows)} 用时{int(time.time()-t0)}s", flush=True)
    for pth in paths:
        print("  写", pth, flush=True)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 语法检查** — `cd data/profit_mining && python3 -c "import ast; ast.parse(open('mine_setup_commonality.py').read()); print('syntax OK')"` → `syntax OK`。

- [ ] **Step 3: 容器冒烟(前台, limit=30)** — 运行：
```bash
docker exec -w /app/data/profit_mining agentsstock1 sh -c 'NPROC=4 python3 mine_setup_commonality.py 30'
```
Expected: 打印 `turnover 覆盖 N 股`、`[蓄势特征] 股票30 信号keys... 用时...s`、`写 ...蓄势特征_共性_zz6_*.csv`/`...最佳可达...`/`...横向对比...md`。无 traceback。

- [ ] **Step 4: 校验冒烟产物** — 运行：
```bash
docker exec agentsstock1 sh -c 'ls -t /app/data/commonality_reports/*蓄势特征* | head; echo ---; head -2 $(ls -t /app/data/commonality_reports/蓄势特征_共性_zz6_*.csv | head -1); echo ---; cat $(ls -t /app/data/commonality_reports/蓄势特征_横向对比_*.md | head -1)'
```
Expected: 文件存在；主榜表头 `level,signal,seg_hit,seg_total,coverage,rate_all,lift,precision`；md 含"达标组合数"与"lift>1"统计。

- [ ] **Step 5: 提交**(仅 .py；报告产物 gitignore,勿 stage)：
```bash
git add data/profit_mining/mine_setup_commonality.py
git commit -m "feat(setup): mine_setup_commonality main(turnover全局+多进程)+冒烟

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: 全量跑 + 归档 + 结论

**Files:** 无代码改动。

- [ ] **Step 1: 后台全量跑(宿主持有会话,NPROC=10)** — 用 run_in_background：
```bash
docker exec agentsstock1 sh -c 'cd /app/data/profit_mining && NPROC=10 python3 mine_setup_commonality.py > /app/data/profit_mining/_setup_run.log 2>&1'
```
（**勿用 docker exec -d**(本环境分离留不住);用 run_in_background 持有会话。等完成通知。turnover 全局加载需读 396MB,首条进度前有数十秒加载。）

- [ ] **Step 2: 完成后归档 report/**：
```bash
TS=$(date +%Y%m%d_%H%M%S); DEST=/home/tdxback/report/蓄势特征_共性挖掘_$TS; mkdir -p "$DEST"
cp /home/tdxback/aiagents-stock/data/profit_mining/_setup_run.log "$DEST"/
cp /home/tdxback/aiagents-stock/data/commonality_reports/*蓄势特征* "$DEST"/ 2>/dev/null
ls "$DEST"
```

- [ ] **Step 3: 读结论报告用户** — 读 `蓄势特征_横向对比_*.md`：是否有 **coverage>0.5 且 lift>1** 的蓄势特征/组合(L1/L2);全局最高 lift;与动量信号(mine_presetup lift≈1)对比——蓄势特征是否真有起涨前 edge。

- [ ] **Step 4: 登记 DATA_FILES.md + 提交**：在 DATA_FILES.md 报告产物段追加 mine_setup_commonality 产物行,提交。

---

## Self-Review

**1. Spec coverage:**
- 4类信号参数化(lowvol/dryup/box/chip)+L1≈17 → Task1(L1_SPECS 6+4+4+3=17) ✓
- L2任意两两 → Task1 l2_pairs + Task2 accumulate L2 ✓
- 起涨前蓄势窗口+段级覆盖 → Task2 复用 SW.presetup_windows_from_pivots + seg_hit/seg_total ✓
- 仅buy/仅zz6 → 写死 side="buy"/PCT=0.06 ✓
- chip依赖turnover,缺失全False → Task2 profit=None→eval_l1 chip 返回zeros ✓ + Task4 _TURN.get(code)
- turnover fork前全局COW → Task4 _load_turn_by_code 填 _TURN(模块全局),main在Pool前调用 ✓
- coverage>0.5且lift>1重点 → Task3 md 显式统计 edge ✓
- 自带写入器不用_write_board → Task3 _write_one ✓
- 复用finalize/filter_rank/_load_kline/_universe/chip_series,不改mine_presetup/mine_commonality → import only ✓
- 输出data/commonality_reports+归档report → Task4/5 ✓

**2. Placeholder scan:** 无 TBD/TODO;每步含完整代码与确切命令。

**3. Type consistency:** counts key=("ALL",level,"buy",PCT,name);finalize 解包(group,plan,side,pct,params)→本方案 plan槽=level、params槽=name(字符串),finalize/filter_rank 仅按 coverage/lift 处理不解释 params,兼容✓。_write_setup_reports 读 r["plan"](level)/r["params"](name)/指标列,与 finalize 输出键一致✓。eval_l1 返回 np bool 数组,tally 用 cumsum 一致✓。L2 名 "a & b" 在 Task2 生成、Task3 测试一致✓。
