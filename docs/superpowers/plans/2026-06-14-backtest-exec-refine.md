# 回测执行精细化(起涨回测v2) 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 模型打分不变,给 setup_backtest 加 trailing/trend 退出模式 + 大盘择时,6 配置横向对比 vs 上证,看能否把薄edge转可用alpha。

**Architecture:** 扩 `setup_backtest.py`:simulate_trade 加 mode 开关(fixed默认向后兼容/trailing/trend)+ _ma 助手;run_backtest 加 mode/maxhold/riskoff(择时 gate);main 一次打分→循环6配置→横向对比报告。复用现有 score_oos/portfolio_curve/metrics。不动其他。

**Tech Stack:** Python3+numpy+pandas+lightgbm。容器 agentsstock1。测试 `python3 -m pytest tests/test_setup_backtest.py`(注:test 在 data/profit_mining/test_setup_backtest.py,用 `cd data/profit_mining && python3 test_setup_backtest.py`)。

参考 spec：`docs/superpowers/specs/2026-06-14-backtest-exec-refine-design.md`

确认事实(当前 setup_backtest.py):
- `simulate_trade(o,h,l,c,entry_idx,tp=TP,sl=SL,maxhold=MAXHOLD,cost=COST)` 现仅 fixed 逻辑(止损优先→止盈→到期)。常量 TP=0.10,SL=-0.05,MAXHOLD=10,COST=0.002,TOPN=10,SLOTS=100。
- `select_topn/score_oos/run_backtest(dates,codes,scores)/portfolio_curve/_bench_curve/main` 已在;run_backtest 内 `simulate_trade(o,h,lo,c,t+1)`;main 单配置跑+写 `起涨回测_{ts}.md`。
- 测试文件 `data/profit_mining/test_setup_backtest.py`(纯 python3 跑,非 tests/)现有 4 个 simulate_trade 测试用关键字传 tp/sl/maxhold/cost。
- `SM._load_index_close()`→上证Close pandas Series(datetime索引)。

---

### Task 1: simulate_trade 加 mode(trailing/trend) + _ma + 测试

**Files:** Modify `data/profit_mining/setup_backtest.py`(改 simulate_trade 加 _ma)+ `data/profit_mining/test_setup_backtest.py`(追加测试)

- [ ] **Step 1: 追加失败测试** — 在 `test_setup_backtest.py` 的 `if __name__` 之前加,并在 `__main__` 调用:
```python
def test_trailing_exit():
    # 涨到+15%(peak=11.5)后回撤8%(11.5*0.92=10.58) -> 移动止盈, 卖价≈10.58
    o,h,l,c = _ohlc([10,11.5,10.5,10.0],
                    highs=[10,11.5,11.0,10.5], lows=[10,11.0,10.5,10.0])
    r = BT.simulate_trade(o,h,l,c, entry_idx=0, mode="trailing", sl=-0.05, maxhold=10, cost=0.002, trail=0.08)
    assert r[3]=="移动止盈", r
    assert abs(r[1] - (11.5*0.92/10 - 1)) < 1e-9, r

def test_trailing_hard_stop_priority():
    # 第2根 Low破-5% -> 硬止损优先
    o,h,l,c = _ohlc([10,9.3], highs=[10,11.6], lows=[10,9.3])
    r = BT.simulate_trade(o,h,l,c, entry_idx=0, mode="trailing", sl=-0.05, maxhold=10, cost=0.002, trail=0.08)
    assert r[3]=="止损", r

def test_trend_exit_break_ma():
    # ma 给定; 第3根 收盘<ma -> 破MA卖(以c[i]计)
    o,h,l,c = _ohlc([10,10.5,10.2,10.4], highs=[10,10.6,10.3,10.5], lows=[10,10.4,10.1,10.3])
    ma = np.array([np.nan, np.nan, 10.3, 10.3])   # i=2: c=10.2<10.3 触发
    r = BT.simulate_trade(o,h,l,c, entry_idx=0, mode="trend", sl=-0.20, maxhold=10, cost=0.002, ma=ma)
    assert r[3]=="破MA" and r[0]==2, r
    assert abs(r[1]-(10.2/10-1))<1e-9, r

def test_ma_helper():
    import numpy as np
    c = np.array([1.0,2,3,4,5], float)
    m = BT._ma(c, 3)
    assert np.isnan(m[0]) and np.isnan(m[1]) and abs(m[2]-2.0)<1e-9 and abs(m[4]-4.0)<1e-9, m
```
`__main__` 追加:`test_trailing_exit(); test_trailing_hard_stop_priority(); test_trend_exit_break_ma(); test_ma_helper();`(在 print 之前)。

- [ ] **Step 2: 跑测试确认失败** — `cd data/profit_mining && python3 test_setup_backtest.py` → 失败(mode 参数不支持/_ma 不存在)。

- [ ] **Step 3: 实现** — 在 `setup_backtest.py` 把 `simulate_trade` 整体替换 + 加 `_ma`:
```python
def _ma(c, n=10):
    c = np.asarray(c, float)
    out = np.full(len(c), np.nan)
    if len(c) >= n:
        cs = np.cumsum(np.insert(c, 0, 0.0))
        out[n - 1:] = (cs[n:] - cs[:-n]) / n
    return out


def simulate_trade(o, h, l, c, entry_idx, mode="fixed", tp=TP, sl=SL, maxhold=MAXHOLD,
                   cost=COST, trail=0.08, ma=None):
    """入场=open[entry_idx]; mode∈{fixed,trailing,trend}; 返回 (exit_idx,gross,net,reason) 或 None。
    fixed: 止损(同日优先)/止盈/到期。 trailing: 硬止损/峰值回撤trail卖(入场根不触发回撤)/到期(maxhold由调用方传).
    trend: 硬止损/收盘<ma卖(入场根不触发)/到期; ma需与序列等长。"""
    n = len(c)
    if entry_idx >= n:
        return None
    entry = o[entry_idx]
    if not np.isfinite(entry) or entry <= 0:
        return None
    sl_px = entry * (1 + sl)
    last = min(entry_idx + maxhold - 1, n - 1)
    if mode == "fixed":
        tp_px = entry * (1 + tp)
        for i in range(entry_idx, last + 1):
            if l[i] <= sl_px:
                return (i, sl, sl - cost, "止损")
            if h[i] >= tp_px:
                return (i, tp, tp - cost, "止盈")
        g = c[last] / entry - 1.0
        return (last, g, g - cost, "到期")
    if mode == "trailing":
        peak = h[entry_idx]
        for i in range(entry_idx, last + 1):
            if l[i] <= sl_px:
                return (i, sl, sl - cost, "止损")
            peak = max(peak, h[i])
            if i > entry_idx and l[i] <= peak * (1 - trail):
                g = peak * (1 - trail) / entry - 1.0
                return (i, g, g - cost, "移动止盈")
        g = c[last] / entry - 1.0
        return (last, g, g - cost, "到期")
    if mode == "trend":
        for i in range(entry_idx, last + 1):
            if l[i] <= sl_px:
                return (i, sl, sl - cost, "止损")
            if i > entry_idx and ma is not None and np.isfinite(ma[i]) and c[i] < ma[i]:
                g = c[i] / entry - 1.0
                return (i, g, g - cost, "破MA")
        g = c[last] / entry - 1.0
        return (last, g, g - cost, "到期")
    raise ValueError(mode)
```

- [ ] **Step 4: 跑测试确认通过** — `cd data/profit_mining && python3 test_setup_backtest.py` → `ALL setup_backtest OK`(含新 + 原 fixed 测试全过=向后兼容)。删 `__pycache__`。

- [ ] **Step 5: 提交**：
```bash
git add data/profit_mining/setup_backtest.py data/profit_mining/test_setup_backtest.py
git commit -m "feat(backtest): simulate_trade 加 trailing/trend 退出模式 + _ma(fixed向后兼容)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: run_backtest 加 mode/择时 + main 6配置

**Files:** Modify `data/profit_mining/setup_backtest.py`(run_backtest 加参数 + 加 _riskoff_days + 重写 main)。

- [ ] **Step 1: 替换 run_backtest**(加 mode/maxhold/riskoff;trend 算 ma;择时 gate):
```python
def run_backtest(dates, codes, scores, mode="fixed", maxhold=MAXHOLD, riskoff=None):
    """逐日 top-N 选股(在持去重) -> 每笔模拟。mode 透传 simulate_trade;riskoff=不开新仓的日期集合(择时)。"""
    riskoff = riskoff or set()
    uniq_days = np.unique(dates)
    by_day = {}
    for dt, cd, s in zip(dates, codes, scores):
        by_day.setdefault(dt, ([], []))
        by_day[dt][0].append(cd); by_day[dt][1].append(s)
    kl_cache = {}
    def kl(code):
        if code not in kl_cache:
            kl_cache[code] = _load_kline(code)
        return kl_cache[code]
    held = {}
    trades = []
    for dt in uniq_days:
        for cd in [c for c, ed in held.items() if ed <= dt]:
            del held[cd]
        if dt in riskoff:            # 择时: risk-off 当日不开新仓
            continue
        cs, ss = by_day[dt]
        for cd in select_topn(cs, np.array(ss), set(held.keys()), TOPN):
            df = kl(cd)
            if df is None:
                continue
            t = df.index.get_indexer([np.datetime64(dt)])[0]
            if t < 0 or t + 1 >= len(df):
                continue
            o = df["Open"].to_numpy(float); h = df["High"].to_numpy(float)
            lo = df["Low"].to_numpy(float); c = df["Close"].to_numpy(float)
            ma = _ma(c, 10) if mode == "trend" else None
            r = simulate_trade(o, h, lo, c, t + 1, mode=mode, maxhold=maxhold, ma=ma)
            if r is None:
                continue
            exit_idx, gross, net, reason = r
            exit_dt = df.index[exit_idx].to_numpy().astype("datetime64[D]")
            held[cd] = exit_dt
            trades.append(dict(code=cd, entry=np.datetime64(dt), exit=exit_dt,
                               gross=gross, net=net, reason=reason))
    return trades
```

- [ ] **Step 2: 加 _riskoff_days + 重写 main(6配置)** — 加 `_riskoff_days()` 并整体替换 `main`:
```python
def _riskoff_days():
    """上证收盘<MA20 的交易日集合(datetime64[D]) -> 择时不开新仓。"""
    import pandas as pd
    ic = SM._load_index_close()
    ma20 = ic.rolling(20).mean()
    ro = ic.index[(ic < ma20).fillna(False)]
    return set(pd.DatetimeIndex(ro).values.astype("datetime64[D]"))


_CONFIGS = [
    ("C0_fixed",          "fixed",    10, False),
    ("C1_trailing",       "trailing", 30, False),
    ("C2_trend",          "trend",    30, False),
    ("C3_fixed_timing",   "fixed",    10, True),
    ("C4_trailing_timing","trailing", 30, True),
    ("C5_trend_timing",   "trend",    30, True),
]


def _eval_config(name, mode, maxhold, timing, dates, codes, scores, days, bench, riskoff):
    trades = run_backtest(dates, codes, scores, mode=mode, maxhold=maxhold,
                          riskoff=(riskoff if timing else None))
    _, curve = portfolio_curve(trades, days)
    nets = np.array([t["net"] for t in trades]) if trades else np.array([0.0])
    drets = np.diff(np.concatenate([[1.0], curve])) / np.concatenate([[1.0], curve[:-1]])
    reasons = {}
    for t in trades:
        reasons[t["reason"]] = reasons.get(t["reason"], 0) + 1
    excess = cum_return(curve) - (bench[-1] / bench[0] - 1)
    return dict(name=name, n=len(trades), win=(nets > 0).mean(), avg=nets.mean(),
                cum=cum_return(curve), ann=annual_return(curve, len(days)),
                sharpe=sharpe(drets), mdd=max_drawdown(curve), excess=excess,
                reasons=reasons)


def main():
    t0 = time.time()
    dates, codes, scores = score_oos("fwd_10_10")
    print(f"  OOS打分 {len(scores)} bar", flush=True)
    days = np.unique(dates)
    bench = _bench_curve(days)
    riskoff = _riskoff_days()
    rows = []
    for name, mode, maxhold, timing in _CONFIGS:
        r = _eval_config(name, mode, maxhold, timing, dates, codes, scores, days, bench, riskoff)
        rows.append(r)
        print(f"  {name}: 笔{r['n']} 胜率{r['win']:.3f} 累计{r['cum']:.3f} "
              f"年化{r['ann']:.3f} Sharpe{r['sharpe']:.2f} 回撤{r['mdd']:.3f} 超额{r['excess']:.3f}", flush=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    bench_cum = bench[-1] / bench[0] - 1
    L = [f"# 起涨回测v2 执行精细化对比 (fwd_10_10 GBDT, OOS {SM.OOS_START}~{SM.OOS_END})\n",
         f"生成 {ts}；每日top{TOPN}等权·t+1开盘买·扣{COST:.1%}成本；上证同期累计 {bench_cum:.3f}\n",
         "| 配置 | 退出 | 择时 | 笔数 | 胜率 | 平均净 | 累计 | 年化 | Sharpe | 最大回撤 | 超额(vs上证) |",
         "|------|------|------|------|------|--------|------|------|--------|----------|--------------|"]
    cfgmap = {c[0]: c for c in _CONFIGS}
    for r in rows:
        _, mode, mh, timing = cfgmap[r["name"]]
        L.append(f"| {r['name']} | {mode} | {'是' if timing else '否'} | {r['n']} | {r['win']:.3f} | "
                 f"{r['avg']:.4f} | {r['cum']:.3f} | {r['ann']:.3f} | {r['sharpe']:.2f} | {r['mdd']:.3f} | "
                 f"**{r['excess']:+.3f}** |")
    best = max(rows, key=lambda r: r["excess"])
    L.append(f"\n## 结论\n- **最优配置: {best['name']}** 超额 {best['excess']:+.3f}(累计{best['cum']:.3f} vs 上证{bench_cum:.3f})")
    L.append("- 退出占比(各配置): " + " | ".join(
        f"{r['name']}:" + ",".join(f"{k}{v}" for k, v in r["reasons"].items()) for r in rows))
    out = f"/app/data/commonality_reports/起涨回测v2_多配置_{ts}.md"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L), flush=True); print("  写", out, flush=True)
    print(f"  用时{int(time.time()-t0)}s", flush=True)
```

- [ ] **Step 3: 语法 + 小样本冒烟(40股panel仍在容器)** —
```bash
cd data/profit_mining && python3 -c "import ast; ast.parse(open('setup_backtest.py').read()); print('syntax OK')"
docker exec agentsstock1 sh -c 'rm -f /app/data/profit_mining/setup_panel.npz' || true
docker exec -w /app/data/profit_mining agentsstock1 sh -c 'NPROC=4 python3 -c "import setup_modeling as M; M.build_panel(limit=60)" && python3 setup_backtest.py'
```
Expected: 打印 6 行配置(C0..C5 各 笔数/胜率/累计/超额)、写 `起涨回测v2_多配置_*.md`。无 traceback。(60股小样本仅冒烟看流程+6配置都出。)

- [ ] **Step 4: 提交**(仅 .py)：
```bash
git add data/profit_mining/setup_backtest.py
git commit -m "feat(backtest): run_backtest加mode/择时 + main 6配置横向对比

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: 全量跑 + 归档 + 结论

**Files:** 无代码改动。

- [ ] **Step 1: 后台全量(宿主持有会话): 重建全市场panel + 6配置回测**:
```bash
docker exec agentsstock1 sh -c 'cd /app/data/profit_mining && rm -f setup_panel.npz && NPROC=10 python3 -c "import setup_modeling as M; M.build_panel()" > _btv2_panel.log 2>&1 && python3 setup_backtest.py > _btv2_run.log 2>&1 && echo DONE'
```
(run_in_background;勿用-d。建面板~5min+6配置(打分1次+6次模拟,各逐笔load kline)~15-25min。等完成通知。)

- [ ] **Step 2: 归档 report/**:
```bash
TS=$(date +%Y%m%d_%H%M%S); DEST=/home/tdxback/report/起涨回测v2_$TS; mkdir -p "$DEST"
cp /home/tdxback/aiagents-stock/data/profit_mining/_btv2_*.log "$DEST"/ 2>/dev/null
cp /home/tdxback/aiagents-stock/data/commonality_reports/起涨回测v2_多配置_*.md "$DEST"/ 2>/dev/null
ls "$DEST"
```

- [ ] **Step 3: 读结论报告用户** — 读 `起涨回测v2_多配置_*.md`:6 配置横向表(超额/Sharpe/回撤/胜率/退出占比),最优配置;移动止盈/趋势退出是否让赢家跑(到期/移动止盈占比升、累计升)、择时是否降回撤/提超额;**对比 v1 基准(C0 应≈v1: 年化+8%/超额-18.7%)** 看精细化是否真把薄edge转可用(超额转正或显著提升)。

- [ ] **Step 4: 登记 DATA_FILES + 提交** — DATA_FILES.md 把 setup_backtest 行更新为"v2多配置(trailing/trend/择时,起涨回测v2_多配置_*.md)";提交。

---

## Self-Review

**1. Spec coverage:**
- trailing/trend/fixed 退出 → Task1 simulate_trade mode ✓
- 大盘择时<MA20停开仓 → Task2 _riskoff_days + run_backtest riskoff gate ✓
- 6配置矩阵 → Task2 _CONFIGS + main 循环 ✓
- 一次打分复用 → main score_oos 一次,循环配置 ✓
- 评估 笔级+组合+超额+横向表 → Task2 _eval_config + main 表 ✓
- 向后兼容(fixed默认,现有测试过) → simulate_trade mode="fixed" 默认 ✓
- 复用 score_oos/portfolio_curve/metrics,不动其他 → ✓
- 合成单测 trailing/trend/硬止损/_ma → Task1 ✓
**2. Placeholder scan:** 无TBD;每步完整代码+命令。
**3. Type consistency:** simulate_trade 新签名 mode 在 entry_idx 后(现有测试用关键字 tp/sl/maxhold/cost→兼容);run_backtest 加 mode/maxhold/riskoff kw 默认(main 调用一致);_riskoff_days 返回 datetime64[D] set 与 uniq_days(datetime64[D]) 可 `dt in riskoff`;_eval_config 返回 dict 键与 main 表一致;trend mode 在 run_backtest 算 _ma(c,10) 传 ma。