# 收紧标签迭代(起涨打分模型v2) 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 特征不变,把标签换成4组前向标签(fwd_6_20基准/fwd_10_10/fwd_10_20/excess_10_20)×两模型,看收紧目标能否放大OOS AUC/lift。

**Architecture:** `setup_features.py` 加 `label_excess`;`setup_modeling.py` 把单标签(yf/yz)重构为标签矩阵 Y[n,4](LABELS配置),main 逐标签评估,去 y_zz。复用现有全套(logistic/GBDT/auc/lift/切分)。不动其他脚本。

**Tech Stack:** Python3+numpy+pandas+lightgbm。容器 agentsstock1。测试 `python3 test_*.py`。

参考 spec：`docs/superpowers/specs/2026-06-14-tighter-labels-design.md`

确认事实(当前代码,无需重查)：
- `setup_features.label_fwd(df,H=20,X=0.06)`(max-High口径,末尾不足H→NaN);`FEATURE_COLS` 21列;`compute_features(df,idx_close,turn)`。
- `setup_modeling.py` 现状:`_panel_proc`(116-125)返回 (X,yf,yz,dates);`build_panel`(129-147)存 yf/yz;`main`(196-216)载/建后 `_run_one("y_fwd...",X,yf,...)`+`_run_one("y_zz...",X,yz,...)`。常量 `PANEL/TRAIN_END/OOS_START/OOS_END/_IDX/_TURN`、`_load_index_close()`、`_run_one(label_name,X,y,dates,lines)` 均已在。

---

### Task 1: setup_features 加 label_excess

**Files:** Modify `data/profit_mining/setup_features.py`(追加函数) + `data/profit_mining/test_setup_features.py`(追加测试)

- [ ] **Step 1: 追加失败测试** — 在 `data/profit_mining/test_setup_features.py` 的 `if __name__` 之前加测试函数,并在 `__main__` 调用它：
```python
def test_label_excess():
    # 个股大涨而大盘平 -> 超额>=10% =1; 个股跟随大盘小涨 -> excess<10% =0; 末尾不足H ->NaN
    n = 60
    idx = pd.date_range("2015-01-01", periods=n, freq="D")
    stock = pd.Series([10.0]*5 + [13.0]*55, index=idx)          # t=0..4 后将涨30%
    big = pd.Series([100.0]*n, index=idx)                        # 大盘平
    d = pd.DataFrame({"Open": stock, "High": stock, "Low": stock, "Close": stock,
                      "Volume": pd.Series([1.0]*n, index=idx)}, index=idx)
    idx_close = big
    y = SF.label_excess(d, idx_close, H=20, X=0.10)
    assert y[0] == 1.0, y[0]                # 20日内个股+30%,大盘0 -> 超额30%>=10%
    assert np.isnan(y[n-1])                 # 末尾不足H
    # 个股跟随大盘同涨 -> 超额~0 -> 0
    stock2 = pd.Series(np.linspace(10, 13, n), index=idx)
    big2 = pd.Series(np.linspace(100, 130, n), index=idx)        # 大盘同比例涨
    d2 = pd.DataFrame({"Open": stock2, "High": stock2, "Low": stock2, "Close": stock2,
                       "Volume": pd.Series([1.0]*n, index=idx)}, index=idx)
    y2 = SF.label_excess(d2, big2, H=20, X=0.10)
    assert y2[0] == 0.0, y2[0]
    # idx_close=None -> 全NaN
    assert np.isnan(SF.label_excess(d, None)).all()
```
并在 `if __name__ == "__main__":` 块追加 `test_label_excess();`(在 print 之前)。

- [ ] **Step 2: 跑测试确认失败** — `cd data/profit_mining && python3 test_setup_features.py` → `AttributeError: module 'setup_features' has no attribute 'label_excess'`。

- [ ] **Step 3: 实现** — 在 `data/profit_mining/setup_features.py` 末尾(label_fwd 之后)追加：
```python
def label_excess(df, idx_close, H=20, X=0.10):
    """个股H日close-to-close收益 - 大盘H日收益 >= X ->1; 末尾不足H或大盘缺失 ->NaN。
    idx_close=对齐前的大盘收盘Series(reindex+ffill到df.index);None->全NaN。"""
    c = df["Close"].to_numpy(float)
    n = len(c); y = np.full(n, np.nan)
    if idx_close is None:
        return y
    ic = idx_close.reindex(df.index).ffill().to_numpy(float)
    for t in range(n):
        if t + H >= n:
            break
        if np.isnan(ic[t]) or np.isnan(ic[t + H]) or ic[t] <= 0 or c[t] <= 0:
            continue
        sr = c[t + H] / c[t] - 1.0
        ir = ic[t + H] / ic[t] - 1.0
        y[t] = 1.0 if (sr - ir) >= X else 0.0
    return y
```

- [ ] **Step 4: 跑测试确认通过** — `cd data/profit_mining && python3 test_setup_features.py` → `ALL setup_features OK`。删 `__pycache__`。

- [ ] **Step 5: 提交**：
```bash
git add data/profit_mining/setup_features.py data/profit_mining/test_setup_features.py
git commit -m "feat(model): setup_features 加 label_excess(close-to-close超额标签)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: setup_modeling 重构为标签矩阵(4标签) + 去 y_zz

**Files:** Modify `data/profit_mining/setup_modeling.py`(4 处替换)。

- [ ] **Step 1: 编辑1 — 加 LABELS 配置** — 在常量区(`TRAIN_END, OOS_START, OOS_END = ...` 那行之后)加：
```python
LABELS = [
    ("fwd_6_20",     "fwd",    dict(H=20, X=0.06)),
    ("fwd_10_10",    "fwd",    dict(H=10, X=0.10)),
    ("fwd_10_20",    "fwd",    dict(H=20, X=0.10)),
    ("excess_10_20", "excess", dict(H=20, X=0.10)),
]
```

- [ ] **Step 2: 编辑2 — 替换 _panel_proc** — 整体替换现有 `_panel_proc`：
```python
def _panel_proc(code):
    try:
        df = _load_kline(code)
        if df is None or len(df) < 300:
            return None
        X = SF.compute_features(df, idx_close=_IDX["close"], turn=_TURN.get(code))
        ys = []
        for name, kind, kw in LABELS:
            if kind == "fwd":
                ys.append(SF.label_fwd(df, **kw))
            else:
                ys.append(SF.label_excess(df, _IDX["close"], **kw))
        Y = np.column_stack(ys)
        dates = df.index.to_numpy().astype("datetime64[D]")
        return X.astype(np.float32), Y.astype(np.float32), dates
    except Exception:
        return None
```

- [ ] **Step 3: 编辑3 — 替换 build_panel** — 整体替换：
```python
def build_panel(limit=0):
    from multiprocessing import Pool
    _IDX["close"] = _load_index_close()
    _load_turn_by_code()
    codes = _universe()
    if limit:
        codes = codes[:limit]
    nproc = int(os.getenv("NPROC", "8"))
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

- [ ] **Step 4: 编辑4 — 替换 main(标签矩阵循环, 去y_zz, 报告名v2)** — 整体替换现有 `main`：
```python
def main():
    t0 = time.time()
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    if os.path.exists(PANEL) and not limit:
        d = np.load(PANEL, allow_pickle=True)
        X, Y = d["X"], d["Y"]; dates = d["dates"].astype("datetime64[D]")
        print(f"  载入面板 {X.shape} 标签 {Y.shape}", flush=True)
    else:
        X, Y, dates = build_panel(limit=limit)
        print(f"  构建面板 {X.shape} 标签 {Y.shape} 用时{int(time.time()-t0)}s", flush=True)
    lines = [f"# 起涨打分模型v2(收紧标签) OOS 评估\n\n生成 {time.strftime('%Y%m%d_%H%M%S')}，"
             f"训练≤{TRAIN_END} / OOS {OOS_START}~{OOS_END}，特征{len(SF.FEATURE_COLS)}列，"
             f"AUC>0.55才算有edge，lift@10%=OOS前10%分bar实际起涨率÷基线\n"]
    for j, (name, _, _) in enumerate(LABELS):
        _run_one(name, X, Y[:, j], dates, lines)
    ts = time.strftime("%Y%m%d_%H%M%S")
    out = f"/app/data/commonality_reports/起涨打分模型v2_评估_{ts}.md"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print(f"[打分模型v2] 用时{int(time.time()-t0)}s 写 {out}", flush=True)
    print("\n".join(lines), flush=True)
```

- [ ] **Step 5: 语法检查 + 删旧v1面板(结构变了) + limit=60端到端冒烟**：
```bash
cd data/profit_mining && python3 -c "import ast; ast.parse(open('setup_modeling.py').read()); print('syntax OK')"
docker exec agentsstock1 sh -c 'rm -f /app/data/profit_mining/setup_panel.npz'
docker exec -w /app/data/profit_mining agentsstock1 sh -c 'NPROC=4 python3 setup_modeling.py 60'
```
Expected: 打印 `构建面板 (N, 21) 标签 (N, 4)`、**4 个** `### 标签 fwd_6_20/fwd_10_10/fwd_10_20/excess_10_20` 段,各含 logistic + GBDT 的 AUC/lift,`写 ...起涨打分模型v2_评估_*.md`。无 traceback。注意各标签 base rate 应**递减**(6%/20宽松→10%/10最严)。

- [ ] **Step 6: 提交**(仅 .py;panel/报告 gitignore)：
```bash
git add data/profit_mining/setup_modeling.py
git commit -m "feat(model): setup_modeling 重构标签矩阵(4前向标签)+去y_zz+报告v2

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: 全量跑 + 归档 + 结论

**Files:** 无代码改动。

- [ ] **Step 1: 删冒烟面板 + 后台全量跑(宿主持有会话,NPROC=10)**:
```bash
docker exec agentsstock1 sh -c 'rm -f /app/data/profit_mining/setup_panel.npz'
docker exec agentsstock1 sh -c 'cd /app/data/profit_mining && NPROC=10 python3 setup_modeling.py > /app/data/profit_mining/_model_v2_run.log 2>&1'
```
(run_in_background;勿用-d。构面板~5min+8训练~30-40min,共~40min。等完成通知。)

- [ ] **Step 2: 归档 report/**:
```bash
TS=$(date +%Y%m%d_%H%M%S); DEST=/home/tdxback/report/起涨打分模型v2_$TS; mkdir -p "$DEST"
cp /home/tdxback/aiagents-stock/data/profit_mining/_model_v2_run.log "$DEST"/
cp /home/tdxback/aiagents-stock/data/commonality_reports/起涨打分模型v2_评估_*.md "$DEST"/ 2>/dev/null
ls "$DEST"
```

- [ ] **Step 3: 读结论报告用户** — 读 `起涨打分模型v2_评估_*.md`:4 标签各自 base rate / OOS AUC(logistic,GBDT) / lift@10%。重点:**收紧目标(更高涨幅/更短窗口/超额)后 base 是否下降、AUC/lift 是否放大** vs 基准 fwd_6_20(AUC0.63/lift1.31)。哪组标签最有 edge;哪些因子在收紧标签下权重上升。

- [ ] **Step 4: 登记 DATA_FILES + 提交** — DATA_FILES.md 报告产物段把 setup_modeling 行更新为"v2 多标签(setup_panel.npz 现存 Y[n,4]标签矩阵)";提交。

---

## Self-Review

**1. Spec coverage:**
- 4标签(fwd_6_20/fwd_10_10/fwd_10_20/excess_10_20) → Task2 LABELS ✓
- label_excess close-to-close超额,大盘=上证,末尾/缺失NaN → Task1 ✓
- 特征不变 → 未碰 compute_features ✓
- panel存标签矩阵Y[n,4]+names → Task2 build_panel ✓
- main逐标签×两模型,去y_zz → Task2 main(循环LABELS,无yz) ✓
- 切分/预处理/模型/评估复用 → _run_one未改 ✓
- 旧v1 panel结构变需重建 → Task2 Step5 + Task3 Step1 删panel ✓
- 报告v2+归档 → Task2/3 ✓
- 不动其他脚本 → 只改 setup_features/setup_modeling ✓
- label_excess合成单测 → Task1 test_label_excess ✓

**2. Placeholder scan:** 无TBD;每处给确切old→new整块替换+命令。

**3. Type consistency:** _panel_proc 返回 (X[float32], Y[n,4 float32], dates);build_panel np.vstack(Ys)→Y[N,4],存 X/Y/dates/cols/label_names;main d["X"]/d["Y"],循环 Y[:,j] 传 _run_one(label_name,X,y,dates,lines)(签名不变);LABELS 顺序=Y列序=names序一致;label_excess 签名 (df,idx_close,H,X) 与 _panel_proc 调用 SF.label_excess(df,_IDX["close"],**kw) 一致;label_fwd(df,**kw) kw=dict(H,X) 一致。