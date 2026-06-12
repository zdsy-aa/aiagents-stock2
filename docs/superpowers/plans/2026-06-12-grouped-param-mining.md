# 分维度参数挖掘（Grouped Param Mining）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有全市场缠论参数挖掘之上增加「板块/市值/波动率」边际分组，一遍跑出每组最优参数及其对全市场的 lift 提升（uplift）。

**Architecture:** 扩展 `accumulate_stock`，累加键加 `group` 前缀，同一只股票的信号只算一次、被其所属各组共享累加（ALL+板块+市值整股复用同一计数；波动率按事件拐点 vol20 预切窗口子集）。新增分桶标定脚本与市值快照拉取脚本。报告层按维度出分组 uplift 榜（vs ALL 基线）。

**Tech Stack:** Python3 + pandas + numpy + multiprocessing；测试为项目惯例的 `def test_*`+assert+`__main__` 脚本，容器内 `python3 test_x.py` 跑。

> 运行环境：脚本在 `data/profit_mining/`，宿主该目录挂载进容器 `agentsstock1`（`/app/data/profit_mining/`），改宿主 `.py` 即生效。测试/运行均在容器内：`docker exec agentsstock1 sh -c 'cd /app/data/profit_mining && python3 ...'`。每次跑前先 `rm -f __pycache__/*.pyc`。

---

## File Structure

**新建：**
- `data/profit_mining/group_dims.py` — 纯分组工具：三分位归桶、板块/市值标签、vol20 序列、按 vol 拆分窗口、读 buckets json。无项目路径依赖，易测。
- `data/profit_mining/test_group_dims.py` — group_dims 单测。
- `data/profit_mining/fetch_mktcap_snapshot.py` — 拉 akshare 全市场快照 → `stock_mktcap_snapshot.csv`。核心解析函数纯函数可测。
- `data/profit_mining/calibrate_buckets.py` — 算市值/波动率三分位切点 → `group_buckets.json`。

**修改：**
- `data/profit_mining/mine_commonality.py` — `accumulate_stock` 加 `groups` 参数并改键；`finalize` 加 group 字段+vol 基线；新增 `write_grouped_reports`；`_proc`/`main` 装配分组上下文。
- `data/profit_mining/test_mine_commonality.py` — 更新现有用例为新键形；加分组累加守恒、uplift 用例。
- `data/profit_mining/_verify_opt.py` — 加分组守恒断言。

**产物（运行期生成，归档 `/home/tdxback/report/`）：** `stock_mktcap_snapshot.csv`、`group_buckets.json`、`分组uplift榜_{板块,市值,波动率}_<ts>.csv`、`分组挖掘总览_<ts>.md`、`grouped_mining_<ts>.log`。

---

## Task 1: group_dims.py 纯分组工具

**Files:**
- Create: `data/profit_mining/group_dims.py`
- Test: `data/profit_mining/test_group_dims.py`

- [ ] **Step 1: 写失败测试** `test_group_dims.py`

```python
# test_group_dims.py —— 分组工具单测
import numpy as np
import group_dims as GD


def test_bucketize():
    cuts = [10.0, 20.0]
    assert GD.bucketize(5, cuts) == 0      # <c1 低/小
    assert GD.bucketize(10, cuts) == 1     # ==c1 左闭 → 中
    assert GD.bucketize(15, cuts) == 1
    assert GD.bucketize(20, cuts) == 2     # ==c2 → 最高桶
    assert GD.bucketize(99, cuts) == 2
    print("OK bucketize")


def test_board_group():
    assert GD.board_group("创业板") == "板块=创业板"
    assert GD.board_group("") is None
    assert GD.board_group(None) is None
    print("OK board_group")


def test_size_group():
    cuts = [50.0, 200.0]
    assert GD.size_group(30, cuts) == "市值=小盘"
    assert GD.size_group(100, cuts) == "市值=中盘"
    assert GD.size_group(500, cuts) == "市值=大盘"
    assert GD.size_group(None, cuts) is None     # 快照缺 → 不分组
    assert GD.size_group(100, None) is None
    print("OK size_group")


def test_vol20_series():
    import pandas as pd
    df = pd.DataFrame({"High": [11, 12, 13], "Low": [9, 10, 11], "Close": [10, 10, 10]})
    v = GD.vol20_series(df, win=20)
    # amp = (H-L)/C = 0.2 每根；min_periods=1 → 累进均值仍 0.2
    assert np.allclose(v, [0.2, 0.2, 0.2]), v
    print("OK vol20_series")


def test_split_windows_by_vol():
    # vol20 在各 bar 的值，拐点=window[0]
    vol20 = np.array([0.0, 0.1, 0.5, 0.0, 0.9, 0.0])
    cuts = [0.2, 0.6]
    windows = [[1, 2], [2, 3], [4, 5]]   # 拐点 vol20 = 0.1(低),0.5(中),0.9(高)
    out = GD.split_windows_by_vol(windows, vol20, cuts)
    assert out[0] == [[1, 2]]
    assert out[1] == [[2, 3]]
    assert out[2] == [[4, 5]]
    print("OK split_windows_by_vol")


if __name__ == "__main__":
    test_bucketize()
    test_board_group()
    test_size_group()
    test_vol20_series()
    test_split_windows_by_vol()
    print("ALL OK")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `docker exec agentsstock1 sh -c 'cd /app/data/profit_mining && rm -f __pycache__/*.pyc; python3 test_group_dims.py'`
Expected: FAIL（`ModuleNotFoundError: No module named 'group_dims'`）

- [ ] **Step 3: 写实现** `group_dims.py`

```python
# group_dims.py —— 分维度分组工具：三分位归桶 / 板块·市值标签 / vol20 / 按vol拆窗 / 读buckets。
import json


SIZE_LABELS = ("小盘", "中盘", "大盘")
VOL_LABELS = ("低", "中", "高")


def bucketize(value, cuts):
    """三分位归桶：cuts=[c1,c2] → 0(<c1) / 1([c1,c2)) / 2(>=c2)。左闭右开，最高桶含上界。"""
    if value < cuts[0]:
        return 0
    if value < cuts[1]:
        return 1
    return 2


def board_group(board):
    """events 板块字段 → '板块=X'；空/None → None(不分组)。"""
    return f"板块={board}" if board else None


def size_group(mktcap, cuts):
    """总市值 → '市值=小/中/大盘'；mktcap 缺或无 cuts → None(不参与市值分组)。"""
    if mktcap is None or cuts is None:
        return None
    return f"市值={SIZE_LABELS[bucketize(mktcap, cuts)]}"


def vol20_series(df, win=20):
    """逐 bar 波动率 vol20 = rolling(win) 均值 of (High-Low)/Close；min_periods=1。返回 numpy。"""
    amp = (df["High"] - df["Low"]) / df["Close"]
    return amp.rolling(win, min_periods=1).mean().to_numpy()


def split_windows_by_vol(windows, vol20, cuts):
    """按拐点(window[0]) 的 vol20 把窗口分到 {0:低,1:中,2:高}。返回 dict[int,list]。"""
    out = {0: [], 1: [], 2: []}
    for w in windows:
        out[bucketize(vol20[w[0]], cuts)].append(w)
    return out


def load_buckets(path):
    """读 group_buckets.json → dict。"""
    with open(path, encoding="utf-8") as f:
        return json.load(f)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `docker exec agentsstock1 sh -c 'cd /app/data/profit_mining && rm -f __pycache__/*.pyc; python3 test_group_dims.py'`
Expected: PASS（`ALL OK`）

- [ ] **Step 5: 提交**

```bash
cd /home/tdxback/aiagents-stock
git add data/profit_mining/group_dims.py data/profit_mining/test_group_dims.py
git commit -m "feat(mining): 分组工具group_dims(三分位归桶/板块市值标签/vol20/按vol拆窗)"
```

---

## Task 2: fetch_mktcap_snapshot.py 市值快照拉取

**Files:**
- Create: `data/profit_mining/fetch_mktcap_snapshot.py`
- Test: 追加到 `data/profit_mining/test_group_dims.py`（复用同一测试文件，避免新建过多文件）

- [ ] **Step 1: 写失败测试**（在 `test_group_dims.py` 顶部 import 后加函数，并加进 `__main__`）

```python
def test_extract_mktcap():
    import pandas as pd
    import fetch_mktcap_snapshot as FM
    df = pd.DataFrame({"代码": ["000001", "600000"],
                       "名称": ["平安银行", "浦发银行"],
                       "总市值": [3.5e11, 4.2e11]})
    out = FM.extract_mktcap(df)
    assert list(out.columns) == ["代码", "总市值"]
    assert out.iloc[0]["代码"] == "000001"
    assert abs(out.iloc[0]["总市值"] - 3.5e11) < 1
    print("OK extract_mktcap")


def test_extract_mktcap_missing_col():
    import pandas as pd
    import fetch_mktcap_snapshot as FM
    df = pd.DataFrame({"代码": ["000001"], "最新价": [10.0]})   # 无总市值
    try:
        FM.extract_mktcap(df)
        assert False, "应抛错"
    except ValueError:
        print("OK extract_mktcap_missing_col")
```

`__main__` 追加：
```python
    test_extract_mktcap()
    test_extract_mktcap_missing_col()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `docker exec agentsstock1 sh -c 'cd /app/data/profit_mining && rm -f __pycache__/*.pyc; python3 test_group_dims.py'`
Expected: FAIL（`No module named 'fetch_mktcap_snapshot'`）

- [ ] **Step 3: 写实现** `fetch_mktcap_snapshot.py`

```python
# fetch_mktcap_snapshot.py —— 拉 akshare 全市场快照,存 代码+总市值 → stock_mktcap_snapshot.csv。
# 用法: python3 fetch_mktcap_snapshot.py  (已存在当天文件则跳过)
import os
import sys
import time

OUT = "/app/data/profit_mining/stock_mktcap_snapshot.csv"


def extract_mktcap(df):
    """全市场快照 df → 仅 [代码, 总市值] 两列(代码转str)。缺总市值列则抛 ValueError。"""
    if df is None or "代码" not in df.columns or "总市值" not in df.columns:
        raise ValueError(f"快照缺 代码/总市值 列；实际列={None if df is None else list(df.columns)}")
    out = df[["代码", "总市值"]].copy()
    out["代码"] = out["代码"].astype(str).str.zfill(6)
    out = out.dropna(subset=["总市值"])
    return out


def main():
    if os.path.exists(OUT):
        mtime = time.strftime("%Y-%m-%d", time.localtime(os.path.getmtime(OUT)))
        if mtime == time.strftime("%Y-%m-%d"):
            print(f"[市值快照] 当天已存在 {OUT}，跳过")
            return
    if "/app" not in sys.path:
        sys.path.insert(0, "/app")
    from akshare_gateway import akshare_gw
    df = akshare_gw.call("stock_zh_a_spot_em")
    out = extract_mktcap(df)              # 失败(限流/缺列)直接抛错,不静默写空表
    out["采集日期"] = time.strftime("%Y-%m-%d")
    out.to_csv(OUT, index=False, encoding="utf-8-sig")
    print(f"[市值快照] 写 {OUT}，{len(out)} 行")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `docker exec agentsstock1 sh -c 'cd /app/data/profit_mining && rm -f __pycache__/*.pyc; python3 test_group_dims.py'`
Expected: PASS（含 `OK extract_mktcap` / `OK extract_mktcap_missing_col`）

- [ ] **Step 5: 实跑拉取（验证 akshare 通路）**

Run: `docker exec agentsstock1 sh -c 'cd /app/data/profit_mining && python3 fetch_mktcap_snapshot.py'`
Expected: 打印 `[市值快照] 写 .../stock_mktcap_snapshot.csv，NNNN 行`（约 5000+ 行）。
若报错（东财限流）：重试或稍后再跑；该文件是后续标定输入，但不阻塞 Task 3 代码实现（标定脚本对缺文件应能跳过市值切点，见 Task 3）。

- [ ] **Step 6: 提交**

```bash
cd /home/tdxback/aiagents-stock
git add data/profit_mining/fetch_mktcap_snapshot.py data/profit_mining/test_group_dims.py
git commit -m "feat(mining): 市值快照拉取fetch_mktcap_snapshot(代码+总市值,缺列即抛错)"
```

---

## Task 3: calibrate_buckets.py 分桶标定

**Files:**
- Create: `data/profit_mining/calibrate_buckets.py`
- Test: 追加到 `data/profit_mining/test_group_dims.py`

标定纯函数 `terciles(values)` 可测；整体 `main()` 走项目数据，靠实跑验证。

- [ ] **Step 1: 写失败测试**（追加到 `test_group_dims.py`）

```python
def test_terciles():
    import calibrate_buckets as CB
    vals = list(range(1, 100))            # 1..99
    c1, c2 = CB.terciles(vals)
    assert 32 <= c1 <= 35, c1            # ~33 分位
    assert 65 <= c2 <= 68, c2            # ~66 分位
    print("OK terciles")


def test_terciles_empty():
    import calibrate_buckets as CB
    try:
        CB.terciles([])
        assert False
    except ValueError:
        print("OK terciles_empty")
```

`__main__` 追加 `test_terciles()` 与 `test_terciles_empty()`。

- [ ] **Step 2: 跑测试确认失败**

Run: `docker exec agentsstock1 sh -c 'cd /app/data/profit_mining && rm -f __pycache__/*.pyc; python3 test_group_dims.py'`
Expected: FAIL（`No module named 'calibrate_buckets'`）

- [ ] **Step 3: 写实现** `calibrate_buckets.py`

```python
# calibrate_buckets.py —— 算市值/波动率三分位切点 → group_buckets.json。轻量,无信号计算。
import json
import os
import sys
import time

import numpy as np

OUT = "/app/data/profit_mining/group_buckets.json"
SNAP = "/app/data/profit_mining/stock_mktcap_snapshot.csv"


def terciles(values):
    """→ [c1,c2] 三分位切点(33.33/66.67 百分位)。空输入抛 ValueError。"""
    arr = np.asarray(list(values), dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        raise ValueError("terciles: 空输入")
    c1, c2 = np.percentile(arr, [100 / 3.0, 200 / 3.0])
    return [float(c1), float(c2)]


def _size_cuts():
    """读快照 → 总市值三分位；快照缺则返回 None(市值维度本轮不可用)。"""
    if not os.path.exists(SNAP):
        print(f"[标定] 无 {SNAP}，跳过市值切点（市值维度将不分组）")
        return None
    import csv
    vals = []
    with open(SNAP, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            try:
                vals.append(float(r["总市值"]))
            except (ValueError, KeyError):
                pass
    return terciles(vals) if vals else None


def _vol_cuts():
    """遍历股票池,收集各 pct 事件拐点的 vol20 → 三分位。"""
    import mine_commonality as M
    import swing_samples as SW
    import group_dims as GD
    codes = M._universe()
    samples = []
    for k, code in enumerate(codes, 1):
        df = M._load_kline(code)
        if df is None or len(df) < 80:
            continue
        vol20 = GD.vol20_series(df)
        high = df["High"].tolist(); low = df["Low"].tolist()
        for pct in M.DEFAULT_PCTS:
            up, down = SW.positive_windows(high, low, pct)
            for wins in (up, down):
                for w in wins:
                    v = vol20[w[0]]
                    if np.isfinite(v):
                        samples.append(float(v))
        if k % 1000 == 0:
            print(f"  vol标定 …{k}/{len(codes)}，样本{len(samples)}", flush=True)
    return terciles(samples)


def main():
    t0 = time.time()
    size_cuts = _size_cuts()
    vol_cuts = _vol_cuts()
    out = {"市值": {"cuts": size_cuts}, "波动率": {"cuts": vol_cuts},
           "标定时间": time.strftime("%Y-%m-%d %H:%M:%S")}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"[标定] 写 {OUT} 市值cuts={size_cuts} 波动率cuts={vol_cuts} 用时{int(time.time()-t0)}s")


if __name__ == "__main__":
    if "/app" not in sys.path:
        sys.path.insert(0, "/app")
    main()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `docker exec agentsstock1 sh -c 'cd /app/data/profit_mining && rm -f __pycache__/*.pyc; python3 test_group_dims.py'`
Expected: PASS（含 `OK terciles` / `OK terciles_empty`）

- [ ] **Step 5: 实跑标定（生成 group_buckets.json）**

Run: `docker exec agentsstock1 sh -c 'cd /app/data/profit_mining && python3 calibrate_buckets.py'`
Expected: ~1-3min，打印 `[标定] 写 .../group_buckets.json 市值cuts=[...] 波动率cuts=[...]`。检查 json 存在且 cuts 为两个递增正数。

- [ ] **Step 6: 提交**

```bash
cd /home/tdxback/aiagents-stock
git add data/profit_mining/calibrate_buckets.py data/profit_mining/test_group_dims.py
git commit -m "feat(mining): 分桶标定calibrate_buckets(市值/波动率三分位切点→group_buckets.json)"
```

---

## Task 4: accumulate_stock 分组化（核心）

把累加键从 `(plan,side,pct,params)` 改为 `(group,plan,side,pct,params)`，`accumulate_stock` 接收 `groups` 并同时累加 ALL+板块+市值+波动率。

**Files:**
- Modify: `data/profit_mining/mine_commonality.py`（`accumulate_stock` 及其上游 `_win_arrays` 复用）
- Modify: `data/profit_mining/test_mine_commonality.py`（更新现有键形 + 加守恒用例）

- [ ] **Step 1: 更新/新增失败测试** `test_mine_commonality.py`

更新 `test_accumulate_stock` 内现有断言里的键，由 `("A","buy",0.15,...)` 改为 `("ALL","A","buy",0.15,...)`（凡断言 key 存在处都加 `"ALL"` 前缀）。然后**新增**守恒用例：

```python
def test_accumulate_stock_grouped_conservation():
    import pandas as pd
    import numpy as np
    base = list(range(20, 60)) + list(range(60, 20, -1))
    c = [float(x) for x in base]
    df = pd.DataFrame({"Open": c, "High": [x + 1 for x in c],
                       "Low": [x - 1 for x in c], "Close": c,
                       "Volume": [1000.0] * len(c)},
                      index=pd.date_range("2020-01-01", periods=len(c), freq="D"))
    groups = {"board": "板块=创业板", "size": "市值=小盘", "vol_cuts": [0.01, 0.03]}
    counts = M.accumulate_stock(df, pcts=(0.15,), groups=groups)
    # 1) 板块/市值组的 6 元计数应与 ALL 完全一致(单股全归入这两组)
    all_keys = [k for k in counts if k[0] == "ALL"]
    assert all_keys, "应有 ALL 键"
    for ak in all_keys:
        bk = ("板块=创业板",) + ak[1:]
        sk = ("市值=小盘",) + ak[1:]
        assert counts[bk] == counts[ak], (ak, counts[bk], counts[ak])
        assert counts[sk] == counts[ak], (ak, counts[sk], counts[ak])
    # 2) 波动率三桶的窗口计数(idx0-3)之和 == ALL 的窗口计数
    for ak in all_keys:
        agg = [0, 0, 0, 0]
        for lab in ("波动率=低", "波动率=中", "波动率=高"):
            vk = (lab,) + ak[1:]
            if vk in counts:
                for i in range(4):
                    agg[i] += counts[vk][i]
        assert agg == counts[ak][:4], (ak, agg, counts[ak][:4])
    print("OK accumulate_stock_grouped_conservation")


def test_accumulate_stock_no_groups_only_all():
    import pandas as pd
    base = list(range(20, 60)) + list(range(60, 20, -1))
    c = [float(x) for x in base]
    df = pd.DataFrame({"Open": c, "High": [x + 1 for x in c],
                       "Low": [x - 1 for x in c], "Close": c,
                       "Volume": [1000.0] * len(c)},
                      index=pd.date_range("2020-01-01", periods=len(c), freq="D"))
    counts = M.accumulate_stock(df, pcts=(0.15,))     # groups=None
    assert all(k[0] == "ALL" for k in counts), "无 groups 时只应有 ALL 键"
    print("OK accumulate_stock_no_groups_only_all")
```

`__main__` 追加这两个，并保留更新后的 `test_accumulate_stock`。

- [ ] **Step 2: 跑测试确认失败**

Run: `docker exec agentsstock1 sh -c 'cd /app/data/profit_mining && rm -f __pycache__/*.pyc; python3 test_mine_commonality.py'`
Expected: FAIL（`accumulate_stock` 还产出旧键 `("A",...)`，断言不匹配 / 不接受 `groups`）

- [ ] **Step 3: 改实现** `mine_commonality.py` 的 `accumulate_stock`

整体替换为（`_win_arrays` 保持不变）：

```python
import group_dims as GD


def accumulate_stock(df, pcts=DEFAULT_PCTS, fwd=4, groups=None):
    """单股 → 计数dict key=(group,plan,side,pct,params) val=[6元累计]。
    groups=None → 仅 ALL(向后兼容)。否则 groups={'board':标签或None,'size':标签或None,
    'vol_cuts':[c1,c2]或None}。ALL/板块/市值整股复用同一窗口计数；波动率按拐点vol20切子集。
    信号每股每(plan,params,side)只算一次,跨pct与跨组复用。"""
    out = defaultdict(lambda: [0, 0, 0, 0, 0, 0])
    n = len(df)
    high = df["High"].tolist(); low = df["Low"].tolist()
    shared = ["ALL"]
    if groups:
        if groups.get("board"):
            shared.append(groups["board"])
        if groups.get("size"):
            shared.append(groups["size"])
    vol_cuts = groups.get("vol_cuts") if groups else None
    vol20 = GD.vol20_series(df) if vol_cuts else None

    # 窗口结构 per (side,pct): list of (labels, starts, ends, seg_total, bars_pos)
    W = {}
    for pct in pcts:
        up, down = SW.positive_windows(high, low, pct, fwd)
        for side, wins in (("buy", up), ("sell", down)):
            entries = []
            if wins:
                st, en = _win_arrays(wins, n)
                entries.append((shared, st, en, len(wins), int((en - st + 1).sum())))
                if vol20 is not None:
                    for b, sub in GD.split_windows_by_vol(wins, vol20, vol_cuts).items():
                        if sub:
                            sst, sen = _win_arrays(sub, n)
                            entries.append(([f"波动率={GD.VOL_LABELS[b]}"], sst, sen,
                                            len(sub), int((sen - sst + 1).sum())))
            W[(side, pct)] = entries

    for side in ("buy", "sell"):
        has = any(W[(side, pct)] for pct in pcts)
        if not has:
            continue
        macd_cache, fib_cache, bbi_cache = {}, {}, {}

        def macd_mask(f, s, sg):
            m = macd_cache.get((f, s, sg))
            if m is None:
                m = (PS.macd_golden(df, f, s, sg) if side == "buy"
                     else PS.macd_dead(df, f, s, sg)).to_numpy()
                macd_cache[(f, s, sg)] = m
            return m

        def fib_mask(N, r, b):
            m = fib_cache.get((N, r, b))
            if m is None:
                m = (PS.fib_support_hold(df, N, r, b) if side == "buy"
                     else PS.fib_resist_reject(df, N, r, b)).to_numpy()
                fib_cache[(N, r, b)] = m
            return m

        def bbi_mask(periods, form):
            m = bbi_cache.get((periods, form))
            if m is None:
                m = PS._bbi_form(df, periods, form, side).to_numpy()
                bbi_cache[(periods, form)] = m
            return m

        def tally(plan, params, sig):
            csum = np.concatenate(([0], np.cumsum(sig, dtype=np.int64)))
            fires_all = int(sig.sum())
            for pct in pcts:
                for labels, st, en, seg_total, bars_pos in W[(side, pct)]:
                    wf = csum[en + 1] - csum[st]
                    seg_hit = int(np.count_nonzero(wf)); fires_pos = int(wf.sum())
                    for g in labels:
                        a = out[(g, plan, side, pct, params)]
                        a[0] += seg_hit; a[1] += seg_total; a[2] += fires_pos
                        a[3] += bars_pos; a[4] += fires_all; a[5] += n

        for params in PS.PLAN_A_GRID:
            N, r, b, f, s, sg = params
            tally("A", params, fib_mask(N, r, b) & macd_mask(f, s, sg))
        for params in PS.PLAN_B_GRID:
            periods, form, f, s, sg = params
            tally("B", params, bbi_mask(periods, form) & macd_mask(f, s, sg))
    return dict(out)
```

> 注意：`tally` 现在循环 `pcts`（窗口结构按 (side,pct) 取），与旧版语义一致（同一 sig 跨 pct 复用同一 csum）。

- [ ] **Step 4: 跑测试确认通过**

Run: `docker exec agentsstock1 sh -c 'cd /app/data/profit_mining && rm -f __pycache__/*.pyc; python3 test_mine_commonality.py'`
Expected: `test_accumulate_stock` / `test_accumulate_stock_grouped_conservation` / `test_accumulate_stock_no_groups_only_all` 通过。
> 此时 `test_finalize_and_rank` / `test_write_reports` 可能因键含 group 而失败 —— Task 5 修复。若已失败，继续 Task 5。

- [ ] **Step 5: 提交**

```bash
cd /home/tdxback/aiagents-stock
git add data/profit_mining/mine_commonality.py data/profit_mining/test_mine_commonality.py
git commit -m "feat(mining): accumulate_stock分组化(ALL+板块+市值整股复用,波动率按事件拆窗,键加group)"
```

---

## Task 5: finalize 加 group + uplift + 分组报告

`finalize` 适配新键并输出 `group` 字段；新增 `write_grouped_reports` 算 uplift（vs ALL）、过样本门槛、按维度出榜；`write_reports` 改为只吃 ALL 行（全市场榜照旧）。

**Files:**
- Modify: `data/profit_mining/mine_commonality.py`（`finalize` / `filter_rank` / `write_reports` / 新增 `write_grouped_reports` 与阈值常量）
- Modify: `data/profit_mining/test_mine_commonality.py`（更新 `test_finalize_and_rank` 键形；加 uplift 用例）

- [ ] **Step 1: 更新/新增失败测试**

更新 `test_finalize_and_rank`：counts 键加 `"ALL"` 前缀，并断言 `r["group"] == "ALL"`；`filter_rank` 行为不变。改后：

```python
def test_finalize_and_rank():
    counts = {
        ("ALL", "A", "buy", 0.15, (20, 0.618, 0.01, 12, 26, 9)):
            [7, 10, 8, 40, 20, 1000],
        ("ALL", "A", "buy", 0.15, (10, 0.5, 0.01, 12, 26, 9)):
            [5, 10, 1, 40, 50, 1000],
    }
    rows = M.finalize(counts)
    assert len(rows) == 2
    assert all(r["group"] == "ALL" for r in rows)
    kept = M.filter_rank(rows, cover_min=0.70)
    assert len(kept) == 1, kept
    r = kept[0]
    assert abs(r["coverage"] - 0.7) < 1e-9
    assert abs(r["lift"] - 10.0) < 1e-6, r["lift"]
    assert r["plan"] == "A" and r["side"] == "buy" and r["pct"] == 0.15
    print("OK finalize_and_rank")
```

新增 uplift 用例：

```python
def test_uplift_rows():
    # 同参数: ALL lift=2, 某组 lift=4 → uplift=2, ratio=2
    params = (20, 0.618, 0.01, 12, 26, 9)
    counts = {
        ("ALL", "A", "buy", 0.2, params): [6, 10, 30, 100, 100, 5000],  # rate_pos .3 rate_all .02 lift15? 重算↓
        ("板块=创业板", "A", "buy", 0.2, params): [8, 10, 60, 100, 100, 2000],
    }
    rows = M.finalize(counts)
    enriched = M.attach_uplift(rows)
    grp = [r for r in enriched if r["group"] == "板块=创业板"][0]
    assert "lift_all" in grp and "uplift" in grp and "uplift_ratio" in grp
    allrow = [r for r in enriched if r["group"] == "ALL"][0]
    assert abs(grp["lift_all"] - allrow["lift"]) < 1e-9
    assert abs(grp["uplift"] - (grp["lift"] - allrow["lift"])) < 1e-9
    print("OK uplift_rows")
```

`__main__` 用更新后的 `test_finalize_and_rank` 并追加 `test_uplift_rows()`。

- [ ] **Step 2: 跑测试确认失败**

Run: `docker exec agentsstock1 sh -c 'cd /app/data/profit_mining && rm -f __pycache__/*.pyc; python3 test_mine_commonality.py'`
Expected: FAIL（`finalize` 还用 4 元键解包 → 报错；`attach_uplift` 未定义）

- [ ] **Step 3: 改实现** `mine_commonality.py`

(a) `finalize` 改 5 元键解包，行加 `group`：

```python
def finalize(counts):
    """counts(已跨股累加,键含group) → list[dict] 含 group/coverage/lift/precision 等。"""
    rows = []
    for (group, plan, side, pct, params), c in counts.items():
        seg_hit, seg_total, fires_pos, bars_pos, fires_all, bars_all = c
        coverage = seg_hit / seg_total if seg_total else 0.0
        rate_pos = fires_pos / bars_pos if bars_pos else 0.0
        rate_all = fires_all / bars_all if bars_all else 0.0
        lift = rate_pos / rate_all if rate_all > 0 else float("inf")
        precision = fires_pos / fires_all if fires_all else 0.0
        rows.append({"group": group, "plan": plan, "side": side, "pct": pct,
                     "params": params, "seg_hit": seg_hit, "seg_total": seg_total,
                     "fires_all": fires_all, "coverage": coverage, "rate_all": rate_all,
                     "lift": lift, "precision": precision})
    return rows
```

(b) `filter_rank` 不变（按 lift 排序、cover_min 过滤），仍作用于 rows 列表。

(c) 新增阈值常量与 uplift/分组报告：

```python
GROUP_MIN_SEG = 3000      # 组级样本门槛(seg_total)
ROW_MIN_FIRES = 300       # 行级样本门槛(fires_all)
DIM_PREFIX = ("板块=", "市值=", "波动率=")


def attach_uplift(rows):
    """给每行补 lift_all / uplift / uplift_ratio（基线=同(plan,side,pct,params)的ALL行lift）。"""
    base = {}
    for r in rows:
        if r["group"] == "ALL":
            base[(r["plan"], r["side"], r["pct"], r["params"])] = r["lift"]
    out = []
    for r in rows:
        r = dict(r)
        la = base.get((r["plan"], r["side"], r["pct"], r["params"]))
        r["lift_all"] = la
        if la is not None and la > 0 and r["lift"] != float("inf"):
            r["uplift"] = r["lift"] - la
            r["uplift_ratio"] = r["lift"] / la
        else:
            r["uplift"] = float("-inf")
            r["uplift_ratio"] = 0.0
        out.append(r)
    return out


def _dim_of(group):
    for p in DIM_PREFIX:
        if group.startswith(p):
            return p.rstrip("=")
    return None
```

(d) `write_reports` 改为只处理 ALL 行（去掉 group 后沿用旧逻辑）。在函数体首行加过滤：

```python
def write_reports(rows, out_dir="/app/data/commonality_reports", ts=None,
                  cover_min=0.50, topn=30):
    rows = [r for r in rows if r["group"] == "ALL"]      # 全市场榜只用 ALL
    ...（其余不变）
```

(e) 新增 `write_grouped_reports`：

```python
def write_grouped_reports(rows, out_dir="/app/data/commonality_reports", ts=None,
                          topn=30, group_min_seg=GROUP_MIN_SEG, row_min_fires=ROW_MIN_FIRES):
    """按维度(板块/市值/波动率)出 uplift 榜 CSV + 总览 md。基线=ALL同参 lift。"""
    import time
    ts = ts or time.strftime("%Y%m%d_%H%M%S")
    os.makedirs(out_dir, exist_ok=True)
    rows = attach_uplift(rows)
    paths = []
    md = ["# 分组挖掘总览(uplift vs 全市场)", "",
          f"生成 {ts}；组级门槛 seg_total≥{group_min_seg}，行级 fires_all≥{row_min_fires}，每组Top{topn}",
          "（uplift=组内lift−全市场同参lift；ratio=组内/全市场。⭐=ratio≥1.3 分组显著增强）", ""]
    pcols_A = ["N", "ratio", "band", "fast", "slow", "signal"]
    pcols_B = ["periods", "form", "fast", "slow", "signal"]
    metric = ["seg_total", "coverage", "lift", "lift_all", "uplift", "uplift_ratio",
              "precision", "fires_all"]
    for dim in ("板块", "市值", "波动率"):
        drows = [r for r in rows if _dim_of(r["group"]) == dim
                 and r["seg_total"] >= group_min_seg and r["fires_all"] >= row_min_fires
                 and r["uplift"] != float("-inf")]
        drows.sort(key=lambda r: r["uplift"], reverse=True)
        # 写 CSV(A/B 参数列不同,统一展开为字符串 params 列以避免混列)
        fpath = os.path.join(out_dir, f"分组uplift榜_{dim}_{ts}.csv")
        with open(fpath, "w", newline="", encoding="utf-8-sig") as f:
            w = _csv.writer(f)
            w.writerow(["group", "plan", "side", "pct", "params"] + metric)
            for r in drows[:topn * 12]:    # 每维度跨多组,放宽总条数
                ep = _expand_params(r["plan"], r["params"])
                w.writerow([r["group"], r["plan"], r["side"], r["pct"],
                            ";".join(f"{k}={v}" for k, v in ep.items())]
                           + [r.get(m) for m in metric])
        paths.append(fpath)
        # md: 每(组×side) 取 uplift 最高一条
        best = {}
        for r in drows:
            key = (r["group"], r["side"])
            if key not in best or r["uplift"] > best[key]["uplift"]:
                best[key] = r
        md.append(f"## 维度：{dim}")
        for (grp, side), r in sorted(best.items()):
            star = "⭐" if r["uplift_ratio"] >= 1.3 else ""
            ep = _expand_params(r["plan"], r["params"])
            md.append(f"- {star}**{grp} {SIDE_CN[side]}**：方案{r['plan']} {ep} "
                      f"lift {r['lift']:.2f}(全市场{r['lift_all']:.2f}, +{r['uplift']:.2f}/{r['uplift_ratio']:.2f}×) "
                      f"覆盖{r['coverage']:.2f} 样本{r['seg_total']}")
        md.append("")
    md_path = os.path.join(out_dir, f"分组挖掘总览_{ts}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")
    paths.append(md_path)
    return paths
```

- [ ] **Step 4: 跑测试确认通过**

Run: `docker exec agentsstock1 sh -c 'cd /app/data/profit_mining && rm -f __pycache__/*.pyc; python3 test_mine_commonality.py'`
Expected: 全部 `OK ...` + `ALL OK`（含 finalize_and_rank、uplift_rows、write_reports）。

- [ ] **Step 5: 提交**

```bash
cd /home/tdxback/aiagents-stock
git add data/profit_mining/mine_commonality.py data/profit_mining/test_mine_commonality.py
git commit -m "feat(mining): finalize加group+attach_uplift+write_grouped_reports(按维度出uplift榜)"
```

---

## Task 6: 装配 main + 校验守恒 + 实跑归档

`_proc`/`main` 装配分组上下文并调分组报告；扩展 `_verify_opt.py` 守恒断言；标定→实跑→归档。

**Files:**
- Modify: `data/profit_mining/mine_commonality.py`（`_proc` / `main` / 新增 `_group_ctx`）
- Modify: `data/profit_mining/_verify_opt.py`

- [ ] **Step 1: 改 `mine_commonality.py` 装配分组上下文**

新增模块级懒加载与改 `_proc`/`main`：

```python
_GCTX = None


def _group_ctx():
    """懒加载(每 worker 一次): {board_map, mktcap_map, size_cuts, vol_cuts}。缺文件则对应维度为空。"""
    global _GCTX
    if _GCTX is not None:
        return _GCTX
    import csv as c2
    import group_dims as GD
    # 板块图: events_labeled.csv 代码->板块
    board_map = {}
    with open("/app/data/profit_mining/events_labeled.csv", encoding="utf-8-sig") as f:
        for r in c2.DictReader(f):
            code = r.get("股票代码")
            if code and code not in board_map:
                board_map[code] = r.get("板块") or None
    # 市值图
    mktcap_map = {}
    snap = "/app/data/profit_mining/stock_mktcap_snapshot.csv"
    if os.path.exists(snap):
        with open(snap, encoding="utf-8-sig") as f:
            for r in c2.DictReader(f):
                try:
                    mktcap_map[r["代码"]] = float(r["总市值"])
                except (ValueError, KeyError):
                    pass
    # 切点
    size_cuts = vol_cuts = None
    bpath = "/app/data/profit_mining/group_buckets.json"
    if os.path.exists(bpath):
        b = GD.load_buckets(bpath)
        size_cuts = b.get("市值", {}).get("cuts")
        vol_cuts = b.get("波动率", {}).get("cuts")
    _GCTX = {"board_map": board_map, "mktcap_map": mktcap_map,
             "size_cuts": size_cuts, "vol_cuts": vol_cuts}
    return _GCTX
```

改 `_proc`：

```python
def _proc(code):
    df = _load_kline(code)
    if df is None or len(df) < 80:
        return {}
    import group_dims as GD
    ctx = _group_ctx()
    groups = {"board": GD.board_group(ctx["board_map"].get(code)),
              "size": GD.size_group(ctx["mktcap_map"].get(code), ctx["size_cuts"]),
              "vol_cuts": ctx["vol_cuts"]}
    return accumulate_stock(df, pcts=DEFAULT_PCTS, fwd=4, groups=groups)
```

改 `main()` 末尾的报告调用（在 `rows = finalize(...)` 后）：

```python
    rows = finalize(dict(total))
    paths = write_reports(rows, out_dir="/app/data/commonality_reports")          # 全市场ALL榜
    paths += write_grouped_reports(rows, out_dir="/app/data/commonality_reports")  # 分组uplift榜
    print(f"[共性挖掘] 股票{len(codes)} 组合keys{len(rows)} 用时{int(time.time()-t0)}s", flush=True)
    for pth in paths:
        print("  写", pth, flush=True)
```

- [ ] **Step 2: 扩展 `_verify_opt.py` 守恒断言**

在 `_verify_opt.py` 的 `main()` 里，对每只股新增分组守恒检查（用一组固定 groups）：

```python
def check_conservation(code):
    df = M._load_kline(code)
    if df is None or len(df) < 80:
        return True
    groups = {"board": "板块=测试", "size": "市值=小盘", "vol_cuts": [0.01, 0.03]}
    counts = M.accumulate_stock(df, pcts=M.DEFAULT_PCTS, groups=groups)
    all_keys = [k for k in counts if k[0] == "ALL"]
    ok = True
    for ak in all_keys:
        for lab in ("板块=测试", "市值=小盘"):
            gk = (lab,) + ak[1:]
            if counts.get(gk) != counts[ak]:
                ok = False; print(f"  {code} ❌ {lab} 6元计数≠ALL {ak}")
        agg = [0, 0, 0, 0]
        for lab in ("波动率=低", "波动率=中", "波动率=高"):
            vk = (lab,) + ak[1:]
            if vk in counts:
                for i in range(4):
                    agg[i] += counts[vk][i]
        if agg != counts[ak][:4]:
            ok = False; print(f"  {code} ❌ 波动率三桶窗口计数和≠ALL {ak}")
    if ok:
        print(f"  {code} ✅ 分组守恒")
    return ok
```

并在 `main()` 的股票循环里调用 `check_conservation(code)`，全 True 才算通过。

- [ ] **Step 3: 跑校验（守恒 + ALL 等价）**

Run: `docker exec agentsstock1 sh -c 'cd /app/data/profit_mining && rm -f __pycache__/*.pyc; python3 _verify_opt.py'`
Expected: 每只股 `✅ 分组守恒`，且原有 ALL-vs-参考实现逐键比对仍 `==== 全部一致 ✅`。

- [ ] **Step 4: 单元测试回归**

Run: `docker exec agentsstock1 sh -c 'cd /app/data/profit_mining && python3 test_mine_commonality.py && python3 test_group_dims.py'`
Expected: 两个 `ALL OK`。

- [ ] **Step 5: 实跑全量分组挖掘 + 归档**

确保 `group_buckets.json` 已生成（Task 3 Step 5）。运行：

```bash
TS=$(date +%Y%m%d_%H%M%S); LOG=/home/tdxback/report/grouped_mining_${TS}.log
docker exec agentsstock1 sh -c 'rm -f /app/data/profit_mining/__pycache__/*.pyc; cd /app/data/profit_mining && NPROC=10 python3 mine_commonality.py 2>&1' | tee "$LOG"
```
Expected: ~12-15min，打印各 checkpoint 与「写 …分组uplift榜_板块/市值/波动率_<ts>.csv」「分组挖掘总览_<ts>.md」。
归档：
```bash
cd /home/tdxback/aiagents-stock/data/commonality_reports
TS2=<上面产物时间戳>
cp 分组uplift榜_*_${TS2}.csv 分组挖掘总览_${TS2}.md /home/tdxback/report/
cp group_buckets.json stock_mktcap_snapshot.csv /home/tdxback/report/ 2>/dev/null
```

- [ ] **Step 6: 提交**

```bash
cd /home/tdxback/aiagents-stock
git add data/profit_mining/mine_commonality.py data/profit_mining/_verify_opt.py
git commit -m "feat(mining): 装配分组上下文(_group_ctx/_proc/main)+_verify_opt守恒校验"
```

---

## Self-Review 备注（已核对）

- **Spec 覆盖**：维度(板块/市值/波动率)=Task1+3+6；市值快照=Task2；标定=Task3；累加键分组化=Task4；uplift+样本门槛+报告=Task5；装配+校验守恒+归档=Task6。全覆盖。
- **vol 基线口径**：采用「统一 6 元组、vol 桶基线=其子universe整段 rate」(见 spec §6 实现注)，故 finalize 无需对 vol 特判；守恒测试对 vol 仅校验窗口 4 计数（fires_all/bars_all 因事件重叠不守恒，预期内）。
- **类型一致**：键统一 `(group,plan,side,pct,params)`；`finalize` 输出含 `group/fires_all/lift/...`；`attach_uplift` 读 `lift`/`group`；`write_grouped_reports` 读这些字段——前后一致。
- **无占位符**：各步含完整代码与命令。
