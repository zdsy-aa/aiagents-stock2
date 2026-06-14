# setup_modeling.py —— 起涨预测打分模型: 面板拼装 + numpy logistic + lightgbm GBDT + OOS评估。
import os, sys, time
import numpy as np


# ---------- 评估 ----------
def _avg_rank(s):
    order = np.argsort(s, kind="mergesort")
    r = np.empty(len(s), float); r[order] = np.arange(1, len(s) + 1)
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


import pandas as pd
import setup_features as SF
from mine_commonality import _load_kline, _universe

PANEL = "/app/data/profit_mining/setup_panel.npz"
IDXCSV = "/app/data/profit_mining/index_sh000001.csv"
TURNCSV = "/app/data/profit_mining/turnover.csv"
TRAIN_END, OOS_START, OOS_END = "2023-12-31", "2024-01-01", "2025-10-31"
LABELS = [
    ("fwd_6_20",     "fwd",    dict(H=20, X=0.06)),
    ("fwd_10_10",    "fwd",    dict(H=10, X=0.10)),
    ("fwd_10_20",    "fwd",    dict(H=20, X=0.10)),
    ("excess_10_20", "excess", dict(H=20, X=0.10)),
]
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
        ys = []
        for name, kind, kw in LABELS:
            if kind == "fwd":
                ys.append(SF.label_fwd(df, **kw))
            else:
                ys.append(SF.label_excess(df, _IDX["close"], **kw))
        Y = np.column_stack(ys)
        dates = df.index.to_numpy().astype("datetime64[D]")
        codes = np.full(len(dates), code, dtype=object)
        return X.astype(np.float32), Y.astype(np.float32), dates, codes
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
    Xtr_s, mu, sd = standardize_fit(Xtr)
    Xsub, ysub = _subsample_train(Xtr_s, ytr, ratio=5)
    w, b = fit_logistic(Xsub, ysub, l2=1.0, lr=0.3, epochs=400)
    sc = predict_logistic(standardize_apply(Xoos, mu, sd), w, b)
    lines.append(f"- **logistic**: OOS AUC={auc(yoos, sc):.4f}  lift@10%={lift_top_decile(yoos, sc):.2f}")
    top = sorted(zip(SF.FEATURE_COLS, w), key=lambda x: -abs(x[1]))[:8]
    lines.append("  - 权重Top8: " + ", ".join(f"{k}={v:+.2f}" for k, v in top))
    try:
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


if __name__ == "__main__":
    main()
