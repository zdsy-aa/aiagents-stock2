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
