# 分维度共性挖掘新增行业维度 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给分维度共性挖掘加「行业」维度（baostock 证监会大类，84个，股票数≥30门槛），方案A&B全维度跑，并新增"达标榜"回答分维度后哪个子组能凑出 >50% 共性。

**Architecture:** 在现有 grouped param mining 管线（`mine_commonality.py` + `group_dims.py`）上最小增量扩展。新增 `fetch_industry_snapshot.py`（仿 `fetch_mktcap_snapshot.py`）拉行业快照；行业作为"逐股单一标签"维度接入 `accumulate_stock`（同 board/size，整股复用窗口计数，零额外切窗）；新增 `write_threshold_boards` 出 coverage>0.50 达标榜。

**Tech Stack:** Python3 / pandas / numpy / baostock / multiprocessing。测试无 pytest，用 `python3 test_x.py` 内联 assert，容器内跑（`docker exec -w /app/data/profit_mining agentsstock1`）。

**关键环境约定：**
- 容器 `agentsstock1` 已挂载 host 的 `./data` → 改 `data/profit_mining/*.py` 即时生效，无需重建镜像。
- 测试/运行一律容器内：`docker exec -w /app/data/profit_mining agentsstock1 python3 ...`。
- 分支 = `main`（CLAUDE.md 约定，只在 main 开发，用户自行 push stock2）。
- `fetch_industry_snapshot.py` / `group_dims.py` / `mine_commonality.py` 均为 tracked（仿 fetch_mktcap 先例），改动需提交。
- 产物落容器 `/app/data/commonality_reports/`（= host `aiagents-stock/data/commonality_reports/`，gitignored），最后拷归档 `/home/tdxback/report/`。

---

## 文件结构

| 文件 | 责任 | 动作 |
|---|---|---|
| `data/profit_mining/fetch_industry_snapshot.py` | baostock 拉行业 → `stock_industry_snapshot.csv`（代码/行业/采集日期） | 新建 |
| `data/profit_mining/test_fetch_industry_snapshot.py` | 行业取数纯函数单测 | 新建 |
| `data/profit_mining/group_dims.py` | 加 `industry_group` + `surviving_industries` | 改 |
| `data/profit_mining/test_group_dims.py` | 行业分组单测（追加） | 改 |
| `data/profit_mining/mine_commonality.py` | accumulate 接行业组 + `_group_ctx` 行业图 + `_dim_of` + 达标榜 + main 接线 | 改 |
| `data/profit_mining/test_mine_commonality.py` | 行业守恒 + 达标榜单测（追加） | 改 |

---

## Task 1: 行业快照取数 `fetch_industry_snapshot.py`

**Files:**
- Create: `data/profit_mining/fetch_industry_snapshot.py`
- Test: `data/profit_mining/test_fetch_industry_snapshot.py`

baostock `query_stock_industry()` 返回行 = `[updateDate, code(sh.600000), code_name, industry, industryClassification]`，行业在下标 3，空字符串=无行业。纯函数与网络隔离便于测试。

- [ ] **Step 1: 写失败测试**

`data/profit_mining/test_fetch_industry_snapshot.py`:
```python
import fetch_industry_snapshot as F

# _code6: 去交易所前缀 → 6位
assert F._code6("sh.600519") == "600519"
assert F._code6("sz.000001") == "000001"
assert F._code6("bj.830799") == "830799"

# extract_industry: 行=[date,code,name,industry,cls]；只留 universe 内 & 非空行业
rows = [
    ["2026-06-08", "sh.600519", "贵州茅台", "C15酒、饮料和精制茶制造业", "证监会行业分类"],
    ["2026-06-08", "sh.600001", "邯郸钢铁", "", "证监会行业分类"],          # 空行业→剔
    ["2026-06-08", "sz.000001", "平安银行", "J66货币金融服务", "证监会行业分类"],
    ["2026-06-08", "sh.600002", "齐鲁石化", "C25石油加工", "证监会行业分类"],  # 不在 universe→剔
]
universe = {"600519", "000001"}
m = F.extract_industry(rows, universe)
assert m == {"600519": "C15酒、饮料和精制茶制造业", "000001": "J66货币金融服务"}, m

# 全空 → extract 返回空 dict（main 据此抛错）
assert F.extract_industry([], {"600519"}) == {}
print("test_fetch_industry_snapshot ALL OK")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `docker exec -w /app/data/profit_mining agentsstock1 python3 test_fetch_industry_snapshot.py`
Expected: FAIL（`ModuleNotFoundError: No module named 'fetch_industry_snapshot'`）

- [ ] **Step 3: 写实现**

`data/profit_mining/fetch_industry_snapshot.py`:
```python
# fetch_industry_snapshot.py —— baostock 拉证监会行业分类 → 代码+行业 → stock_industry_snapshot.csv。
# 用法: docker exec -w /app/data/profit_mining agentsstock1 python3 fetch_industry_snapshot.py
import os
import time

OUT = "/app/data/profit_mining/stock_industry_snapshot.csv"
EVENTS = "/app/data/profit_mining/events_labeled.csv"
INDUSTRY_IDX = 3      # baostock query_stock_industry 行: [date,code,name,industry,cls]


def _code6(bs_code):
    """'sh.600519' / 'sz.000001' → 6位代码。"""
    c = str(bs_code).split(".")[-1]
    return c.zfill(6)


def extract_industry(rows, universe):
    """baostock 行 list → {代码6位: 行业}。只留 universe 内 & 行业非空。"""
    out = {}
    uni = set(universe)
    for r in rows:
        if len(r) <= INDUSTRY_IDX:
            continue
        code = _code6(r[1])
        ind = (r[INDUSTRY_IDX] or "").strip()
        if not ind or code not in uni:
            continue
        out.setdefault(code, ind)
    return out


def fetch_industry(query=None):
    """调 baostock query_stock_industry → 全部行 list。query 可注入便于测试。"""
    if query is not None:
        return query()
    import baostock as bs
    bs.login()
    try:
        rs = bs.query_stock_industry()
        rows = []
        while (rs.error_code == "0") and rs.next():
            rows.append(rs.get_row_data())
        return rows
    finally:
        bs.logout()


def _universe():
    """events_labeled.csv 去重股票代码。"""
    import csv
    codes, seen = [], set()
    with open(EVENTS, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            c = (r.get("股票代码") or "").strip()
            if c and c not in seen:
                seen.add(c)
                codes.append(c)
    return codes


def main():
    if os.path.exists(OUT):
        mtime = time.strftime("%Y-%m-%d", time.localtime(os.path.getmtime(OUT)))
        if mtime == time.strftime("%Y-%m-%d"):
            print(f"[行业快照] 当天已存在 {OUT}，跳过")
            return
    universe = set(_universe())
    print(f"[行业快照] 股票池 {len(universe)} 只，向 baostock 取行业 …", flush=True)
    rows = None
    for attempt in range(2):                       # 一次重试
        try:
            rows = fetch_industry()
            break
        except Exception as e:
            if attempt == 1:
                raise
            print(f"  baostock 取数失败重试: {e}", flush=True)
    mapping = extract_industry(rows, universe)
    if not mapping:                                # 全空抛错,不静默写空表
        raise ValueError("baostock 行业取数 0 行,疑似全部失败")
    today = time.strftime("%Y-%m-%d")
    import csv
    with open(OUT, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["代码", "行业", "采集日期"])
        for code, ind in mapping.items():
            w.writerow([code, ind, today])
    print(f"[行业快照] 写 {OUT}，{len(mapping)} 行")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `docker exec -w /app/data/profit_mining agentsstock1 python3 test_fetch_industry_snapshot.py`
Expected: PASS（`test_fetch_industry_snapshot ALL OK`）

- [ ] **Step 5: 提交**

```bash
cd /home/tdxback/aiagents-stock
git add data/profit_mining/fetch_industry_snapshot.py data/profit_mining/test_fetch_industry_snapshot.py
git commit -m "feat: 行业快照取数 fetch_industry_snapshot(baostock证监会大类)"
```

---

## Task 2: `group_dims.py` 行业分组 + ≥30门槛

**Files:**
- Modify: `data/profit_mining/group_dims.py`
- Test: `data/profit_mining/test_group_dims.py`（追加）

- [ ] **Step 1: 写失败测试**

测试文件是函数式（`def test_*()` + `if __name__` 逐个调用）。在 `data/profit_mining/test_group_dims.py` 的 `if __name__ == "__main__":` 之前定义新函数：
```python
def test_industry_group():
    assert GD.industry_group("C39计算机") == "行业=C39计算机"
    assert GD.industry_group("") is None
    assert GD.industry_group(None) is None
    print("OK industry_group")


def test_surviving_industries():
    imap = {"600000": "金融", "600001": "金融", "600002": "金融",
            "000001": "地产", "000002": "地产"}
    assert GD.surviving_industries(imap, min_count=3) == {"金融"}
    assert GD.surviving_industries(imap, min_count=2) == {"金融", "地产"}
    print("OK surviving_industries")
```
并在 `if __name__ == "__main__":` 块的 `print("ALL OK")` 之前加两行调用：
```python
    test_industry_group()
    test_surviving_industries()
```
（`GD` 已在文件顶部 `import group_dims as GD`。）

- [ ] **Step 2: 跑测试确认失败**

Run: `docker exec -w /app/data/profit_mining agentsstock1 python3 test_group_dims.py`
Expected: FAIL（`AttributeError: module 'group_dims' has no attribute 'industry_group'`）

- [ ] **Step 3: 写实现**

在 `data/profit_mining/group_dims.py` 的 `size_group` 函数之后插入：
```python
def industry_group(industry):
    """行业 → '行业=X'；空/None → None(不分组)。"""
    return f"行业={industry}" if industry else None


def surviving_industries(industry_map, min_count=30):
    """industry_map={代码:行业} → 股票数≥min_count 的行业集合(小行业被剔)。"""
    from collections import Counter
    c = Counter(v for v in industry_map.values() if v)
    return {ind for ind, n in c.items() if n >= min_count}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `docker exec -w /app/data/profit_mining agentsstock1 python3 test_group_dims.py`
Expected: PASS（`test_group_dims ... ALL OK`）

- [ ] **Step 5: 提交**

```bash
cd /home/tdxback/aiagents-stock
git add data/profit_mining/group_dims.py data/profit_mining/test_group_dims.py
git commit -m "feat: group_dims 加 industry_group + surviving_industries(≥30门槛)"
```

---

## Task 3: `accumulate_stock` 接行业组 + `_group_ctx`/`_proc`/`_dim_of` 接线

**Files:**
- Modify: `data/profit_mining/mine_commonality.py`
- Test: `data/profit_mining/test_mine_commonality.py`（追加）

行业 = 逐股单一标签，与 board/size 同路径 append 到 `shared`。守恒：因小行业=None，各行业组 seg 之和 **≤** ALL（≠ board/size 的 ==）。

- [ ] **Step 1: 写失败测试**

测试文件函数式，`mine_commonality` 别名为 **`M`**（顶部 `import mine_commonality as M`）。在 `data/profit_mining/test_mine_commonality.py` 的 `if __name__ == "__main__":` 之前定义：
```python
def _synth_df_ind(n=300, seed=1):
    import pandas as pd, numpy as np
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    high = close + np.abs(rng.normal(0, 0.5, n))
    low = close - np.abs(rng.normal(0, 0.5, n))
    return pd.DataFrame({"Open": close, "High": high, "Low": low,
                         "Close": close, "Volume": rng.integers(1e5, 1e6, n)})


def test_accumulate_stock_industry():
    df = _synth_df_ind()
    out = M.accumulate_stock(df, groups={"board": None, "size": None,
                                         "vol_cuts": None, "industry": "行业=测试业"})
    ind_keys = [k for k in out if k[0] == "行业=测试业"]
    assert ind_keys, "应出现 行业=测试业 的 key"
    # 单股全归该行业 → 行业组 seg_hit == 同参 ALL seg_hit（≤ 的等号情形）
    for k in ind_keys:
        allk = ("ALL",) + k[1:]
        assert out[k][0] == out[allk][0], (k, out[k], out[allk])
    # industry=None 不产行业组
    out2 = M.accumulate_stock(df, groups={"board": None, "size": None,
                                          "vol_cuts": None, "industry": None})
    assert not any(k[0].startswith("行业=") for k in out2)
    print("OK accumulate_stock_industry")


def test_dim_of_industry():
    assert M._dim_of("行业=C39计算机") == "行业"
    print("OK dim_of_industry")
```
并在 `__main__` 块 `print("ALL OK")` 之前加：
```python
    test_accumulate_stock_industry()
    test_dim_of_industry()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `docker exec -w /app/data/profit_mining agentsstock1 python3 test_mine_commonality.py`
Expected: FAIL（行业 key 不出现 / `_dim_of` 返回 None）

- [ ] **Step 3: 写实现**

改 `data/profit_mining/mine_commonality.py` 三处：

(a) `accumulate_stock` 内 `shared` 构造段（约 79-84 行），在 size 之后加 industry：
```python
    shared = ["ALL"]
    if groups:
        if groups.get("board"):
            shared.append(groups["board"])
        if groups.get("size"):
            shared.append(groups["size"])
        if groups.get("industry"):
            shared.append(groups["industry"])
```

(b) `DIM_PREFIX`（约 198 行）加 `"行业="`：
```python
DIM_PREFIX = ("板块=", "市值=", "波动率=", "行业=")
```

(c) `_group_ctx`（约 354 行）加载行业图 + ≥30门槛，并在 `_proc` 用上。
在 `_group_ctx` 内 `mktcap_map` 加载块之后、`# 切点` 之前插入：
```python
    # 行业图(+≥30门槛): 仅保留股票数≥30的行业,小行业的股票→None
    industry_map = {}
    ipath = "/app/data/profit_mining/stock_industry_snapshot.csv"
    if os.path.exists(ipath):
        raw = {}
        with open(ipath, encoding="utf-8-sig") as f:
            for r in c2.DictReader(f):
                code = r.get("代码")
                if code:
                    raw[code] = (r.get("行业") or "").strip() or None
        surv = GD.surviving_industries(raw, min_count=30)
        industry_map = {c: ind for c, ind in raw.items() if ind in surv}
```
并把返回 dict 加 `industry_map`：
```python
    _GCTX = {"board_map": board_map, "mktcap_map": mktcap_map,
             "size_cuts": size_cuts, "vol_cuts": vol_cuts,
             "industry_map": industry_map}
    return _GCTX
```
`_proc`（约 389-397 行）的 groups 加 industry：
```python
    groups = {"board": GD.board_group(ctx["board_map"].get(code)),
              "size": GD.size_group(ctx["mktcap_map"].get(code), ctx["size_cuts"]),
              "vol_cuts": ctx["vol_cuts"],
              "industry": GD.industry_group(ctx["industry_map"].get(code))}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `docker exec -w /app/data/profit_mining agentsstock1 python3 test_mine_commonality.py`
Expected: PASS（含已有用例全 OK）

- [ ] **Step 5: 提交**

```bash
cd /home/tdxback/aiagents-stock
git add data/profit_mining/mine_commonality.py data/profit_mining/test_mine_commonality.py
git commit -m "feat: 行业维度接入 accumulate_stock/_group_ctx/_proc/_dim_of"
```

---

## Task 4: 行业进 uplift 榜 + 新增 `write_threshold_boards` 达标榜

**Files:**
- Modify: `data/profit_mining/mine_commonality.py`
- Test: `data/profit_mining/test_mine_commonality.py`（追加）

uplift 榜：把 `write_grouped_reports` 维度循环加 `"行业"`。达标榜：新函数筛 coverage > 0.50。

- [ ] **Step 1: 写失败测试**

在 `data/profit_mining/test_mine_commonality.py` 的 `if __name__ == "__main__":` 之前定义：
```python
def test_write_threshold_boards():
    import tempfile
    rows = [
        {"group": "行业=甲", "plan": "A", "side": "buy", "pct": 0.15,
         "params": (10, 0.618, 0.02, 5, 17, 5), "seg_total": 5000, "fires_all": 400,
         "coverage": 0.62, "rate_all": 0.1, "lift": 2.0, "precision": 0.2},
        {"group": "行业=乙", "plan": "A", "side": "buy", "pct": 0.15,
         "params": (10, 0.618, 0.02, 5, 17, 5), "seg_total": 5000, "fires_all": 400,
         "coverage": 0.40, "rate_all": 0.1, "lift": 2.0, "precision": 0.2},   # <0.5 剔
        {"group": "ALL", "plan": "A", "side": "buy", "pct": 0.15,
         "params": (10, 0.618, 0.02, 5, 17, 5), "seg_total": 9000, "fires_all": 900,
         "coverage": 0.55, "rate_all": 0.1, "lift": 1.0, "precision": 0.2},   # ALL 不进维度榜
    ]
    d = tempfile.mkdtemp()
    paths = M.write_threshold_boards(rows, out_dir=d, ts="T", cover_min=0.50,
                                     group_min_seg=3000)
    ind = [p for p in paths if "达标榜_行业" in p][0]
    with open(ind, encoding="utf-8-sig") as f:
        txt = f.read()
    assert "行业=甲" in txt and "行业=乙" not in txt, txt
    print("OK write_threshold_boards")
```
并在 `__main__` 块 `print("ALL OK")` 之前加：
```python
    test_write_threshold_boards()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `docker exec -w /app/data/profit_mining agentsstock1 python3 test_mine_commonality.py`
Expected: FAIL（`AttributeError: module 'mine_commonality' has no attribute 'write_threshold_boards'`）

- [ ] **Step 3: 写实现**

(a) `write_grouped_reports` 维度循环（约 289 行）加 `"行业"`：
```python
    for dim in ("板块", "市值", "波动率", "行业"):
```

(b) 在 `write_grouped_reports` 之后新增 `write_threshold_boards`：
```python
def write_threshold_boards(rows, out_dir="/app/data/commonality_reports", ts=None,
                           cover_min=0.50, topn=60,
                           group_min_seg=GROUP_MIN_SEG, row_min_fires=ROW_MIN_FIRES):
    """各维度达标榜：组内 coverage>cover_min(且过样本门槛)的参数,按 coverage 降序。
    回答"分维度后哪个子组+哪套参数能凑出 >cover_min 共性"。"""
    import time
    ts = ts or time.strftime("%Y%m%d_%H%M%S")
    os.makedirs(out_dir, exist_ok=True)
    metric = ["coverage", "lift", "precision", "seg_total", "fires_all"]
    paths = []
    for dim in ("行业", "板块", "市值", "波动率"):
        drows = [r for r in rows
                 if _dim_of(r["group"]) == dim
                 and r["seg_total"] >= group_min_seg and r["fires_all"] >= row_min_fires
                 and r["rate_all"] > 0 and r["coverage"] > cover_min]
        drows.sort(key=lambda r: r["coverage"], reverse=True)
        fpath = os.path.join(out_dir, f"分组达标榜_{dim}_{ts}.csv")
        with open(fpath, "w", newline="", encoding="utf-8-sig") as f:
            w = _csv.writer(f)
            w.writerow(["group", "plan", "side", "pct", "params"] + metric)
            for r in drows[:topn * 12]:
                ep = _expand_params(r["plan"], r["params"])
                w.writerow([r["group"], r["plan"], r["side"], r["pct"],
                            ";".join(f"{k}={v}" for k, v in ep.items())]
                           + [r.get(m) for m in metric])
        paths.append(fpath)
    return paths
```

(c) `main()`（约 418 行 `paths += write_grouped_reports(...)` 之后）加一行：
```python
    paths += write_threshold_boards(rows, out_dir="/app/data/commonality_reports", ts=run_ts)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `docker exec -w /app/data/profit_mining agentsstock1 python3 test_mine_commonality.py`
Expected: PASS（`test_threshold_boards OK` + 全部已有用例）

- [ ] **Step 5: 提交**

```bash
cd /home/tdxback/aiagents-stock
git add data/profit_mining/mine_commonality.py data/profit_mining/test_mine_commonality.py
git commit -m "feat: 行业进uplift榜 + write_threshold_boards 达标榜(coverage>0.50)"
```

---

## Task 5: 容器内取行业快照 + 全量挖掘 + 归档

**Files:** 无代码改动（运行 + 归档）。

- [ ] **Step 1: 拉行业快照**

Run: `docker exec -w /app/data/profit_mining agentsstock1 python3 fetch_industry_snapshot.py`
Expected: 打印 `[行业快照] 写 .../stock_industry_snapshot.csv，N 行`（N≈4000+）。
校验幸存行业数：
```bash
docker exec -w /app/data/profit_mining agentsstock1 python3 -c "
import group_dims as GD, csv
m={}
for r in csv.DictReader(open('stock_industry_snapshot.csv',encoding='utf-8-sig')):
    m[r['代码']]=r['行业']
print('行业快照', len(m), '只; 幸存(≥30)行业数', len(GD.surviving_industries(m,30)))"
```
Expected: 幸存行业数 ~30-40。

- [ ] **Step 2: 30股冒烟**

Run: `docker exec -e NPROC=8 -w /app/data/profit_mining agentsstock1 python3 mine_commonality.py 30`
Expected: 正常结束，打印写出 `分组uplift榜_行业_*.csv` 和 `分组达标榜_行业_*.csv` 等路径，无异常。

- [ ] **Step 3: 全量跑（后台）**

用 `run_in_background` Bash（避免 docker exec 前台子进程随会话回收）：
```bash
docker exec -e NPROC=10 -w /app/data/profit_mining agentsstock1 \
  python3 mine_commonality.py > /home/tdxback/report/commonality_industry_run.log 2>&1
```
Expected: ~40-50min；日志每 500 股一个 checkpoint。先看首个 500 股 checkpoint 估 ETA。

- [ ] **Step 4: 归档产物**

跑完后拷容器产物到归档目录（带时间戳）：
```bash
TS=$(docker exec -w /app/data/commonality_reports agentsstock1 \
     sh -c "ls -t 分组达标榜_行业_*.csv | head -1" | grep -oE '[0-9]{8}_[0-9]{6}')
docker exec -w /app/data/commonality_reports agentsstock1 \
  sh -c "cp 分组达标榜_*_${TS}.csv 分组uplift榜_*_${TS}.csv 分组挖掘总览_${TS}.md /app/data/profit_mining/../commonality_reports/" 2>/dev/null
cp /home/tdxback/aiagents-stock/data/commonality_reports/*_${TS}.* /home/tdxback/report/ 2>/dev/null
ls -la /home/tdxback/report/*_${TS}.* | head
```
Expected: `/home/tdxback/report/` 下出现 `分组达标榜_行业/板块/市值/波动率_${TS}.csv` + `分组uplift榜_*` + `分组挖掘总览_${TS}.md`。

- [ ] **Step 5: 看结论 + 更记忆**

读 `分组达标榜_行业_${TS}.csv`（哪些行业+参数凑出 >50% 共性）和 `分组挖掘总览_${TS}.md`（行业 uplift 维度结论），写进 `industry-dim-commonality.md` 记忆，并把 MEMORY.md 索引那行从"进行中"改"全done"。

---

## Self-Review

**Spec 覆盖：**
- 数据层 fetch_industry_snapshot → Task 1 ✅
- 分组层 industry_group + ≥30门槛 → Task 2 ✅
- 挖掘层 _group_ctx/_proc/accumulate/_dim_of → Task 3 ✅
- >50% 达标视图 + 行业进 uplift 榜 → Task 4 ✅
- 产物归档 + 算量 + 结论 → Task 5 ✅
- 守恒测试（行业用 ≤，单股等号情形）→ Task 3 Step 1 ✅
- 全空容错 → Task 1（extract 空 dict → main 抛错）✅

**占位符扫描：** 无 TBD/TODO；每步含完整代码/命令/期望输出。

**类型一致性：**
- `extract_industry(rows, universe)` / `_code6(bs_code)` / `industry_group(industry)` / `surviving_industries(industry_map, min_count)` / `write_threshold_boards(rows, out_dir, ts, cover_min, topn, group_min_seg, row_min_fires)` 签名跨 Task 一致。
- `groups` dict 键 `industry` 在 Task 3 (`_proc` 写入 / `accumulate_stock` 读取) 一致。
- `_dim_of` 加 `行业=` 后被 write_grouped_reports(Task4 加"行业") 和 write_threshold_boards(Task4) 共用，前缀一致。
- 达标榜筛选用 `coverage > cover_min`（严格>，对应 spec ">50%"）。
