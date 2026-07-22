# chanlun_sell_pipeline.py —— 缠论卖点导出+特征 一次完成 -> sell_features.csv
#   卖点=1卖/2卖/3卖；标签好卖点=到下一个卖点的区间涨跌幅≤-4%(卖后下跌即正确)。
# 运行: docker exec -w /app agentsstock1 python3 /app/data/profit_mining/chanlun_sell_pipeline.py [LIMIT]
import sys, csv, time
sys.path.insert(0, "/app"); sys.path.insert(0, "/app/data/profit_mining")
from collections import defaultdict
import pandas as pd
import features as F
from chanlun_engine import analyze
from chanlun_universe import list_universe, board_of

OUT = "/app/data/profit_mining/sell_features.csv"
IDXCSV = "/app/data/profit_mining/index_sh000001.csv"
_RENAME = {"开盘": "Open", "最高": "High", "最低": "Low", "收盘": "Close", "成交量": "Volume"}
WIN = -4.0   # 好卖点阈值：跌≥4%
OFFSET = 2


def _load(symbol, kind, limit):
    from akshare_gateway import akshare_gw
    df = akshare_gw.local.get_kline(symbol, kline_type=kind, limit=limit)
    if df is None or df.empty:
        return None
    return df.rename(columns=_RENAME).set_index("日期").sort_index()[["Open", "High", "Low", "Close", "Volume"]]


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    idx = pd.read_csv(IDXCSV, encoding="utf-8-sig"); idx["日期"] = pd.to_datetime(idx["日期"])
    idx = idx.set_index("日期").sort_index()[["Open", "High", "Low", "Close", "Volume"]]
    ist = F.index_state(idx); iclose = idx["Close"]

    universe = list_universe()
    nb = {c: (n, b) for c, n, b in universe}
    codes = [c for c, _, _ in universe]
    if limit:
        codes = codes[:limit]
    print(f"[卖点] 股票池 {len(codes)}，扫描中…", flush=True)

    bool_cols = None
    out_rows = []
    t0 = time.time()
    for k, code in enumerate(codes, 1):
        df_day = _load(code, "day", 10000)   # 全历史
        if df_day is None or len(df_day) < 70:
            continue
        df_30 = None   # 全历史:30min仅近2年,跳过避免老卖点虚假次级别确认
        try:
            res = analyze(df_day, df_30)
        except Exception:
            continue
        sells = [(p.i, p.kind, float(p.price)) for p in res.points
                 if p.kind in ("1卖", "2卖", "3卖") and 0 <= p.i < len(df_day)]
        if len(sells) < 2:
            pass
        sells.sort()
        rel = F.relative_strength(df_day["Close"], iclose.reindex(df_day.index).ffill())
        ff = F.assemble_feature_frame(df_day, ist, rel, code=code)
        if bool_cols is None:
            skip = set(F.CONTINUOUS_COLS) | {"大盘状态ID"}
            bool_cols = [c for c in ff.columns if c not in skip]
        name, board = nb.get(code, ("", board_of(code)))
        day_index = list(df_day.index)
        for j, (i, kind, price) in enumerate(sells):
            # 区间涨跌幅 = 到下一个卖点
            if j + 1 >= len(sells):
                continue
            ni, _, nprice = sells[j + 1]
            qj = (nprice - price) / price * 100
            rec = {"股票代码": code, "股票名称": name, "板块": board, "买点类型": kind,
                   "信号日期": pd.Timestamp(day_index[i]).strftime("%Y-%m-%d"),
                   "区间涨跌幅": round(qj, 2), "是否盈利": 1 if qj <= WIN else 0}
            for col in bool_cols:
                rec[col] = F.window_or_at(ff[col], i, OFFSET) if col in ff.columns else ""
            for col in F.CONTINUOUS_COLS:
                v = ff[col].iloc[i] if col in ff.columns else None
                rec[col] = round(float(v), 4) if v is not None and pd.notna(v) else ""
            out_rows.append(rec)
        if k % 500 == 0:
            print(f"  …{k}/{len(codes)}，卖点 {len(out_rows)}，{int(time.time()-t0)}s", flush=True)

    head = ["股票代码", "股票名称", "板块", "买点类型", "信号日期", "区间涨跌幅", "是否盈利"]
    cols = head + (bool_cols or []) + F.CONTINUOUS_COLS
    with open(OUT, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader()
        for r in out_rows:
            w.writerow(r)
    good = sum(r["是否盈利"] for r in out_rows)
    print(f"[卖点] 完成 {len(out_rows)} 个卖点，好卖点(跌≥4%) {good} ({good/max(len(out_rows),1)*100:.1f}%)，"
          f"写入 {OUT}，{int(time.time()-t0)}s", flush=True)


if __name__ == "__main__":
    main()
