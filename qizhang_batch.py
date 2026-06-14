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


# ── run_daily 重活编排（重依赖只在函数内 import，不在模块顶层）──
import os
import sys
import time
import logging

PROFIT_DIR = "/app/data/profit_mining"

logger = logging.getLogger(__name__)


def _today_str():
    return time.strftime("%Y-%m-%d")


def run_daily(db, limit=0):
    """每日批：重建 panel → 训练 GBDT(扩展窗) → 今日 top-N → 落库 → realized 回填。

    db: QizhangPicksDatabase。limit>0 仅用于 smoke(限票池)。重依赖在此函数内 import。
    """
    if PROFIT_DIR not in sys.path:
        sys.path.insert(0, PROFIT_DIR)
    import setup_modeling as SM
    import setup_backtest as BT
    from mine_commonality import _load_kline

    scan_date = _today_str()
    try:
        # 1. 重建全市场 panel(最新本地K线)
        SM.build_panel(limit=limit)
        d = np.load(SM.PANEL, allow_pickle=True)
        X = d["X"]; Y = d["Y"]; dates = d["dates"].astype("datetime64[D]")
        codes = d["codes"]; label_names = d["label_names"]

        # 2. 训练 GBDT：全部有效标签行(扩展窗)
        j = label_index(label_names, LABEL)
        y = Y[:, j].astype(float)
        valid = ~np.isnan(y)
        med = SM.col_median(X[valid])
        Xtr = SM.fill_na(X[valid], med); ytr = y[valid]
        Xsub, ysub = SM._subsample_train(Xtr, ytr, ratio=5)
        bst = SM.fit_gbdt(Xsub, ysub)
        train_end = str(dates[valid].max())

        # 3. 给今日 bar 打分
        today_m = latest_date_mask(dates)
        Xtoday = SM.fill_na(X[today_m], med)
        sc = bst.predict(Xtoday)
        today_codes = codes[today_m]
        latest_date = dates.max()

        # 4. C4 大盘择时 gate
        riskoff_set = BT._riskoff_days()
        gate = is_riskoff(latest_date, riskoff_set)

        # 5. 候选落库（riskoff 日不产候选）
        if gate:
            db.save_daily_picks(scan_date, [], riskoff=True)
            logger.info("[起涨] %s risk-off(上证<MA20),今日不开新仓", scan_date)
        else:
            picks = build_ranked_picks(today_codes, sc, topn=TOPN)
            for p in picks:
                p["name"] = ""  # 名称非必需,留空(前台可后补);避免额外依赖
                df = _load_kline(p["code"])
                p["entry_ref_price"] = (float(df["Close"].iloc[-1])
                                        if df is not None and len(df) else None)
            db.save_daily_picks(scan_date, picks, riskoff=False)
            logger.info("[起涨] %s 产候选 %d 只", scan_date, len(picks))

        # 6. realized 回填到期候选
        new_real = []
        idx_close = SM._load_index_close()
        for sd, code in db.get_unrealized_picks():
            df = _load_kline(code)
            if df is None:
                continue
            r = compute_realized(df, sd, idx_close, BT.simulate_trade)
            if r is not None:
                r.update(scan_date=sd, code=code)
                new_real.append(r)
        db.save_realized(new_real)
        logger.info("[起涨] realized 回填 %d 条", len(new_real))

        db.save_run_meta(scan_date, model_train_rows=int(valid.sum()),
                         train_end_date=train_end, sh_ma20_gate=gate, status="ok")
        return True
    except Exception:
        logger.exception("[起涨] 日批失败")
        db.save_run_meta(scan_date, model_train_rows=0, train_end_date="",
                         sh_ma20_gate=False, status="failed")
        return False


def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    from qizhang_picks_db import QizhangPicksDatabase
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    db = QizhangPicksDatabase()
    ok = run_daily(db, limit=limit)
    print("[起涨日批] 完成" if ok else "[起涨日批] 失败", flush=True)


if __name__ == "__main__":
    main()
