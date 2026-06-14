# 起涨打分模型回测(setup_backtest) 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 fwd_10_10 GBDT 在 OOS 选股(每日top10等权,t+1开盘买,止盈+10%/止损-5%/持10日,扣0.2%成本),算净值曲线 vs 上证,判断扣成本后实战价值。

**Architecture:** `setup_modeling` 的 panel 加 codes 列(向后兼容);新建 `setup_backtest.py`(score_oos重训GBDT打分 / simulate_trade纯函数 / run_backtest每日选股+逐笔 / portfolio_curve槽位法 / metrics / main+报告)。复用 setup_modeling/_load_kline,不动其他。

**Tech Stack:** Python3+numpy+pandas+lightgbm。容器 agentsstock1。测试 `python3 test_*.py`。

参考 spec：`docs/superpowers/specs/2026-06-14-setup-backtest-design.md`

确认事实(当前代码,无需重查)：
- `setup_modeling`:`_panel_proc(code)` 返回 (X[float32], Y[n,4 float32], dates[datetime64D]);`build_panel`(行149-159)用 Xs/Ys/dts 列表 vstack 后 `np.savez(PANEL, X=, Y=, dates=int64, cols=, label_names=)`;`PANEL="/app/data/profit_mining/setup_panel.npz"`。复用函数:`fit_gbdt(X,y,scale_pos_weight=1.0)`、`_subsample_train(Xtr,ytr,ratio=5,seed=0)`、`col_median(X)`、`fill_na(X,med)`、`time_split_mask(dates,train_end,oos_start,oos_end)`、`TRAIN_END/OOS_START/OOS_END`、`LABELS`(列序: fwd_6_20,fwd_10_10,fwd_10_20,excess_10_20)。
- `mine_commonality._load_kline(code)`→datetime索引 OHLCV df 或 None;`setup_modeling._load_index_close()`→上证Close Series。

---

### Task 1: panel 加 codes 列

**Files:** Modify `data/profit_mining/setup_modeling.py`(2 处:_panel_proc 返回加 codes;build_panel 收集存 codes)。

- [ ] **Step 1: 编辑 _panel_proc** — 把返回行
```python
        dates = df.index.to_numpy().astype("datetime64[D]")
        return X.astype(np.float32), Y.astype(np.float32), dates
```
改为(加等长 code 数组):
```python
        dates = df.index.to_numpy().astype("datetime64[D]")
        codes = np.full(len(dates), code, dtype=object)
        return X.astype(np.float32), Y.astype(np.float32), dates, codes
```

- [ ] **Step 2: 编辑 build_panel** — 现有(行149-160附近):
```python
    Xs, Ys, dts = [], [], []
    with Pool(nproc) as p:
        for r in p.imap_unordered(_panel_proc, codes, chunksize=8):
            if r is None:
                continue
            X, Y, dates = r
            Xs.append(X); Ys.append(Y); dts.append(dates)
    X = np.vstack(Xs); Y = np.vstack(Ys)
    dates = np.concatenate(dts).astype("datetime64[D]")
    names = np.array([n for n, _, _ in LABELS])
    np.savez(PANEL, X=X, Y=Y, dates=dates.astype("int64"),
             cols=np.array(SF.FEATURE_COLS), label_names=names)
    return X, Y, dates
```
替换为(注意循环变量 `codes` 与池 `codes` 重名,改用 cs 收集股票码列):
```python
    Xs, Ys, dts, css = [], [], [], []
    with Pool(nproc) as p:
        for r in p.imap_unordered(_panel_proc, codes, chunksize=8):
            if r is None:
                continue
            X, Y, dates, cs = r
            Xs.append(X); Ys.append(Y); dts.append(dates); css.append(cs)
    X = np.vstack(Xs); Y = np.vstack(Ys)
    dates = np.concatenate(dts).astype("datetime64[D]")
    code_arr = np.concatenate(css)
    names = np.array([n for n, _, _ in LABELS])
    np.savez(PANEL, X=X, Y=Y, dates=dates.astype("int64"), codes=code_arr,
             cols=np.array(SF.FEATURE_COLS), label_names=names)
    return X, Y, dates
```
(main 仍只用 X/Y/dates,不读 codes,向后兼容。)

- [ ] **Step 3: 语法 + limit 冒烟验证 panel 含 codes** —
```bash
cd data/profit_mining && python3 -c "import ast; ast.parse(open('setup_modeling.py').read()); print('syntax OK')"
docker exec agentsstock1 sh -c 'rm -f /app/data/profit_mining/setup_panel.npz'
docker exec -w /app/data/profit_mining agentsstock1 sh -c 'NPROC=4 python3 -c "import setup_modeling as M; M.build_panel(limit=40)"'
docker exec agentsstock1 python3 -c "
import numpy as np
d=np.load('/app/data/profit_mining/setup_panel.npz', allow_pickle=True)
print('keys:', list(d.keys()))
print('X', d['X'].shape, 'codes', d['codes'].shape, 'sample codes', d['codes'][:3], d['codes'][-1])
assert d['codes'].shape[0]==d['X'].shape[0]
print('OK codes 与 X 行数一致')
"
```
Expected: keys 含 `codes`;codes 行数 == X 行数;打印若干股票码。无异常。

- [ ] **Step 4: 提交**：
```bash
git add data/profit_mining/setup_modeling.py
git commit -m "feat(backtest): setup_modeling panel 加 codes 列(向后兼容,回测定位股票)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: setup_backtest 核心纯函数(simulate_trade + metrics + 选股)

**Files:** Create `data/profit_mining/setup_backtest.py` + `data/profit_mining/test_setup_backtest.py`

- [ ] **Step 1: 写失败测试** — `data/profit_mining/test_setup_backtest.py`：
```python
import numpy as np
import setup_backtest as BT

def _ohlc(seq_close, highs=None, lows=None):
    c = np.array(seq_close, float)
    o = c.copy()
    h = np.array(highs, float) if highs is not None else c.copy()
    l = np.array(lows, float) if lows is not None else c.copy()
    return o, h, l, c

def test_trade_take_profit():
    # entry=open[0]=10; 第2根High到11(+10%) -> 止盈, 净=0.10-0.002
    o,h,l,c = _ohlc([10,10.5,11.0,10.0], highs=[10,10.5,11.0,10.0], lows=[10,10.2,10.8,9.9])
    r = BT.simulate_trade(o,h,l,c, entry_idx=0, tp=0.10, sl=-0.05, maxhold=10, cost=0.002)
    exit_idx, gross, net, reason = r
    assert reason=="止盈" and abs(gross-0.10)<1e-9 and abs(net-0.098)<1e-9, r

def test_trade_stop_loss():
    o,h,l,c = _ohlc([10,9.8,9.4], highs=[10,9.9,9.6], lows=[10,9.8,9.4])  # 第3根Low9.4<=9.5(-5%)
    r = BT.simulate_trade(o,h,l,c, entry_idx=0, tp=0.10, sl=-0.05, maxhold=10, cost=0.002)
    assert r[3]=="止损" and abs(r[1]+0.05)<1e-9 and abs(r[2]-(-0.052))<1e-9, r

def test_trade_maxhold():
    # 横盘到期(maxhold=3): 收盘10.3, gross=0.03
    o,h,l,c = _ohlc([10,10.1,10.3], highs=[10,10.2,10.4], lows=[10,9.9,10.0])
    r = BT.simulate_trade(o,h,l,c, entry_idx=0, tp=0.10, sl=-0.05, maxhold=3, cost=0.002)
    assert r[3]=="到期" and abs(r[1]-0.03)<1e-9 and abs(r[2]-0.028)<1e-9, r

def test_trade_same_bar_tp_and_sl_takes_sl():
    # 同一根 High破+10% 且 Low破-5% -> 保守取止损
    o,h,l,c = _ohlc([10,10.0], highs=[10,11.0], lows=[10,9.4])
    r = BT.simulate_trade(o,h,l,c, entry_idx=0, tp=0.10, sl=-0.05, maxhold=10, cost=0.002)
    assert r[3]=="止损", r

def test_select_topn_dedupe():
    # 当日分: A0.9 B0.8 C0.7; topn=2 且 B在持 -> 选 A,C
    picks = BT.select_topn(["A","B","C"], [0.9,0.8,0.7], held={"B"}, topn=2)
    assert picks==["A","C"], picks

def test_max_drawdown_and_cum():
    curve = np.array([1.0, 1.2, 0.9, 1.1])
    assert abs(BT.cum_return(curve) - 0.10) < 1e-9
    assert abs(BT.max_drawdown(curve) - (0.9/1.2 - 1)) < 1e-9   # -0.25

def test_sharpe_zero_std():
    assert BT.sharpe(np.array([0.0,0.0,0.0])) == 0.0

if __name__ == "__main__":
    test_trade_take_profit(); test_trade_stop_loss(); test_trade_maxhold()
    test_trade_same_bar_tp_and_sl_takes_sl(); test_select_topn_dedupe()
    test_max_drawdown_and_cum(); test_sharpe_zero_std()
    print("ALL setup_backtest OK")
```

- [ ] **Step 2: 跑测试确认失败** — `cd data/profit_mining && python3 test_setup_backtest.py` → `ModuleNotFoundError`。

- [ ] **Step 3: 实现** — `data/profit_mining/setup_backtest.py`(Task2 部分:纯函数)：
```python
# setup_backtest.py —— 起涨打分模型回测: fwd_10_10 GBDT 选股 + 止盈止损 + 净值 vs 上证。
import os, sys, time
import numpy as np

TP, SL, MAXHOLD, COST, TOPN = 0.10, -0.05, 10, 0.002, 10
SLOTS = TOPN * MAXHOLD   # 槽位法满仓上限近似


def simulate_trade(o, h, l, c, entry_idx, tp=TP, sl=SL, maxhold=MAXHOLD, cost=COST):
    """某股 OHLC(numpy) + 入场行 entry_idx(=t+1) -> (exit_idx, gross, net, reason)。
    entry=open[entry_idx]; 逐日先判止损(同日同破取止损)再止盈; 否则持满maxhold收盘卖。
    entry非法 -> None。"""
    n = len(c)
    if entry_idx >= n:
        return None
    entry = o[entry_idx]
    if not np.isfinite(entry) or entry <= 0:
        return None
    tp_px, sl_px = entry * (1 + tp), entry * (1 + sl)
    last = min(entry_idx + maxhold - 1, n - 1)
    for i in range(entry_idx, last + 1):
        if l[i] <= sl_px:
            return (i, sl, sl - cost, "止损")
        if h[i] >= tp_px:
            return (i, tp, tp - cost, "止盈")
    gross = c[last] / entry - 1.0
    return (last, gross, gross - cost, "到期")


def select_topn(day_codes, day_scores, held, topn=TOPN):
    """当日 codes/scores -> 按分降序取不在 held 的前 topn 个 code。"""
    order = np.argsort(day_scores)[::-1]
    out = []
    for j in order:
        cd = day_codes[j]
        if cd in held:
            continue
        out.append(cd)
        if len(out) >= topn:
            break
    return out


def cum_return(curve):
    return float(curve[-1] / curve[0] - 1.0)


def annual_return(curve, n_days):
    return float((curve[-1] / curve[0]) ** (252.0 / max(n_days, 1)) - 1.0)


def max_drawdown(curve):
    peak = -1e18; mdd = 0.0
    for v in curve:
        peak = max(peak, v)
        if peak > 0:
            mdd = min(mdd, v / peak - 1.0)
    return float(mdd)


def sharpe(daily_rets):
    r = np.asarray(daily_rets, float)
    sd = r.std()
    return 0.0 if sd == 0 else float(r.mean() / sd * np.sqrt(252))
```

- [ ] **Step 4: 跑测试确认通过** — `cd data/profit_mining && python3 test_setup_backtest.py` → `ALL setup_backtest OK`。删 `__pycache__`。

- [ ] **Step 5: 提交**：
```bash
git add data/profit_mining/setup_backtest.py data/profit_mining/test_setup_backtest.py
git commit -m "feat(backtest): setup_backtest 纯函数(simulate_trade/select_topn/metrics)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: score_oos + run_backtest + portfolio_curve + main

**Files:** Modify `data/profit_mining/setup_backtest.py`(追加)。

- [ ] **Step 1: 追加实现** — 追加到 `setup_backtest.py`：
```python
import setup_modeling as SM
import setup_features as SF
from mine_commonality import _load_kline

PANEL = "/app/data/profit_mining/setup_panel.npz"


def score_oos(label="fwd_10_10"):
    """载panel,train上重训GBDT(指定标签),返回OOS有效行 (dates[datetime64D], codes, scores)。"""
    d = np.load(PANEL, allow_pickle=True)
    X = d["X"]; Y = d["Y"]; dates = d["dates"].astype("datetime64[D]")
    codes = d["codes"]; names = list(d["label_names"])
    j = names.index(label)
    y = Y[:, j]
    tr, oos = SM.time_split_mask(dates, SM.TRAIN_END, SM.OOS_START, SM.OOS_END)
    valid_tr = tr & ~np.isnan(y); valid_oos = oos & ~np.isnan(y)
    med = SM.col_median(X[valid_tr])
    Xtr = SM.fill_na(X[valid_tr], med); ytr = y[valid_tr]
    Xsub, ysub = SM._subsample_train(Xtr, ytr, ratio=5)
    bst = SM.fit_gbdt(Xsub, ysub)
    Xoos = SM.fill_na(X[valid_oos], med)
    sc = bst.predict(Xoos)
    return dates[valid_oos], codes[valid_oos], sc.astype(float)


def run_backtest(dates, codes, scores):
    """逐日 top-N 选股(在持去重) -> 每笔 _load_kline 定位 t+1 模拟 -> trades list。"""
    uniq_days = np.unique(dates)
    by_day = {}
    for dt, cd, s in zip(dates, codes, scores):
        by_day.setdefault(dt, ([], [])); by_day[dt][0].append(cd); by_day[dt][1].append(s)
    kl_cache = {}
    def kl(code):
        if code not in kl_cache:
            df = _load_kline(code)
            kl_cache[code] = df
        return kl_cache[code]
    held = {}   # code -> exit_date(datetime64D); 持仓中不重复买
    trades = []
    for dt in uniq_days:
        # 释放已到期
        for cd in [c for c, ed in held.items() if ed <= dt]:
            del held[cd]
        cs, ss = by_day[dt]
        for cd in select_topn(cs, np.array(ss), set(held.keys()), TOPN):
            df = kl(cd)
            if df is None:
                continue
            idxpos = df.index.get_indexer([np.datetime64(dt)])
            t = idxpos[0]
            if t < 0 or t + 1 >= len(df):
                continue
            o = df["Open"].to_numpy(float); h = df["High"].to_numpy(float)
            lo = df["Low"].to_numpy(float); c = df["Close"].to_numpy(float)
            r = simulate_trade(o, h, lo, c, t + 1)
            if r is None:
                continue
            exit_idx, gross, net, reason = r
            exit_dt = df.index[exit_idx].to_numpy().astype("datetime64[D]")
            held[cd] = exit_dt
            trades.append(dict(code=cd, entry=np.datetime64(dt), exit=exit_dt,
                               gross=gross, net=net, reason=reason))
    return trades


def portfolio_curve(trades, oos_days):
    """槽位法日净值: 每笔占1/SLOTS资金,从entry+1日起到exit日按其net线性摊到持有日(简化:净收益记在exit日)。
    返回 (days, curve)。简化口径: 日收益 = 当日所有exit笔的 net 之和 / SLOTS。"""
    days = np.unique(oos_days)
    ret_by_day = {d: 0.0 for d in days}
    for tr in trades:
        ed = tr["exit"]
        if ed in ret_by_day:
            ret_by_day[ed] += tr["net"] / SLOTS
    curve = [1.0]
    for d in days:
        curve.append(curve[-1] * (1 + ret_by_day[d]))
    return days, np.array(curve[1:])


def _bench_curve(oos_days):
    ic = SM._load_index_close()
    s = ic.reindex(__import__("pandas").to_datetime(oos_days)).ffill()
    v = s.to_numpy(float); v = v / v[0]
    return v


def main():
    t0 = time.time()
    dates, codes, scores = score_oos("fwd_10_10")
    print(f"  OOS打分 {len(scores)} bar", flush=True)
    trades = run_backtest(dates, codes, scores)
    oos_days = np.unique(dates)
    days, curve = portfolio_curve(trades, oos_days)
    bench = _bench_curve(days)
    nets = np.array([t["net"] for t in trades])
    reasons = {}
    for t in trades:
        reasons[t["reason"]] = reasons.get(t["reason"], 0) + 1
    drets = np.diff(np.concatenate([[1.0], curve])) / np.concatenate([[1.0], curve[:-1]])
    ts = time.strftime("%Y%m%d_%H%M%S")
    L = [f"# 起涨打分模型回测 (fwd_10_10 GBDT, OOS {SM.OOS_START}~{SM.OOS_END})\n",
         f"生成 {ts}；策略: 每日top{TOPN}等权·t+1开盘买·止盈+{TP:.0%}/止损{SL:.0%}/持{MAXHOLD}日·扣{COST:.1%}成本\n",
         f"## 笔级\n- 总笔数 {len(trades)};胜率(净>0) {(nets>0).mean():.3f};平均净收益 {nets.mean():.4f}",
         f"- 退出占比: " + ", ".join(f"{k} {v}({v/max(len(trades),1):.0%})" for k, v in reasons.items()),
         f"## 组合(槽位法 SLOTS={SLOTS})\n- 累计 {cum_return(curve):.3f};年化 {annual_return(curve,len(days)):.3f};"
         f"Sharpe {sharpe(drets):.2f};最大回撤 {max_drawdown(curve):.3f}",
         f"- 上证同期: 累计 {bench[-1]/bench[0]-1:.3f};**策略超额 {cum_return(curve)-(bench[-1]/bench[0]-1):.3f}**",
         f"\n用时 {int(time.time()-t0)}s"]
    out = f"/app/data/commonality_reports/起涨回测_{ts}.md"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, "w", encoding="utf-8").write("\n".join(L) + "\n")
    # 净值CSV
    import csv as _csv
    with open(f"/app/data/commonality_reports/起涨回测_净值_{ts}.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = _csv.writer(f); w.writerow(["date", "strategy", "bench"])
        for dd, sv, bv in zip(days, curve, bench):
            w.writerow([str(dd), f"{sv:.6f}", f"{bv:.6f}"])
    print("\n".join(L), flush=True); print("  写", out, flush=True)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 语法检查** — `cd data/profit_mining && python3 -c "import ast; ast.parse(open('setup_backtest.py').read()); print('syntax OK')"` → `syntax OK`。

- [ ] **Step 3: 小样本冒烟(用 Task1 的 40 股 panel,limit panel 已在容器)** —
```bash
docker exec -w /app/data/profit_mining agentsstock1 sh -c 'python3 setup_backtest.py'
```
Expected: 打印 `OOS打分 N bar`、笔级(总笔数/胜率/平均净收益/退出占比)、组合(累计/年化/Sharpe/回撤/上证/超额)、`写 ...起涨回测_*.md`。无 traceback。(注:当前 panel 是 Task1 的 40 股小样本,数值仅冒烟,看流程通。)

- [ ] **Step 4: 提交**(仅 .py;报告 gitignore)：
```bash
git add data/profit_mining/setup_backtest.py
git commit -m "feat(backtest): score_oos+run_backtest+portfolio_curve+main(净值vs上证)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: 全量面板重建 + 全量回测 + 归档结论

**Files:** 无代码改动。

- [ ] **Step 1: 后台全量(宿主持有会话): 重建全市场panel(含codes) + 回测**:
```bash
docker exec agentsstock1 sh -c 'cd /app/data/profit_mining && rm -f setup_panel.npz && NPROC=10 python3 -c "import setup_modeling as M; M.build_panel()" > _bt_panel.log 2>&1 && python3 setup_backtest.py > _bt_run.log 2>&1'
```
(run_in_background;勿用-d。建面板~5min+打分/回测(逐笔load kline)~10-20min。等完成通知。)

- [ ] **Step 2: 归档 report/**:
```bash
TS=$(date +%Y%m%d_%H%M%S); DEST=/home/tdxback/report/起涨回测_$TS; mkdir -p "$DEST"
cp /home/tdxback/aiagents-stock/data/profit_mining/_bt_*.log "$DEST"/ 2>/dev/null
cp /home/tdxback/aiagents-stock/data/commonality_reports/起涨回测_*.md "$DEST"/ 2>/dev/null
cp /home/tdxback/aiagents-stock/data/commonality_reports/起涨回测_净值_*.csv "$DEST"/ 2>/dev/null
ls "$DEST"
```

- [ ] **Step 3: 读结论报告用户** — 读 `起涨回测_*.md`:笔级胜率/平均净收益/退出占比;组合累计·年化·Sharpe·最大回撤;**对比上证超额**;结论:扣成本后策略是否跑赢基准、是否可用(配合 v2 的 AUC0.68/lift1.88 给整体判断)。

- [ ] **Step 4: 登记 DATA_FILES + 提交** — DATA_FILES.md 加 setup_backtest 产物行(起涨回测_*.md/净值csv),提交。

---

## Self-Review

**1. Spec coverage:**
- panel加code → Task1 ✓
- fwd_10_10 GBDT 重训OOS打分(train统计/下采样) → Task3 score_oos ✓
- 每日top10去重在持 → Task2 select_topn + Task3 run_backtest held ✓
- t+1开盘买 → Task3 simulate_trade(entry_idx=t+1) ✓
- 止盈+10%/止损-5%/持10日/同破取止损 → Task2 simulate_trade ✓
- 扣0.2%成本 → net=gross-cost ✓
- 基准上证 → _bench_curve ✓
- 笔级+组合指标(累计/年化/Sharpe/回撤/超额) → Task2 metrics + Task3 main ✓
- 报告+净值csv+归档 → Task3/4 ✓
- 复用setup_modeling/_load_kline,不动其他 → import only ✓
- 合成单测 simulate_trade/选股/metrics → Task2 ✓

**2. Placeholder scan:** 无TBD;每步完整代码+命令。

**3. Type consistency:** _panel_proc 返回4元组(加codes)↔build_panel解包4元组;panel新增 codes 键↔score_oos 读 d["codes"];simulate_trade 返回 (exit_idx,gross,net,reason) ↔ run_backtest 解包一致;select_topn(day_codes,day_scores数组,held集合,topn)↔run_backtest 调用一致;metrics(cum/annual/maxdd/sharpe)输入 curve numpy↔portfolio_curve 输出一致;SM 复用函数签名(fit_gbdt/_subsample_train/col_median/fill_na/time_split_mask/_load_index_close/TRAIN_END等)与现状一致。注:run_backtest 用 df.index.get_indexer 定位日期需 df.index 为 DatetimeIndex(_load_kline 是);portfolio_curve 简化口径(net记exit日)已在docstring注明。