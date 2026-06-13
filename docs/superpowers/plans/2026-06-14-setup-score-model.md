# 起涨预测多因子打分模型(setup_modeling) 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 逐bar用~25连续特征预测起涨,两标签(y_fwd/y_zz)×两模型(numpy logistic/lightgbm GBDT)时间切分OOS,看弱信号组合后是否有 AUC/top-decile lift 的 edge。

**Architecture:** `setup_features.py`(逐股连续特征+两标签,纯计算,可单测)+ `setup_modeling.py`(面板拼装多进程/time_split/numpy logistic/lightgbm GBDT/AUC+lift评估/main+报告)。复用 features.py 算子、turnover_features.chip_series、swing_samples(zz6)、mine_commonality._load_kline/_universe。不动现有挖掘脚本。

**Tech Stack:** Python3+numpy+pandas(+lightgbm容器装)。容器 agentsstock1。测试合成序列 `python3 test_*.py`。

参考 spec：`docs/superpowers/specs/2026-06-13-setup-score-model-design.md`

确认事实(无需重查)：
- `features` 算子:`MA(x,n)/EMA(x,n)/STD(x,n)/HHV(x,n)/LLV(x,n)/TR(df)`(rolling,min_periods内置);`relative_strength(stock_close,index_close)`→DataFrame含连续列`相对强弱`。
- `turnover_features.chip_series(df, turn)`→DataFrame含`获利盘/套牢盘`(前60 bar NaN);turn=date-indexed Series。
- `swing_samples.Z.zigzag_pivots(high_list,low_list,pct)` + `Z.segments_from_pivots(pivots)`→[(start=L,end=H,"up"/"down")]。
- `mine_commonality._load_kline(code)`→datetime-indexed OHLCV df 或None;`_universe()`→codes list。
- 指数:`/app/data/profit_mining/index_sh000001.csv`(列 日期/Open/High/Low/Close/...),`pd.read_csv`后`日期`→datetime设索引。
- 容器 pip 24 可用;无 sklearn/scipy。

---

### Task 1: setup_features.py — 逐股连续特征 + 两标签

**Files:** Create `data/profit_mining/setup_features.py` + `data/profit_mining/test_setup_features.py`

- [ ] **Step 1: 写失败测试** — `data/profit_mining/test_setup_features.py`：
```python
import numpy as np, pandas as pd
import setup_features as SF

def _df(close, vol=None, n=None):
    n = n or len(close)
    idx = pd.date_range("2015-01-01", periods=n, freq="D")
    c = pd.Series(close[:n], dtype=float, index=idx)
    return pd.DataFrame({"Open": c, "High": c*1.01, "Low": c*0.99, "Close": c,
                         "Volume": pd.Series((vol or [100.0]*n)[:n], index=idx)}, index=idx)

def test_feature_cols_count():
    assert 20 <= len(SF.FEATURE_COLS) <= 28, len(SF.FEATURE_COLS)

def test_no_future_leak():
    # 改未来bar不应改变过去bar的特征值
    base = [10.0 + 0.01*i for i in range(300)]
    d1 = _df(base)
    d2v = list(base); d2v[250] = 999.0          # 篡改 t=250
    d2 = _df(d2v)
    f1 = SF.compute_features(d1, idx_close=None, turn=None)
    f2 = SF.compute_features(d2, idx_close=None, turn=None)
    # t=200 处所有特征应不受 t=250 改动影响
    assert np.allclose(np.nan_to_num(f1[200]), np.nan_to_num(f2[200])), (f1[200], f2[200])

def test_label_fwd():
    # 后H内涨>=X -> 1。构造 t0 后 5 天涨 10%
    close = [10.0]*10 + [11.0]*10 + [10.0]*30
    d = _df(close)
    y = SF.label_fwd(d, H=20, X=0.06)
    assert y[5] == 1                  # t=5 后20日内有11(涨10%>=6%)
    assert y[40] == 0 or np.isnan(y[40])  # 末尾平盘
    # 末尾不足H的bar应为 NaN(丢弃)
    assert np.isnan(y[len(close)-1])

def test_label_zz():
    # 明显上涨段: 前低位后翻倍 -> 波谷前K根=1
    close = [10.0]*40 + [10.0+0.5*i for i in range(40)] + [30.0]*20
    d = _df(close)
    y = SF.label_zz(d, pct=0.06, K=10)
    # 应至少有一些1(起涨前K根); 且全在上涨段波谷之前
    assert y.sum() >= 1, y.sum()
    assert set(np.unique(y[~np.isnan(y)])) <= {0.0, 1.0}

if __name__ == "__main__":
    test_feature_cols_count(); test_no_future_leak()
    test_label_fwd(); test_label_zz()
    print("ALL setup_features OK")
```

- [ ] **Step 2: 跑测试确认失败** — `cd data/profit_mining && python3 test_setup_features.py` → `ModuleNotFoundError: No module named 'setup_features'`。

- [ ] **Step 3: 实现** — `data/profit_mining/setup_features.py`：
```python
# setup_features.py —— 起涨预测的逐bar连续特征 + 两标签(y_fwd/y_zz)。纯计算,特征只用<=t。
import numpy as np
import pandas as pd

import features as F
import swing_samples as SW
from turnover_features import chip_series

FEATURE_COLS = [
    "vol_std20_pct", "vbar20", "vbar60", "box20", "box60", "profit", "trapped",
    "macd_bar", "macd_bar_slope", "rsi14", "kdj_k",
    "dist_ma5", "dist_ma20", "dist_ma60", "rel_strength", "atr_pct",
    "ret20", "ret60", "pos_year_hi", "pos_year_lo", "turn",
]


def _rsi(c, n=14):
    d = c.diff()
    up = d.clip(lower=0).rolling(n, min_periods=n).mean()
    dn = (-d.clip(upper=0)).rolling(n, min_periods=n).mean()
    return 100 - 100 / (1 + up / (dn + 1e-9))


def _kdj_k(df, n=9):
    low_n = F.LLV(df["Low"], n); high_n = F.HHV(df["High"], n)
    rsv = (df["Close"] - low_n) / (high_n - low_n + 1e-9) * 100
    return rsv.ewm(com=2, adjust=False).mean()   # K = SMA(rsv,3,1) 近似


def compute_features(df, idx_close=None, turn=None):
    """df(OHLCV,datetime索引) -> numpy 二维 [n, len(FEATURE_COLS)] (float, 含NaN)。
    idx_close=对齐到df.index的大盘收盘Series(无则相对强弱填NaN); turn=换手率Series(无则chip/turn填NaN)。"""
    c, h, l, v = df["Close"], df["High"], df["Low"], df["Volume"]
    ret = c.pct_change()
    std20 = F.STD(ret, 20)
    cols = {}
    cols["vol_std20_pct"] = std20.rolling(120, min_periods=40).rank(pct=True)
    cols["vbar20"] = v / (F.MA(v, 20) + 1e-9)
    cols["vbar60"] = v / (F.MA(v, 60) + 1e-9)
    cols["box20"] = (F.HHV(c, 20) - F.LLV(c, 20)) / (F.LLV(c, 20) + 1e-9)
    cols["box60"] = (F.HHV(c, 60) - F.LLV(c, 60)) / (F.LLV(c, 60) + 1e-9)
    if turn is not None:
        try:
            ch = chip_series(df, turn)
            cols["profit"] = ch["获利盘"]; cols["trapped"] = ch["套牢盘"]
        except Exception:
            cols["profit"] = pd.Series(np.nan, index=df.index); cols["trapped"] = cols["profit"]
        cols["turn"] = turn.reindex(df.index)
    else:
        cols["profit"] = pd.Series(np.nan, index=df.index)
        cols["trapped"] = pd.Series(np.nan, index=df.index)
        cols["turn"] = pd.Series(np.nan, index=df.index)
    dif = F.EMA(c, 12) - F.EMA(c, 26); dea = F.EMA(dif, 9); bar = dif - dea
    cols["macd_bar"] = bar / (c + 1e-9)
    cols["macd_bar_slope"] = (bar - bar.shift(1)) / (c + 1e-9)
    cols["rsi14"] = _rsi(c, 14)
    cols["kdj_k"] = _kdj_k(df, 9)
    cols["dist_ma5"] = (c - F.MA(c, 5)) / (F.MA(c, 5) + 1e-9)
    cols["dist_ma20"] = (c - F.MA(c, 20)) / (F.MA(c, 20) + 1e-9)
    cols["dist_ma60"] = (c - F.MA(c, 60)) / (F.MA(c, 60) + 1e-9)
    if idx_close is not None:
        cols["rel_strength"] = F.relative_strength(c, idx_close.reindex(df.index).ffill())["相对强弱"]
    else:
        cols["rel_strength"] = pd.Series(np.nan, index=df.index)
    atr = F.TR(df).rolling(14, min_periods=14).mean()
    cols["atr_pct"] = atr / (c + 1e-9)
    cols["ret20"] = c / (c.shift(20) + 1e-9) - 1
    cols["ret60"] = c / (c.shift(60) + 1e-9) - 1
    cols["pos_year_hi"] = (c - F.HHV(c, 250)) / (F.HHV(c, 250) + 1e-9)
    cols["pos_year_lo"] = (c - F.LLV(c, 250)) / (F.LLV(c, 250) + 1e-9)
    M = np.column_stack([cols[k].to_numpy(float) for k in FEATURE_COLS])
    return M


def label_fwd(df, H=20, X=0.06):
    """后H交易日内最大High/当前Close-1>=X ->1; 末尾不足H根 ->NaN。返回 float numpy(0/1/NaN)。"""
    c = df["Close"].to_numpy(float); h = df["High"].to_numpy(float)
    n = len(c); y = np.full(n, np.nan)
    for t in range(n):
        if t + H >= n:
            break
        fwd_max = h[t + 1:t + 1 + H].max()
        y[t] = 1.0 if (fwd_max / c[t] - 1.0) >= X else 0.0
    return y


def label_zz(df, pct=0.06, K=10):
    """t∈某zz6上涨段波谷L的[L-K,L] ->1; 其余0。返回 float numpy(0/1)。
    注:y_zz 用ZigZag(含未来确认)定义,仅作对照标签。"""
    piv = SW.Z.zigzag_pivots(df["High"].tolist(), df["Low"].tolist(), pct)
    wins = SW.presetup_windows_from_pivots(piv, tight_k=K)   # [L-K, L]
    n = len(df); y = np.zeros(n)
    for w in wins:
        for i in w:
            if 0 <= i < n:
                y[i] = 1.0
    return y
```

- [ ] **Step 4: 跑测试确认通过** — `cd data/profit_mining && python3 test_setup_features.py` → `ALL setup_features OK`。删 `__pycache__`。

- [ ] **Step 5: 提交**：
```bash
git add data/profit_mining/setup_features.py data/profit_mining/test_setup_features.py
git commit -m "feat(model): setup_features 逐bar连续特征(~21)+两标签(y_fwd/y_zz)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: setup_modeling.py — logistic + 评估 + 切分 + 预处理

**Files:** Create `data/profit_mining/setup_modeling.py` + `data/profit_mining/test_setup_modeling.py`

- [ ] **Step 1: 写失败测试** — `data/profit_mining/test_setup_modeling.py`：
```python
import numpy as np
import setup_modeling as SM

def test_auc_known():
    y = np.array([0,0,1,1]); s = np.array([0.1,0.2,0.3,0.4])
    assert abs(SM.auc(y, s) - 1.0) < 1e-9
    assert abs(SM.auc(y, -s) - 0.0) < 1e-9
    assert abs(SM.auc(np.array([0,1,0,1]), np.array([1,1,2,2])) - 0.5) < 1e-9  # 完全并列对半

def test_lift_top_decile():
    y = np.array([0]*90 + [1]*10); s = np.arange(100.0)  # 分越高越靠后; 高分10个=后10个=全1
    assert abs(SM.lift_top_decile(y, s, q=0.1) - (1.0/0.1)) < 1e-6   # top率1.0 / 基线0.1 =10

def test_logistic_separable():
    rng = np.random.default_rng(0)
    X = np.vstack([rng.normal(-2,1,(200,3)), rng.normal(2,1,(200,3))])
    y = np.array([0]*200 + [1]*200)
    Xs, mu, sd = SM.standardize_fit(X)
    w, b = SM.fit_logistic(Xs, y, l2=0.1, lr=0.5, epochs=400)
    sc = SM.predict_logistic(SM.standardize_apply(X, mu, sd), w, b)
    assert SM.auc(y, sc) > 0.97, SM.auc(y, sc)

def test_median_fill_uses_train_only():
    Xtr = np.array([[1.0],[3.0],[np.nan]]); Xoos = np.array([[np.nan]])
    med, = (SM.col_median(Xtr),)
    Xtr2 = SM.fill_na(Xtr, med); Xoos2 = SM.fill_na(Xoos, med)
    assert Xtr2[2,0] == 2.0 and Xoos2[0,0] == 2.0   # 用训练中位数2填

def test_time_split():
    import numpy as np
    dates = np.array(["2023-06-01","2023-12-31","2024-01-01","2025-09-01"], dtype="datetime64[D]")
    tr, oos = SM.time_split_mask(dates, "2023-12-31", "2024-01-01", "2025-10-31")
    assert tr.tolist() == [True,True,False,False]
    assert oos.tolist() == [False,False,True,True]

if __name__ == "__main__":
    test_auc_known(); test_lift_top_decile(); test_logistic_separable()
    test_median_fill_uses_train_only(); test_time_split()
    print("ALL setup_modeling OK")
```

- [ ] **Step 2: 跑测试确认失败** — `cd data/profit_mining && python3 test_setup_modeling.py` → `ModuleNotFoundError`。

- [ ] **Step 3: 实现(本任务先到工具函数,build_panel/main 在 Task3)** — `data/profit_mining/setup_modeling.py`：
```python
# setup_modeling.py —— 起涨预测打分模型: 面板拼装 + numpy logistic + lightgbm GBDT + OOS评估。
import os, sys, time
import numpy as np


# ---------- 评估 ----------
def _avg_rank(s):
    order = np.argsort(s, kind="mergesort")
    r = np.empty(len(s), float); r[order] = np.arange(1, len(s) + 1)
    # 处理并列: 同值取平均秩
    s_sorted = s[order]
    i = 0
    while i < len(s):
        j = i
        while j + 1 < len(s) and s_sorted[j + 1] == s_sorted[i]:
            j += 1
        if j > i:
            avg = (r[order[i]] + r[order[j]]) / 2.0
            for k in range(i, j + 1):
                r[order[k]] = avg
        i = j + 1
    return r


def auc(y, score):
    y = np.asarray(y, float); score = np.asarray(score, float)
    npos = y.sum(); nneg = len(y) - npos
    if npos == 0 or nneg == 0:
        return 0.5
    r = _avg_rank(score)
    return (r[y == 1].sum() - npos * (npos + 1) / 2) / (npos * nneg)


def lift_top_decile(y, score, q=0.1):
    y = np.asarray(y, float); score = np.asarray(score, float)
    k = max(1, int(len(score) * q))
    idx = np.argsort(score)[::-1][:k]
    base = y.mean()
    return float(y[idx].mean() / base) if base > 0 else float("nan")


# ---------- 预处理 ----------
def col_median(X):
    return np.nanmedian(X, axis=0)


def fill_na(X, med):
    X = X.copy()
    inds = np.where(np.isnan(X))
    X[inds] = np.take(med, inds[1])
    return X


def standardize_fit(X):
    mu = X.mean(axis=0); sd = X.std(axis=0); sd[sd == 0] = 1.0
    return (X - mu) / sd, mu, sd


def standardize_apply(X, mu, sd):
    return (X - mu) / sd


def time_split_mask(dates, train_end, oos_start, oos_end):
    d = np.asarray(dates, dtype="datetime64[D]")
    tr = d <= np.datetime64(train_end)
    oos = (d >= np.datetime64(oos_start)) & (d <= np.datetime64(oos_end))
    return tr, oos


# ---------- numpy logistic ----------
def fit_logistic(X, y, l2=1.0, lr=0.1, epochs=300, class_weight=True, seed=0):
    n, dft = X.shape
    w = np.zeros(dft); b = 0.0
    if class_weight:
        pos = max(y.mean(), 1e-6)
        sw = np.where(y == 1, 0.5 / pos, 0.5 / max(1 - pos, 1e-6))
        sw = sw / sw.mean()
    else:
        sw = np.ones(n)
    for _ in range(epochs):
        p = 1.0 / (1.0 + np.exp(-(X @ w + b)))
        g = (p - y) * sw
        w -= lr * (X.T @ g / n + l2 * w / n)
        b -= lr * g.mean()
    return w, b


def predict_logistic(X, w, b):
    return 1.0 / (1.0 + np.exp(-(X @ w + b)))
```

- [ ] **Step 4: 跑测试确认通过** — `cd data/profit_mining && python3 test_setup_modeling.py` → `ALL setup_modeling OK`。删 `__pycache__`。

- [ ] **Step 5: 提交**：
```bash
git add data/profit_mining/setup_modeling.py data/profit_mining/test_setup_modeling.py
git commit -m "feat(model): setup_modeling 工具(auc/lift/标准化/中位填充/time_split/numpy logistic)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: 面板拼装 + GBDT + main + 报告 + lightgbm 安装

**Files:** Modify `data/profit_mining/setup_modeling.py`(追加 build_panel/fit_gbdt/_eval_report/main);容器装 lightgbm;改 `requirements.txt`。

- [ ] **Step 1: 容器安装 lightgbm + 入 requirements**：
```bash
docker exec agentsstock1 sh -c 'pip install --quiet lightgbm 2>&1 | tail -3; python3 -c "import lightgbm; print(\"lightgbm\", lightgbm.__version__)"'
```
Expected: 打印 `lightgbm <版本>`。若安装失败(网络),记录,后续 main 会自动降级 logistic-only。
然后在宿主 `requirements.txt` 末尾加一行 `lightgbm`(若安装成功)：编辑 `requirements.txt` 追加 `lightgbm`。

- [ ] **Step 2: 追加 build_panel/fit_gbdt/_eval_report/main 到 setup_modeling.py**：
```python
import pandas as pd
import setup_features as SF
from mine_commonality import _load_kline, _universe

PANEL = "/app/data/profit_mining/setup_panel.npz"
IDXCSV = "/app/data/profit_mining/index_sh000001.csv"
TURNCSV = "/app/data/profit_mining/turnover.csv"
TRAIN_END, OOS_START, OOS_END = "2023-12-31", "2024-01-01", "2025-10-31"
_IDX = {"close": None}
_TURN = {}


def _load_index_close():
    df = pd.read_csv(IDXCSV, encoding="utf-8-sig"); df["日期"] = pd.to_datetime(df["日期"])
    return df.set_index("日期").sort_index()["Close"]


def _load_turn_by_code():
    if not os.path.exists(TURNCSV):
        return
    df = pd.read_csv(TURNCSV, dtype={"code": str}); df["date"] = pd.to_datetime(df["date"])
    for code, g in df.groupby("code", sort=False):
        _TURN[code] = pd.Series(g["turn"].to_numpy(float), index=pd.DatetimeIndex(g["date"].to_numpy()))


def _panel_proc(code):
    try:
        df = _load_kline(code)
        if df is None or len(df) < 300:
            return None
        X = SF.compute_features(df, idx_close=_IDX["close"], turn=_TURN.get(code))
        yf = SF.label_fwd(df); yz = SF.label_zz(df)
        dates = df.index.to_numpy().astype("datetime64[D]")
        return X.astype(np.float32), yf.astype(np.float32), yz.astype(np.float32), dates
    except Exception:
        return None


def build_panel(limit=0):
    from multiprocessing import Pool
    _IDX["close"] = _load_index_close()
    _load_turn_by_code()
    codes = _universe()
    if limit:
        codes = codes[:limit]
    nproc = int(os.getenv("NPROC", "8"))
    Xs, yfs, yzs, dts = [], [], [], []
    with Pool(nproc) as p:
        for r in p.imap_unordered(_panel_proc, codes, chunksize=8):
            if r is None:
                continue
            X, yf, yz, dates = r
            Xs.append(X); yfs.append(yf); yzs.append(yz); dts.append(dates)
    X = np.vstack(Xs); yf = np.concatenate(yfs); yz = np.concatenate(yzs)
    dates = np.concatenate(dts).astype("datetime64[D]")
    np.savez(PANEL, X=X, yf=yf, yz=yz, dates=dates.astype("int64"), cols=np.array(SF.FEATURE_COLS))
    return X, yf, yz, dates


def fit_gbdt(X, y, scale_pos_weight=1.0):
    import lightgbm as lgb
    ds = lgb.Dataset(X, label=y)
    params = dict(objective="binary", metric="auc", learning_rate=0.05,
                  num_leaves=31, min_data_in_leaf=200, feature_fraction=0.8,
                  bagging_fraction=0.8, bagging_freq=1, scale_pos_weight=scale_pos_weight,
                  verbose=-1)
    return lgb.train(params, ds, num_boost_round=200)


def _subsample_train(Xtr, ytr, ratio=5, seed=0):
    rng = np.random.default_rng(seed)
    pos = np.where(ytr == 1)[0]; neg = np.where(ytr == 0)[0]
    keepn = min(len(neg), len(pos) * ratio) if len(pos) else len(neg)
    negk = rng.choice(neg, size=keepn, replace=False) if keepn < len(neg) else neg
    idx = np.concatenate([pos, negk]); rng.shuffle(idx)
    return Xtr[idx], ytr[idx]


def _run_one(label_name, X, y, dates, lines):
    tr, oos = time_split_mask(dates, TRAIN_END, OOS_START, OOS_END)
    valid = ~np.isnan(y)
    trm = tr & valid; oosm = oos & valid
    Xtr_raw, ytr = X[trm], y[trm]; Xoos_raw, yoos = X[oosm], y[oosm]
    med = col_median(Xtr_raw)
    Xtr = fill_na(Xtr_raw, med); Xoos = fill_na(Xoos_raw, med)
    base = yoos.mean()
    lines.append(f"### 标签 {label_name}  (训练 {len(ytr)} 行/正{int(ytr.sum())}, OOS {len(yoos)} 行/基线{base:.4f})")
    # logistic
    Xtr_s, mu, sd = standardize_fit(Xtr)
    Xsub, ysub = _subsample_train(Xtr_s, ytr, ratio=5)
    w, b = fit_logistic(Xsub, ysub, l2=1.0, lr=0.3, epochs=400)
    sc = predict_logistic(standardize_apply(Xoos, mu, sd), w, b)
    lines.append(f"- **logistic**: OOS AUC={auc(yoos, sc):.4f}  lift@10%={lift_top_decile(yoos, sc):.2f}")
    top = sorted(zip(SF.FEATURE_COLS, w), key=lambda x: -abs(x[1]))[:8]
    lines.append("  - 权重Top8: " + ", ".join(f"{k}={v:+.2f}" for k, v in top))
    # gbdt
    try:
        spw = (len(ytr) - ytr.sum()) / max(ytr.sum(), 1)
        Xsub2, ysub2 = _subsample_train(Xtr, ytr, ratio=5)
        bst = fit_gbdt(Xsub2, ysub2, scale_pos_weight=1.0)
        scg = bst.predict(Xoos)
        imp = sorted(zip(SF.FEATURE_COLS, bst.feature_importance()), key=lambda x: -x[1])[:8]
        lines.append(f"- **GBDT**: OOS AUC={auc(yoos, scg):.4f}  lift@10%={lift_top_decile(yoos, scg):.2f}")
        lines.append("  - importance Top8: " + ", ".join(f"{k}={int(v)}" for k, v in imp))
    except Exception as e:
        lines.append(f"- **GBDT**: 跳过(lightgbm不可用: {type(e).__name__})")


def main():
    t0 = time.time()
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    if os.path.exists(PANEL) and not limit:
        d = np.load(PANEL, allow_pickle=True)
        X, yf, yz = d["X"], d["yf"], d["yz"]; dates = d["dates"].astype("datetime64[D]")
        print(f"  载入面板 {X.shape}", flush=True)
    else:
        X, yf, yz, dates = build_panel(limit=limit)
        print(f"  构建面板 {X.shape} 用时{int(time.time()-t0)}s", flush=True)
    lines = [f"# 起涨打分模型 OOS 评估\n\n生成 {time.strftime('%Y%m%d_%H%M%S')}，"
             f"训练≤{TRAIN_END} / OOS {OOS_START}~{OOS_END}，特征{len(SF.FEATURE_COLS)}列，"
             f"AUC>0.55才算有edge，lift@10%=OOS前10%分bar实际起涨率÷基线\n"]
    _run_one("y_fwd(后20日涨≥6%)", X, yf, dates, lines)
    _run_one("y_zz(zz6波谷前10根)", X, yz, dates, lines)
    ts = time.strftime("%Y%m%d_%H%M%S")
    out = f"/app/data/commonality_reports/起涨打分模型_评估_{ts}.md"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print(f"[打分模型] 用时{int(time.time()-t0)}s 写 {out}", flush=True)
    print("\n".join(lines), flush=True)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: 语法检查** — `cd data/profit_mining && python3 -c "import ast; ast.parse(open('setup_modeling.py').read()); print('syntax OK')"` → `syntax OK`。

- [ ] **Step 4: 容器冒烟(limit=60, 端到端: 构面板+4训练+评估)**：
```bash
docker exec -w /app/data/profit_mining agentsstock1 sh -c 'NPROC=4 python3 setup_modeling.py 60'
```
Expected: 打印 `构建面板 (N, 21)`、两个标签段、每段 logistic + GBDT 的 `OOS AUC=.. lift@10%=..`(60股样本小,AUC仅冒烟看不崩)、`写 ...起涨打分模型_评估_*.md`。无 traceback。(GBDT 若 lightgbm 没装→打印"跳过",可接受,Step1 应已装上。)

- [ ] **Step 5: 提交**(仅 .py + requirements;panel/报告 gitignore)：
```bash
git add data/profit_mining/setup_modeling.py requirements.txt
git commit -m "feat(model): setup_modeling build_panel+GBDT+main+报告; requirements加lightgbm

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: 全量跑 + 归档 + 结论

**Files:** 无代码改动。

- [ ] **Step 1: 后台全量跑(宿主持有会话, NPROC=10, 全市场建面板+4训练)**:
```bash
docker exec agentsstock1 sh -c 'cd /app/data/profit_mining && NPROC=10 python3 setup_modeling.py > /app/data/profit_mining/_model_run.log 2>&1'
```
(run_in_background;勿用 -d。构面板~15-20min+turnover加载,内存峰值 float32面板~2GB+下采样训练。等完成通知。若 OOM,Step2 改 limit 或减特征——但先按全量试。)

- [ ] **Step 2: 归档 report/**:
```bash
TS=$(date +%Y%m%d_%H%M%S); DEST=/home/tdxback/report/起涨打分模型_$TS; mkdir -p "$DEST"
cp /home/tdxback/aiagents-stock/data/profit_mining/_model_run.log "$DEST"/
cp /home/tdxback/aiagents-stock/data/commonality_reports/起涨打分模型_评估_*.md "$DEST"/ 2>/dev/null
ls "$DEST"
```

- [ ] **Step 3: 读结论报告用户** — 读 `起涨打分模型_评估_*.md`:4 单元 OOS AUC(logistic/GBDT × y_fwd/y_zz)是否 >0.55、top-decile lift 是否 >1.x、哪些因子权重/重要性高;结论:**弱信号组合后是否产生 edge**(对照单点共性 lift≈1)。

- [ ] **Step 4: 登记 DATA_FILES + 提交** — 在 DATA_FILES.md 加 `setup_panel.npz`(setup_modeling.py 产物,可重建)+ 报告产物行,提交。

---

## Self-Review

**1. Spec coverage:**
- 两标签 y_fwd(H20X6%)/y_zz(K10) → Task1 label_fwd/label_zz ✓
- ~25连续特征(蓄势+动量+经典,≤t) → Task1 FEATURE_COLS(21列,在20-28区间)+compute_features ✓
- 防泄漏(特征≤t) → Task1 test_no_future_leak ✓
- 时间切分训练≤2023末/OOS2024-2025.10 → Task2 time_split_mask + Task3 常量 ✓
- 标准化/中位填充只用训练统计 → Task2 standardize_fit/col_median(在_run_one里只对Xtr算med/mu/sd) ✓
- float32+负样本下采样R5,OOS全量 → Task3 _panel_proc astype float32 + _subsample_train + _run_one(OOS不采样) ✓
- 类不均衡:logistic class_weight + (GBDT下采样后) → Task2 fit_logistic class_weight ✓
- 两模型logistic+GBDT,GBDT容错降级 → Task3 fit_gbdt + _run_one try/except ✓
- 评估AUC+lift@decile+权重/importance → Task2 auc/lift + Task3 _run_one输出 ✓
- lightgbm装+requirements → Task3 Step1 ✓
- 不动现有挖掘脚本 → 仅 import features/swing_samples/turnover_features/mine_commonality ✓
- 产物报告+归档 → Task3/4 ✓

**2. Placeholder scan:** 无 TBD;每步完整代码+确切命令。

**3. Type consistency:** compute_features 返回 [n,len(FEATURE_COLS)] 与 FEATURE_COLS 顺序一致(M 用 FEATURE_COLS 列序 column_stack);label_fwd/label_zz 返回 float numpy(0/1/NaN);build_panel 存 X/yf/yz/dates;_run_one 用 time_split_mask+col_median+fill_na+standardize+fit_logistic/predict_logistic+auc/lift_top_decile(均 Task2 定义,签名一致);fit_gbdt 返回 lgb booster,.predict/.feature_importance 调用一致。dates 存 int64 再转回 datetime64[D]。
