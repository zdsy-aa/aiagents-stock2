# fetch_turnover.py —— 经 baostock 抓取信号股全历史换手率(turn)，存单CSV。
# 运行: docker exec -w /app agentsstock1 python3 /app/data/profit_mining/fetch_turnover.py
import csv, time
import baostock as bs

LABELS = "/app/data/profit_mining/labels.csv"
OUT = "/app/data/profit_mining/turnover.csv"
START, END = "2001-01-01", "2026-05-29"   # 全历史换手率


def bcode(code):
    code = str(code).zfill(6)
    if code[0] == "6":
        return "sh." + code
    if code[0] in ("0", "3"):
        return "sz." + code
    return None


def main():
    codes = sorted({r["股票代码"] for r in csv.DictReader(open(LABELS, encoding="utf-8-sig"))})
    bs.login()
    t0 = time.time()
    n_ok = 0
    with open(OUT, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["code", "date", "turn"])
        for k, c in enumerate(codes, 1):
            bc = bcode(c)
            if not bc:
                continue
            rs = bs.query_history_k_data_plus(bc, "date,turn", start_date=START, end_date=END,
                                              frequency="d", adjustflag="2")
            got = 0
            while rs.error_code == "0" and rs.next():
                d, t = rs.get_row_data()
                if t:
                    w.writerow([c, d, t]); got += 1
            if got:
                n_ok += 1
            if k % 300 == 0:
                print(f"  …{k}/{len(codes)} 股，有数据 {n_ok}，{int(time.time()-t0)}s", flush=True)
    bs.logout()
    print(f"[换手率] 完成 {n_ok} 股，{int(time.time()-t0)}s，写入 {OUT}", flush=True)


if __name__ == "__main__":
    main()
