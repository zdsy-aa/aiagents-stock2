# build_forward_stats.py —— 前向统计：每个信号后多少交易日"启动"(首次涨≥4%)、60日内最大涨幅、
#   是否有足够前向数据(应对右截断)。运行: docker exec -w /app agentsstock1 python3 .../build_forward_stats.py
import sys, csv, time
sys.path.insert(0, "/app")
from collections import defaultdict
import pandas as pd

LABELS = "/app/data/profit_mining/labels.csv"
OUT = "/app/data/profit_mining/forward_stats.csv"
_RENAME = {"开盘": "Open", "最高": "High", "最低": "Low", "收盘": "Close", "成交量": "Volume"}
TARGET = 0.04
HORIZON = 60


def _load(symbol):
    from akshare_gateway import akshare_gw
    df = akshare_gw.local.get_kline(symbol, kline_type="day", limit=10000)
    if df is None or df.empty:
        return None
    df = df.rename(columns=_RENAME).set_index("日期").sort_index()
    return df[["High", "Close"]]


def main():
    rows = [r for r in csv.DictReader(open(LABELS, encoding="utf-8-sig"))
            if r["是否盈利"] != "无后续买点"]
    by_code = defaultdict(list)
    for r in rows:
        by_code[r["股票代码"]].append(r)
    out_rows, t0 = [], time.time()
    for k, code in enumerate(sorted(by_code), 1):
        df = _load(code)
        if df is None or len(df) < 70:
            continue
        pos = {d.strftime("%Y-%m-%d"): i for i, d in enumerate(df.index)}
        highs = df["High"].to_numpy()
        n = len(df)
        for r in by_code[code]:
            sd = r["信号日期"]
            if sd not in pos:
                continue
            i = pos[sd]
            buy = float(r["买入价"]) if r.get("买入价") else float(df["Close"].iloc[i])
            fwd = min(HORIZON, n - 1 - i)            # 可用前向交易日数
            launch = ""                                # 首次涨≥4%的天数
            maxgain = ""
            if fwd > 0:
                window_high = highs[i + 1:i + 1 + fwd]
                mg = (window_high.max() - buy) / buy * 100
                maxgain = round(float(mg), 2)
                hit = [d for d, hi in enumerate(window_high, 1) if (hi - buy) / buy >= TARGET]
                launch = hit[0] if hit else ""
            out_rows.append({"股票代码": code, "买点类型": r["买点类型"], "信号日期": sd,
                             "前向可用日": fwd, "启动天数": launch, "60日最大涨幅": maxgain})
        if k % 800 == 0:
            print(f"  …{k} 股，累计 {len(out_rows)}，{int(time.time()-t0)}s", flush=True)
    cols = ["股票代码", "买点类型", "信号日期", "前向可用日", "启动天数", "60日最大涨幅"]
    with open(OUT, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(out_rows)
    print(f"[前向] 完成 {len(out_rows)} 个信号，写入 {OUT}，{int(time.time()-t0)}s", flush=True)


if __name__ == "__main__":
    main()
