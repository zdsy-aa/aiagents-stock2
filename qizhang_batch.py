# qizhang_batch.py
"""起涨预测 paper-tracking 日批：纯 helper(numpy/pandas) + run_daily(重活)。

纯 helper 段不 import lightgbm / setup_modeling / _load_kline,可在 host 单测。
run_daily 段把重依赖关进函数内部,仅由 sidecar(容器,主镜像)调用。
"""
import numpy as np
import pandas as pd

TOPN = 10
MAXHOLD = 30      # C4: trailing maxhold
TRAIL = 0.08      # C4: 8% 回撤移动止盈
SL = -0.05        # C4: 硬止损
COST = 0.002
LABEL = "fwd_10_10"


def label_index(label_names, label=LABEL):
    """panel label_names 数组中目标标签的列下标。"""
    return list(label_names).index(label)


def latest_date_mask(dates):
    """dates(datetime64[D]) -> 最新日期的布尔掩码。"""
    dates = np.asarray(dates, dtype="datetime64[D]")
    return dates == dates.max()


def build_ranked_picks(codes, scores, topn=TOPN):
    """按分降序取前 topn -> list[dict(code,score,rank)]。"""
    order = np.argsort(np.asarray(scores, float))[::-1][:topn]
    return [{"code": codes[j], "score": float(scores[j]), "rank": i + 1}
            for i, j in enumerate(order)]


def is_riskoff(date, riskoff_set):
    """该交易日上证是否 risk-off(<MA20)。date/riskoff_set 元素均 datetime64[D]。"""
    return np.datetime64(date, "D") in riskoff_set


def compute_realized(df, scan_date, idx_close, simulate_fn, maxhold=MAXHOLD,
                     trail=TRAIL, sl=SL, cost=COST):
    """对某候选(scan_date 当日的 code 的 kline df)算 C4(移动止盈)退出结果。

    入场=scan_date 次一根开盘;未到期(不足完整 maxhold 窗)或 scan_date 不在 df → None。
    返回 dict(exit_date, holding_days, realized_return, hit_10pct, exit_reason, bench_return)。
    """
    ts = pd.Timestamp(scan_date)
    if ts not in df.index:
        return None
    scan_idx = df.index.get_loc(ts)
    entry_idx = scan_idx + 1
    if entry_idx >= len(df):              # 入场行不存在 → 未到期
        return None
    o = df["Open"].to_numpy(float); h = df["High"].to_numpy(float)
    lo = df["Low"].to_numpy(float); c = df["Close"].to_numpy(float)
    res = simulate_fn(o, h, lo, c, entry_idx, mode="trailing",
                      maxhold=maxhold, trail=trail, sl=sl, cost=cost)
    if res is None:
        return None
    exit_idx, gross, net, reason = res
    if reason == "到期" and entry_idx + maxhold > len(df):
        # simulate_fn 因数据末尾被截断才给出"到期",并非真正持满 maxhold → 未到期
        return None
    entry = o[entry_idx]
    hit_10pct = bool(h[entry_idx:exit_idx + 1].max() >= entry * 1.10)
    entry_date = df.index[entry_idx]; exit_date = df.index[exit_idx]
    bench_return = None
    if idx_close is not None and entry_date in idx_close.index and exit_date in idx_close.index:
        bench_return = float(idx_close.loc[exit_date] / idx_close.loc[entry_date] - 1.0)
    return {"exit_date": exit_date.strftime("%Y-%m-%d"),
            "holding_days": int(exit_idx - entry_idx + 1),
            "realized_return": float(net), "hit_10pct": hit_10pct,
            "exit_reason": reason, "bench_return": bench_return}
