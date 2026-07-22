# chanlun_interval.py —— 由全历史缠论买点明细算"到下一买点"的区间涨跌幅+是否盈利，
#   产出 含区间收益.csv 与 labels.csv(供 build_features)。
# 运行: docker exec -w /app agentsstock1 python3 /app/data/profit_mining/chanlun_interval.py
import csv
from collections import defaultdict

SRC = "/app/data/缠论买点全历史明细.csv"
OUT = "/app/data/缠论买点全历史明细_含区间收益.csv"
LABELS = "/app/data/profit_mining/labels.csv"
TYPE_ORDER = {"1买": 1, "2买": 2, "3买": 3}


def main():
    rows = list(csv.DictReader(open(SRC, encoding="utf-8-sig")))
    by_code = defaultdict(list)
    for r in rows:
        by_code[r["股票代码"]].append(r)
    out = []
    for code, lst in by_code.items():
        lst.sort(key=lambda r: (r["信号日期"], TYPE_ORDER.get(r["买点类型"], 9)))
        for i, r in enumerate(lst):
            nxt = lst[i + 1] if i + 1 < len(lst) else None
            if nxt is None:
                pct, flag = "", "无后续买点"
            else:
                buy = float(r["买入价"]); ex = float(nxt["买入价"])
                pct = round((ex - buy) / buy * 100, 2) if buy else 0.0
                flag = "盈利" if pct > 0 else ("亏损" if pct < 0 else "持平")
            r2 = dict(r)
            r2["区间涨跌幅(%)"] = pct
            r2["是否盈利"] = flag
            out.append(r2)
    cols = list(rows[0].keys()) + ["区间涨跌幅(%)", "是否盈利"]
    with open(OUT, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader()
        for r in out:
            w.writerow({k: r.get(k, "") for k in cols})
    # labels.csv = 同内容(build_features 读它)
    with open(LABELS, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader()
        for r in out:
            w.writerow({k: r.get(k, "") for k in cols})
    n_lab = sum(1 for r in out if r["是否盈利"] != "无后续买点")
    print(f"[区间收益] 全历史买点 {len(out)}，有效(有下一买点) {n_lab}，写入 含区间收益.csv + labels.csv", flush=True)


if __name__ == "__main__":
    main()
