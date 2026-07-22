# offset_sweep.py —— ±偏移遍历：极限抄底+量比≥1.3 在 ±0/1/2/3 观察窗口下的胜率/支持数。
# 运行: docker exec -w /app agentsstock1 python3 /app/data/profit_mining/offset_sweep.py
import sys, csv, time
sys.path.insert(0, "/app"); sys.path.insert(0, "/app/data/profit_mining")
from collections import defaultdict
import pandas as pd
import features as F

LABELS = "/app/data/profit_mining/labels.csv"
_RENAME = {"开盘": "Open", "最高": "High", "最低": "Low", "收盘": "Close", "成交量": "Volume"}
OFFSETS = [0, 1, 2, 3]
WIN = 4.0


def _load(code):
    from akshare_gateway import akshare_gw
    df = akshare_gw.local.get_kline(code, kline_type="day", limit=10000)
    if df is None or df.empty:
        return None
    return df.rename(columns=_RENAME).set_index("日期").sort_index()[["Open", "High", "Low", "Close", "Volume"]]


def main():
    rows = [r for r in csv.DictReader(open(LABELS, encoding="utf-8-sig")) if r["是否盈利"] != "无后续买点"]
    by_code = defaultdict(list)
    for r in rows:
        by_code[r["股票代码"]].append(r)
    # 每个offset: [满足且盈利, 满足总数]
    stat = {o: [0, 0] for o in OFFSETS}
    t0 = time.time()
    for k, code in enumerate(sorted(by_code), 1):
        df = _load(code)
        if df is None or len(df) < 70:
            continue
        cd = F.tdx_extra_features(df, code=code)["极限抄底"]
        ql = (F.volume_features(df)["量比"] >= 1.3).astype(int)
        pos = {d.strftime("%Y-%m-%d"): i for i, d in enumerate(df.index)}
        for r in by_code[code]:
            sd = r["信号日期"]
            if sd not in pos:
                continue
            i = pos[sd]
            win = 1 if float(r["区间涨跌幅(%)"]) >= WIN else 0
            for o in OFFSETS:
                if F.window_or_at(cd, i, o) and F.window_or_at(ql, i, o):
                    stat[o][1] += 1
                    stat[o][0] += win
        if k % 800 == 0:
            print(f"  …{k} 股，{int(time.time()-t0)}s", flush=True)
    print("\n=== ±偏移遍历：极限抄底+量比≥1.3 ===")
    print("| 窗口 | 支持数 | 胜率(≥4%) |")
    print("|---|---|---|")
    for o in OFFSETS:
        w, n = stat[o]
        print(f"| ±{o}日 | {n} | {w/n*100:.1f}% |" if n else f"| ±{o}日 | 0 | - |")
    print(f"[offset] 完成 {int(time.time()-t0)}s", flush=True)


if __name__ == "__main__":
    main()
