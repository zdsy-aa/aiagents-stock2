# chanlun_full_export.py —— 全历史缠论买点明细导出
# A股，排除科创/北交/ST；不限近7日窗口，记录每只票全部日期的 1/2/3 买点。
# 运行： docker exec -w /app agentsstock1 python3 /app/data/chanlun_full_export.py
import sys, csv, time, logging
sys.path.insert(0, "/app")
import pandas as pd
from chanlun_engine import analyze, stop_loss_for, match_sell_after
from chanlun_universe import list_universe, board_of

logging.basicConfig(level=logging.WARNING)
_RENAME = {"开盘": "Open", "最高": "High", "最低": "Low", "收盘": "Close", "成交量": "Volume"}
DAY_LIMIT = 10000   # 全历史：放开到上市日（本地日K到1991/2001）

def _load(symbol, kind, limit):
    from akshare_gateway import akshare_gw
    df = akshare_gw.local.get_kline(symbol, kline_type=kind, limit=limit)
    if df is None or df.empty:
        return None
    df = df.rename(columns=_RENAME).set_index("日期").sort_index()
    return df[["Open", "High", "Low", "Close", "Volume"]]

def main():
    universe = list_universe()
    name_board = {c: (n, b) for c, n, b in universe}
    codes = [c for c, _, _ in universe]
    print(f"[全历史] 合格股票池 {len(codes)} 只，开始扫描…", flush=True)
    rows = []
    t0 = time.time()
    for idx, code in enumerate(codes, 1):
        try:
            df_day = _load(code, "day", DAY_LIMIT)
            if df_day is None or len(df_day) < 60:
                continue
            df_30m = None  # 全历史:30min本地仅近2年,跳过避免对老买点产生虚假次级别确认
            res = analyze(df_day, df_30m)
            if not res.points:
                continue
            day_index = list(df_day.index)
            name, board = name_board.get(code, ("", board_of(code)))
            for p in res.points:
                if p.kind not in ("1买", "2买", "3买"):
                    continue
                if p.i < 0 or p.i >= len(day_index):
                    continue
                sig_dt = day_index[p.i]
                sell = match_sell_after(p, res.points)
                sell_type = sell_date = sell_reason = ""
                if sell is not None and 0 <= sell.i < len(day_index):
                    sell_type = sell.kind
                    sell_date = pd.Timestamp(day_index[sell.i]).strftime("%Y-%m-%d")
                    sell_reason = sell.note
                rows.append({
                    "code": code, "name": name, "board": board,
                    "signal_type": p.kind,
                    "signal_date": pd.Timestamp(sig_dt).strftime("%Y-%m-%d"),
                    "buy_price": round(float(p.price), 3), "buy_reason": p.note,
                    "stop_loss": stop_loss_for(p, res.pivots),
                    "sell_type": sell_type, "sell_date": sell_date, "sell_reason": sell_reason,
                    "level": "日线",
                })
        except Exception as e:
            pass
        if idx % 500 == 0:
            print(f"  …已扫 {idx}/{len(codes)} 只，累计买点 {len(rows)} 条，耗时 {int(time.time()-t0)}s", flush=True)

    rows.sort(key=lambda r: (r["signal_date"], r["signal_type"], r["code"]))
    out = "/app/data/缠论买点全历史明细.csv"
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["股票代码","股票名称","板块","买点类型","信号日期","买入价","买点说明",
                    "止损位","卖点类型","卖点日期","卖点说明","级别"])
        for r in rows:
            w.writerow([r["code"],r["name"],r["board"],r["signal_type"],r["signal_date"],
                        r["buy_price"],r["buy_reason"],r["stop_loss"],
                        r["sell_type"],r["sell_date"],r["sell_reason"],r["level"]])
    print(f"[全历史] 完成：{len(rows)} 条买点，写入 {out}，总耗时 {int(time.time()-t0)}s", flush=True)

if __name__ == "__main__":
    main()
