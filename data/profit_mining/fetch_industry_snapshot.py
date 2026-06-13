# fetch_industry_snapshot.py —— baostock 拉证监会行业分类 → 代码+行业 → stock_industry_snapshot.csv。
# 用法: docker exec -w /app/data/profit_mining agentsstock1 python3 fetch_industry_snapshot.py
import os
import time

OUT = "/app/data/profit_mining/stock_industry_snapshot.csv"
EVENTS = "/app/data/profit_mining/events_labeled.csv"
INDUSTRY_IDX = 3      # baostock query_stock_industry 行: [date,code,name,industry,cls]


def _code6(bs_code):
    """'sh.600519' / 'sz.000001' → 6位代码。"""
    c = str(bs_code).split(".")[-1]
    return c.zfill(6)


def extract_industry(rows, universe):
    """baostock 行 list → {代码6位: 行业}。只留 universe 内 & 行业非空；重复代码用 setdefault 保留首次出现。"""
    out = {}
    uni = set(universe)
    for r in rows:
        if len(r) <= INDUSTRY_IDX:
            continue
        code = _code6(r[1])
        ind = (r[INDUSTRY_IDX] or "").strip()
        if not ind or code not in uni:
            continue
        out.setdefault(code, ind)
    return out


def fetch_industry(query=None):
    """调 baostock query_stock_industry → 全部行 list。query 可注入便于测试。"""
    if query is not None:
        return query()
    import baostock as bs
    bs.login()
    try:
        rs = bs.query_stock_industry()
        rows = []
        while (rs.error_code == "0") and rs.next():
            rows.append(rs.get_row_data())
        return rows
    finally:
        bs.logout()


def _universe():
    """events_labeled.csv 去重股票代码。"""
    import csv
    codes, seen = [], set()
    with open(EVENTS, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            c = (r.get("股票代码") or "").strip()
            if c and c not in seen:
                seen.add(c)
                codes.append(c)
    return codes


def main():
    if os.path.exists(OUT):
        mtime = time.strftime("%Y-%m-%d", time.localtime(os.path.getmtime(OUT)))
        if mtime == time.strftime("%Y-%m-%d"):
            print(f"[行业快照] 当天已存在 {OUT}，跳过")
            return
    universe = set(_universe())
    print(f"[行业快照] 股票池 {len(universe)} 只，向 baostock 取行业 …", flush=True)
    rows = None
    for attempt in range(2):                       # 一次重试
        try:
            rows = fetch_industry()
            break
        except Exception as e:
            if attempt == 1:
                raise
            print(f"  baostock 取数失败重试: {e}", flush=True)
    mapping = extract_industry(rows, universe)
    if not mapping:                                # 全空抛错,不静默写空表
        raise ValueError("baostock 行业取数 0 行,疑似全部失败")
    today = time.strftime("%Y-%m-%d")
    import csv
    with open(OUT, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["代码", "行业", "采集日期"])
        for code, ind in mapping.items():
            w.writerow([code, ind, today])
    print(f"[行业快照] 写 {OUT}，{len(mapping)} 行")


if __name__ == "__main__":
    main()
