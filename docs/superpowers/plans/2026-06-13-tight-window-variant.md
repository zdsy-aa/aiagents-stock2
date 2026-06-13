# 紧窗口变体(起涨前[L-K,L]) 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给起涨前窗口加紧窗口模式 `[L-K, L]`(K∈{5,10}),对动量(mine_presetup)+蓄势(mine_setup_commonality)各重跑,检验紧窗口下是否现 coverage>0.5 且 lift>1。

**Architecture:** `swing_samples.presetup_windows_from_pivots` 加可选 `tight_k` 参数(默认None=现有自适应);两个 mine 脚本读 `TIGHT_K` env 并把 tight_k 穿到窗口调用、给产物文件名加 `_tightK{K}` 后缀。向后兼容(不设env→行为不变)。mine_commonality.py 不动。

**Tech Stack:** Python3+numpy+pandas。容器 agentsstock1。测试合成序列 `python3 test_*.py`。

参考 spec：`docs/superpowers/specs/2026-06-13-tight-window-variant-design.md`

确认事实(无需重查)：
- `swing_samples.presetup_windows_from_pivots(pivots, near_n=20, far=7)` 现签名;内部 `Z.segments_from_pivots(pivots)` 给 (start=L, end=H, "up"/"down")。
- mine_presetup.py:33 `wins = SW.presetup_windows_from_pivots(piv, near_n, far)`;`accumulate_presetup(df, pct=PCT, near_n=NEAR_N, far=FAR)`@25;`write_presetup_reports(...ts=None...)`@78 文件名@89/94/108;`_proc`@117 调 `accumulate_presetup(df)`@122;main@128 `write_presetup_reports(rows,out_dir=...,ts=run_ts)`@143。
- mine_setup_commonality.py:36 `wins = SW.presetup_windows_from_pivots(piv, NEAR_N, FAR)`;`accumulate_setup(df, code, turn=None)`@27;`_write_setup_reports(...ts=None...)`@88 文件名@96/97/99;`_proc`@129 调 `accumulate_setup(df, code, turn=_TURN.get(code))`@134;main@139 `_write_setup_reports(rows,out_dir=...,ts=run_ts)`@157。

---

### Task 1: swing_samples 加 tight_k 模式

**Files:**
- Modify: `data/profit_mining/swing_samples.py`(改 presetup_windows_from_pivots)
- Test: `data/profit_mining/test_tight_window.py`(新建)

- [ ] **Step 1: 写失败测试** — `data/profit_mining/test_tight_window.py`：
```python
import swing_samples as SW

def test_tight_single_segment():
    pivots = [(30, "L"), (50, "H")]
    w = SW.presetup_windows_from_pivots(pivots, tight_k=5)
    assert w == [list(range(25, 31))], w   # [L-5 .. L] 含L, 6根

def test_tight_clip_negative():
    pivots = [(3, "L"), (15, "H")]
    w = SW.presetup_windows_from_pivots(pivots, tight_k=5)
    assert w == [list(range(0, 4))], w     # L-5<0 截到0

def test_tight_ignores_prev_cycle():
    # 两上涨段; 紧窗口每段都是 [L-K, L], 与上一段无关(不跨周期)
    pivots = [(0, "L"), (10, "H"), (25, "L"), (40, "H")]
    w = SW.presetup_windows_from_pivots(pivots, tight_k=5)
    assert w[0] == [0], w[0]                # L0=0: [0-5截0..0]
    assert w[1] == list(range(20, 26)), w[1]  # L1=25: [20..25]

def test_tight_none_equals_adaptive():
    # tight_k=None(默认) 必须与现有自适应输出完全一致(回归保护)
    pivots = [(0, "L"), (10, "H"), (25, "L"), (40, "H")]
    assert (SW.presetup_windows_from_pivots(pivots, tight_k=None)
            == SW.presetup_windows_from_pivots(pivots))

if __name__ == "__main__":
    test_tight_single_segment(); test_tight_clip_negative()
    test_tight_ignores_prev_cycle(); test_tight_none_equals_adaptive()
    print("ALL tight_window OK")
```

- [ ] **Step 2: 跑测试确认失败** — `cd data/profit_mining && python3 test_tight_window.py` → `TypeError: presetup_windows_from_pivots() got an unexpected keyword argument 'tight_k'`。

- [ ] **Step 3: 实现** — 编辑 `data/profit_mining/swing_samples.py`，把现有函数：
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
改为(加 tight_k 分支,放在 for 内最前):
```python
def presetup_windows_from_pivots(pivots, near_n=20, far=7, tight_k=None):
    """每个上涨段(L->H)的"起涨前蓄势窗口"(buy向, 含波谷L, 截止于L无泄漏)。
    tight_k 给定: 紧窗口=[max(0,L-tight_k), L](忽略近/远自适应)。
    tight_k=None(默认): 近(上一涨段终点H_prev到L的间隔 gap<=near_n)->[上一涨段起点L_prev, L];
    远(gap>near_n 或无上一涨段)->[L-far, L]。返回 list[list[int]](升序bar索引)。"""
    segs = Z.segments_from_pivots(pivots)
    wins = []
    prev_up = None                       # (L_prev_idx, H_prev_idx)
    for start, end, d in segs:
        if d != "up":
            continue
        L = start
        if tight_k is not None:
            lo = max(0, L - tight_k)
        elif prev_up is not None and (L - prev_up[1]) <= near_n:
            lo = prev_up[0]              # 上一涨段起点
        else:
            lo = max(0, L - far)
        wins.append(list(range(lo, L + 1)))   # 含L
        prev_up = (start, end)
    return wins
```

- [ ] **Step 4: 跑测试确认通过** — `cd data/profit_mining && python3 test_tight_window.py` → `ALL tight_window OK`。再跑回归 `python3 test_presetup_windows.py` → 仍 `ALL presetup_windows OK`。删 `__pycache__`。

- [ ] **Step 5: 提交**：
```bash
git add data/profit_mining/swing_samples.py data/profit_mining/test_tight_window.py
git commit -m "feat(tight): presetup_windows_from_pivots 加 tight_k 紧窗口模式(默认None不变)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: mine_presetup 接 TIGHT_K + 文件名后缀

**Files:** Modify `data/profit_mining/mine_presetup.py`（4 处编辑）。无新测试(逻辑由 Task1 + 冒烟覆盖)。

- [ ] **Step 1: 编辑1 — 加 TIGHT_K 全局** — 在 `mine_presetup.py` 常量区(找到 `FAR = 7` 那行,其后)加：
```python
TIGHT_K = int(os.getenv("TIGHT_K")) if os.getenv("TIGHT_K") else None
```
(若文件无独立 `FAR = 7` 常量行,则加在 `import` 块之后、第一个 `def` 之前。)

- [ ] **Step 2: 编辑2 — accumulate_presetup 加 tight_k + 穿到窗口** — 改函数签名与窗口调用：
  - 签名 `def accumulate_presetup(df, pct=PCT, near_n=NEAR_N, far=FAR):` → `def accumulate_presetup(df, pct=PCT, near_n=NEAR_N, far=FAR, tight_k=None):`
  - 窗口行 `wins = SW.presetup_windows_from_pivots(piv, near_n, far)` → `wins = SW.presetup_windows_from_pivots(piv, near_n, far, tight_k=tight_k)`

- [ ] **Step 3: 编辑3 — _proc 传 TIGHT_K** — 把 `_proc` 里 `return accumulate_presetup(df)` 改为 `return accumulate_presetup(df, tight_k=TIGHT_K)`。

- [ ] **Step 4: 编辑4 — 报告文件名加后缀** — 给 `write_presetup_reports` 加 `suffix=""` 形参并改 3 处文件名；main 计算并传 suffix：
  - 签名 `def write_presetup_reports(rows, out_dir="/app/data/commonality_reports", ts=None,` 同行后续参数保持,在参数表末尾加 `suffix="",`(放在 `topn=30` 等之后均可,只要是关键字参数)。
  - 文件名：
    - `f"方案{plan}_起涨前蓄势_zz6_{ts}.csv"` → `f"方案{plan}_起涨前蓄势_zz6{suffix}_{ts}.csv"`
    - `f"方案{plan}_起涨前蓄势最佳可达_zz6_{ts}.csv"` → `f"方案{plan}_起涨前蓄势最佳可达_zz6{suffix}_{ts}.csv"`
    - `f"起涨前蓄势_横向对比_{ts}.md"` → `f"起涨前蓄势_横向对比{suffix}_{ts}.md"`
  - main 里 `paths = write_presetup_reports(rows, out_dir="/app/data/commonality_reports", ts=run_ts)` → 
    ```python
    suffix = f"_tightK{TIGHT_K}" if TIGHT_K else ""
    paths = write_presetup_reports(rows, out_dir="/app/data/commonality_reports", ts=run_ts, suffix=suffix)
    ```
  - main 起始处(进度前)加一行 `print(f"  窗口模式: {'紧窗口 K='+str(TIGHT_K) if TIGHT_K else '自适应'}", flush=True)`。

- [ ] **Step 5: 语法检查 + 自适应回归冒烟(不设TIGHT_K, 应与原一致)**：
```bash
cd data/profit_mining && python3 -c "import ast; ast.parse(open('mine_presetup.py').read()); print('syntax OK')"
docker exec -w /app/data/profit_mining agentsstock1 sh -c 'NPROC=4 python3 mine_presetup.py 20'
```
Expected: 打印 `窗口模式: 自适应`、`[起涨前蓄势] 股票20 ...`、写文件名**无** `_tightK`(后缀空)。无异常。

- [ ] **Step 6: 紧窗口冒烟(TIGHT_K=5, limit=20)**：
```bash
docker exec -w /app/data/profit_mining agentsstock1 sh -c 'TIGHT_K=5 NPROC=4 python3 mine_presetup.py 20'
docker exec agentsstock1 sh -c 'ls -t /app/data/commonality_reports/*起涨前蓄势*tightK5* | head'
```
Expected: 打印 `窗口模式: 紧窗口 K=5`;产物文件名含 `_tightK5`。无异常。

- [ ] **Step 7: 提交**(仅 .py;报告产物 gitignore)：
```bash
git add data/profit_mining/mine_presetup.py
git commit -m "feat(tight): mine_presetup 接 TIGHT_K 紧窗口 + 文件名后缀(默认自适应不变)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: mine_setup_commonality 接 TIGHT_K + 文件名后缀

**Files:** Modify `data/profit_mining/mine_setup_commonality.py`（4 处编辑,与 Task2 对称）。

- [ ] **Step 1: 编辑1 — 加 TIGHT_K 全局** — 在常量区 `FAR = 7` 后(或 `_TURN = {}` 附近)加：
```python
TIGHT_K = int(os.getenv("TIGHT_K")) if os.getenv("TIGHT_K") else None
```

- [ ] **Step 2: 编辑2 — accumulate_setup 加 tight_k + 穿到窗口**：
  - 签名 `def accumulate_setup(df, code, turn=None):` → `def accumulate_setup(df, code, turn=None, tight_k=None):`
  - 窗口行 `wins = SW.presetup_windows_from_pivots(piv, NEAR_N, FAR)` → `wins = SW.presetup_windows_from_pivots(piv, NEAR_N, FAR, tight_k=tight_k)`

- [ ] **Step 3: 编辑3 — _proc 传 TIGHT_K** — `return accumulate_setup(df, code, turn=_TURN.get(code))` → `return accumulate_setup(df, code, turn=_TURN.get(code), tight_k=TIGHT_K)`。

- [ ] **Step 4: 编辑4 — 报告文件名加后缀**：
  - `_write_setup_reports` 签名参数表末尾加 `suffix=""`。
  - 文件名：
    - `f"蓄势特征_共性_zz6_{ts}.csv"` → `f"蓄势特征_共性_zz6{suffix}_{ts}.csv"`
    - `f"蓄势特征_最佳可达_zz6_{ts}.csv"` → `f"蓄势特征_最佳可达_zz6{suffix}_{ts}.csv"`
    - `f"蓄势特征_横向对比_{ts}.md"` → `f"蓄势特征_横向对比{suffix}_{ts}.md"`
  - main 里 `paths = _write_setup_reports(rows, out_dir="/app/data/commonality_reports", ts=run_ts)` →
    ```python
    suffix = f"_tightK{TIGHT_K}" if TIGHT_K else ""
    paths = _write_setup_reports(rows, out_dir="/app/data/commonality_reports", ts=run_ts, suffix=suffix)
    ```
  - main 起始处加 `print(f"  窗口模式: {'紧窗口 K='+str(TIGHT_K) if TIGHT_K else '自适应'}", flush=True)`(放在 `turnover 覆盖` 打印之后)。

- [ ] **Step 5: 语法检查 + 紧窗口冒烟(TIGHT_K=5, limit=30)**：
```bash
cd data/profit_mining && python3 -c "import ast; ast.parse(open('mine_setup_commonality.py').read()); print('syntax OK')"
docker exec -w /app/data/profit_mining agentsstock1 sh -c 'TIGHT_K=5 NPROC=4 python3 mine_setup_commonality.py 30'
docker exec agentsstock1 sh -c 'ls -t /app/data/commonality_reports/*蓄势特征*tightK5* | head; cat $(ls -t /app/data/commonality_reports/蓄势特征_横向对比_tightK5_*.md | head -1)'
```
Expected: 打印 `窗口模式: 紧窗口 K=5`;产物含 `_tightK5`;md 正常(达标组合数 + lift>1 统计)。无异常。

- [ ] **Step 6: 提交**：
```bash
git add data/profit_mining/mine_setup_commonality.py
git commit -m "feat(tight): mine_setup_commonality 接 TIGHT_K 紧窗口 + 文件名后缀

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: 4 次全量跑 + 归档 + 结论

**Files:** 无代码改动。

- [ ] **Step 1: 4 次后台全量跑(逐个,宿主持有会话,NPROC=10)** — 用 run_in_background 串行(一个完成再下一个,避免抢CPU)：
```bash
# 顺序: 动量K5 -> 动量K10 -> 蓄势K5 -> 蓄势K10
docker exec agentsstock1 sh -c 'cd /app/data/profit_mining && TIGHT_K=5  NPROC=10 python3 mine_presetup.py          > _tight_mp5.log  2>&1'
docker exec agentsstock1 sh -c 'cd /app/data/profit_mining && TIGHT_K=10 NPROC=10 python3 mine_presetup.py          > _tight_mp10.log 2>&1'
docker exec agentsstock1 sh -c 'cd /app/data/profit_mining && TIGHT_K=5  NPROC=10 python3 mine_setup_commonality.py > _tight_ms5.log  2>&1'
docker exec agentsstock1 sh -c 'cd /app/data/profit_mining && TIGHT_K=10 NPROC=10 python3 mine_setup_commonality.py > _tight_ms10.log 2>&1'
```
(勿用 docker exec -d。蓄势两次需各加载 396M turnover。每次 ~5min,4 次 ~20-30min。)

- [ ] **Step 2: 归档 report/**：
```bash
TS=$(date +%Y%m%d_%H%M%S); DEST=/home/tdxback/report/紧窗口变体_共性挖掘_$TS; mkdir -p "$DEST"
cp /home/tdxback/aiagents-stock/data/commonality_reports/*tightK* "$DEST"/ 2>/dev/null
cp /home/tdxback/aiagents-stock/data/profit_mining/_tight_*.log "$DEST"/ 2>/dev/null
ls "$DEST"
```

- [ ] **Step 3: 读结论报告用户** — 读 4 份横向对比 md(动量 tightK5/10 + 蓄势 tightK5/10):紧窗口下**是否出现 coverage>0.5 且 lift>1** 的信号/组合;最高 lift 多少;K=5 vs K=10 差异;与自适应大窗口(lift≈1)对比——**紧窗口是否揭示出真 edge,验证"大窗口稀释"假设**。

- [ ] **Step 4: 登记 DATA_FILES.md + 提交** — 在 DATA_FILES 报告产物段注明 mine_presetup/mine_setup_commonality 支持 `TIGHT_K` env(产物名 `_tightK{K}`),提交。

---

## Self-Review

**1. Spec coverage:**
- tight_k 模式 [max(0,L-K),L] 含L → Task1 ✓
- tight_k=None 默认不变(回归保护) → Task1 test_tight_none_equals_adaptive ✓
- 脚本读 TIGHT_K env + 穿 tight_k → Task2/3 编辑1-3 ✓
- 文件名 _tightK{K} 后缀 → Task2/3 编辑4 ✓
- K∈{5,10}×动量+蓄势=4跑 → Task4 ✓
- mine_commonality 不动 → 计划不涉及它 ✓
- 重点 coverage>0.5且lift>1 + 与自适应对比 → Task4 Step3 ✓

**2. Placeholder scan:** 无 TBD;每处编辑给确切 old→new 片段与命令。Task2/3 "编辑1"对常量行位置给了 fallback(无FAR行则import块后)。

**3. Type consistency:** tight_k 贯穿 presetup_windows_from_pivots(新形参)→accumulate_presetup/accumulate_setup(新形参)→_proc(传TIGHT_K全局);suffix 贯穿 write_presetup_reports/_write_setup_reports(新形参)→main(计算传入);文件名 f-string 插 `{suffix}` 位置一致(zz6 后、_ts 前;md 在 横向对比 后)。TIGHT_K 全局类型 int|None,os.getenv 空→None。
