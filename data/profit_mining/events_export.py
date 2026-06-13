# events_export.py —— 导出12组买卖点明细+30日窗口标签 → events_labeled.csv
# 运行: docker exec -w /app agentsstock1 python3 /app/data/profit_mining/events_export.py [LIMIT]
import sys, csv, time, os
sys.path.insert(0, "/app"); sys.path.insert(0, "/app/data/profit_mining")
import pandas as pd
import features as F
import label_window as LW
import event_registry as ER
from chanlun_engine import analyze
from chanlun_universe import list_universe, board_of

OUT = "/app/data/profit_mining/events_labeled.csv"
IDXCSV = "/app/data/profit_mining/index_sh000001.csv"
_RENAME = {"开盘":"Open","最高":"High","最低":"Low","收盘":"Close","成交量":"Volume"}
WIN, THRESH, OFFSET = 30, 0.10, 2
COOLDOWN = 10   # 信号源组(六脉/庄散)同股同组冷却:N根内不重复计,去抖
SIGNAL_EVENTS = {g: v for g, v in ER.EVENTS.items() if v["source"] == "signal"}


def _load(code):
    from akshare_gateway import akshare_gw
    df = akshare_gw.local.get_kline(code, kline_type="day", limit=10000)
    if df is None or df.empty:
        return None
    return df.rename(columns=_RENAME).set_index("日期").sort_index()[["Open","High","Low","Close","Volume"]]

_G = {}
def _init(nb):
    _G["nb"] = nb

def _proc(code):
    df = _load(code)
    if df is None or len(df) < 80:
        return []
    name, board = _G["nb"].get(code, ("", board_of(code)))
    rows = []
    di = list(df.index)
    # 缠论组（引擎）
    try:
        res = analyze(df, None)
        for p in res.points:
            if p.kind not in ("1买","2买","3买","1卖","2卖","3卖"):
                continue
            if not (0 <= p.i < len(di)):
                continue
            grp = "缠论" + p.kind
            direction = ER.EVENTS[grp]["direction"]
            label, ret, trunc = LW.forward_window_label(df, p.i, direction, WIN, THRESH)
            rows.append(dict(组=grp, family="缠论", direction=direction, 股票代码=code,
                股票名称=name, 板块=board, 信号日期=pd.Timestamp(di[p.i]).strftime("%Y-%m-%d"),
                bar=p.i, 标签=label, 极值收益=ret, truncated=int(trunc)))
    except Exception:
        pass
    # 六脉/庄散组（信号扫描）
    sig = F.assemble_feature_frame(df, None, None, code=code)
    for grp, v in SIGNAL_EVENTS.items():
        col = v["kind"]
        if col not in sig.columns:
            continue
        hit_pos = sorted(di.index(dt) for dt in
                         sig.index[pd.to_numeric(sig[col], errors="coerce").fillna(0) > 0])
        last = -10**9
        for i in hit_pos:
            if i - last < COOLDOWN:   # 冷却:同股同组N根内不重复计
                continue
            last = i
            dt = di[i]
            label, ret, trunc = LW.forward_window_label(df, i, v["direction"], WIN, THRESH)
            rows.append(dict(组=grp, family=v["family"], direction=v["direction"], 股票代码=code,
                股票名称=name, 板块=board, 信号日期=pd.Timestamp(dt).strftime("%Y-%m-%d"),
                bar=i, 标签=label, 极值收益=ret, truncated=int(trunc)))
    return rows


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    universe = list_universe()
    nb = {c: (n, b) for c, n, b in universe}
    codes = [c for c, _, _ in universe]
    if limit:
        codes = codes[:limit]
    print(f"[事件导出] 股票池 {len(codes)}", flush=True)
    out_rows = []; t0 = time.time()
    from multiprocessing import Pool
    nproc = int(os.getenv("NPROC", "8"))
    with Pool(nproc, initializer=_init, initargs=(nb,)) as p:
        for k, rows in enumerate(p.imap_unordered(_proc, codes, chunksize=30), 1):
            out_rows.extend(rows)
            if k % 1000 == 0:
                print(f"  …{k}/{len(codes)}，事件 {len(out_rows)}，{int(time.time()-t0)}s", flush=True)
    cols = ["组","family","direction","股票代码","股票名称","板块","信号日期","bar","标签","极值收益","truncated"]
    with open(OUT, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader()
        for r in out_rows:
            w.writerow(r)
    import collections
    by = collections.Counter(r["组"] for r in out_rows)
    pos = collections.Counter(r["组"] for r in out_rows if r["标签"] == 1)
    print(f"[事件导出] 完成 {len(out_rows)} 事件，写入 {OUT}，{int(time.time()-t0)}s", flush=True)
    for g in ER.EVENTS:
        n = by.get(g, 0); p = pos.get(g, 0)
        print(f"  {g}: {n}  基线={p/n*100:.1f}%" if n else f"  {g}: 0")


if __name__ == "__main__":
    main()
