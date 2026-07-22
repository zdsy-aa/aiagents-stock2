# turnover_features.py —— 用 baostock 换手率重建筹码分布(WINNER近似)，补 换手率/尖刺/获利盘/套牢盘 信号，
#   与现有矩阵 join 后重挖，检验是否在 极限抄底+量比≥1.3 之上有增益。
# 运行: docker exec -w /app agentsstock1 python3 /app/data/profit_mining/turnover_features.py
import sys, time, os
sys.path.insert(0, "/app"); sys.path.insert(0, "/app/data/profit_mining")
from collections import defaultdict
import numpy as np
import pandas as pd

TURN = "/app/data/profit_mining/turnover.csv"
FEAT = "/app/data/profit_mining/signal_features.csv"
OUT = "/app/data/profit_mining/turnover_signal.csv"
_RENAME = {"开盘": "Open", "最高": "High", "最低": "Low", "收盘": "Close", "成交量": "Volume"}
NB = 240  # 价格网格


def _load(code):
    from akshare_gateway import akshare_gw
    df = akshare_gw.local.get_kline(code, kline_type="day", limit=10000)   # 全历史
    if df is None or df.empty:
        return None
    return df.rename(columns=_RENAME).set_index("日期").sort_index()[["Open", "High", "Low", "Close"]]


def chip_series(df, turn):
    """重建筹码分布,返回每日 获利盘/活跃筹码/套牢盘/爆破线/堡垒线 (百分比)。"""
    o, h, l, c = (df[x].to_numpy(float) for x in ("Open", "High", "Low", "Close"))
    tr = turn.reindex(df.index).fillna(0).to_numpy(float) / 100.0
    tr = np.clip(tr, 0, 0.5)
    lo, hi = l.min() * 0.95, h.max() * 1.05
    grid = np.linspace(lo, hi, NB)
    step = grid[1] - grid[0]
    chips = np.zeros(NB)
    n = len(c)
    out = np.full((n, 5), np.nan)

    def winner(price):
        return chips[grid <= price].sum() / (chips.sum() + 1e-12)

    for t in range(n):
        chips *= (1 - tr[t])
        a, b = l[t], h[t]
        m = (grid >= a) & (grid <= b)
        if b > a and m.any():
            # 三角分布：峰在均价 (low+high+2*close)/4，线性升降
            pk = (a + b + 2 * c[t]) / 4
            g = grid[m]
            w = np.where(g <= pk, (g - a) / (pk - a + 1e-9), (b - g) / (b - pk + 1e-9))
            w = np.clip(w, 0, None)
            sw = w.sum()
            chips[m] += tr[t] * (w / sw if sw > 0 else 1.0 / m.sum())
        else:
            chips[np.argmin(np.abs(grid - c[t]))] += tr[t]
        if t < 60:
            continue
        wc = winner(c[t])
        out[t, 0] = wc * 100                                   # 获利盘
        out[t, 1] = (winner(c[t]*1.075) - winner(c[t]*0.925)) * 100  # 活跃筹码
        out[t, 2] = (1 - wc) * 100                             # 套牢盘
        out[t, 3] = (wc - winner(o[t])) * 100                  # 爆破线
        out[t, 4] = (winner(c[t]*1.1) - wc) * 100              # 堡垒线
    return pd.DataFrame(out, index=df.index, columns=["获利盘", "活跃筹码", "套牢盘", "爆破线", "堡垒线"])


_TG = {}   # fork写时复用：sig_by_code, turn_by_code(大字典不pickle)


def _tf_proc(code):
    sig_by_code, turn_by_code = _TG["sig"], _TG["turn"]
    if code not in turn_by_code:
        return []
    df = _load(code)
    if df is None or len(df) < 70:
        return []
    turn = turn_by_code[code]
    ch = chip_series(df, turn)
    ts = turn.reindex(df.index)
    pos = {d.strftime("%Y-%m-%d"): i for i, d in enumerate(df.index)}
    rows = []
    for sd in sig_by_code[code]:
        if sd not in pos:
            continue
        i = pos[sd]
        hv = ts.iloc[i]
        getv = lambda col: ch[col].iloc[i]
        爆, 堡 = getv("爆破线"), getv("堡垒线")
        爆1 = ch["爆破线"].iloc[i - 1] if i > 0 else np.nan
        堡1 = ch["堡垒线"].iloc[i - 1] if i > 0 else np.nan
        rows.append({
            "股票代码": code, "信号日期": sd,
            "换手率1_3": 1 if (pd.notna(hv) and 1 <= hv <= 3) else 0,
            "换手率3_8": 1 if (pd.notna(hv) and 3 <= hv <= 8) else 0,
            "换手率8_15": 1 if (pd.notna(hv) and 8 <= hv <= 15) else 0,
            "筹码集中": 1 if (pd.notna(getv("获利盘")) and 50 < getv("获利盘") < 80) else 0,
            "深度套牢": 1 if (pd.notna(getv("套牢盘")) and getv("套牢盘") > 70) else 0,
            "获利盘高": 1 if (pd.notna(getv("获利盘")) and getv("获利盘") > 70) else 0,
            "尖刺金叉": 1 if (pd.notna(爆) and pd.notna(堡) and pd.notna(爆1) and 爆 > 堡 and 爆1 <= 堡1) else 0,
        })
    return rows


def main():
    feat = pd.read_csv(FEAT, encoding="utf-8-sig", dtype={"股票代码": str})
    feat["股票代码"] = feat["股票代码"].str.zfill(6)
    sig_by_code = defaultdict(list)
    for _, r in feat.iterrows():
        sig_by_code[r["股票代码"]].append(r["信号日期"])

    tdf = pd.read_csv(TURN, encoding="utf-8-sig", dtype={"code": str})
    tdf["code"] = tdf["code"].str.zfill(6)
    turn_by_code = {c: g.drop_duplicates("date").set_index("date")["turn"]
                    for c, g in tdf.groupby("code")}
    turn_by_code = {c: pd.Series(pd.to_numeric(s, errors="coerce").values,
                                 index=pd.to_datetime(s.index)) for c, s in turn_by_code.items()}

    _TG["sig"], _TG["turn"] = sig_by_code, turn_by_code   # fork前置,子进程COW共享
    t0 = time.time(); rows = []
    nproc = int(os.getenv("NPROC", "8"))
    from multiprocessing import Pool
    codes = sorted(sig_by_code)
    with Pool(nproc) as p:
        for k, part in enumerate(p.imap_unordered(_tf_proc, codes, chunksize=30), 1):
            rows.extend(part)
            if k % 1000 == 0:
                print(f"  …{k}/{len(codes)} 股，{int(time.time()-t0)}s", flush=True)
    ts = pd.DataFrame(rows)
    ts.to_csv(OUT, index=False, encoding="utf-8-sig")
    print(f"[换手率特征] 完成 {len(ts)} 行，写入 {OUT}，{int(time.time()-t0)}s", flush=True)
    # 简评：新信号命中率
    for col in ["换手率3_8", "筹码集中", "深度套牢", "尖刺金叉", "获利盘高"]:
        print(f"  {col}: 命中 {int(ts[col].sum())}", flush=True)


if __name__ == "__main__":
    main()
