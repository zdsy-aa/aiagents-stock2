# build_features.py —— 阶段1：逐股加载日K+大盘，对每信号±2窗口算布尔特征 → signal_features.csv
# 运行: docker exec -w /app agentsstock1 python3 /app/data/profit_mining/build_features.py [LIMIT]
import sys, csv, time, os
sys.path.insert(0, "/app")
sys.path.insert(0, "/app/data/profit_mining")
from collections import defaultdict
import pandas as pd
import features as F

LABELS = "/app/data/profit_mining/labels.csv"
OUT = "/app/data/profit_mining/signal_features.csv"
WIN_THRESH = 4.0
OFFSET = 2
_RENAME = {"开盘": "Open", "最高": "High", "最低": "Low", "收盘": "Close", "成交量": "Volume"}


def _load_local(symbol, kind, limit):
    from akshare_gateway import akshare_gw
    df = akshare_gw.local.get_kline(symbol, kline_type=kind, limit=limit)
    if df is None or df.empty:
        return None
    df = df.rename(columns=_RENAME).set_index("日期").sort_index()
    return df[["Open", "High", "Low", "Close", "Volume"]]


def _load_index():
    """优先读缓存CSV(index_sh000001.csv)；缺失则现拉AKShare并缓存。"""
    import os
    cache = "/app/data/profit_mining/index_sh000001.csv"
    if not os.path.exists(cache):
        try:
            import akshare as ak
            d = ak.stock_zh_index_daily(symbol="sh000001").rename(columns={
                "date": "日期", "open": "Open", "high": "High", "low": "Low",
                "close": "Close", "volume": "Volume"})
            d.to_csv(cache, index=False, encoding="utf-8-sig")
        except Exception:
            return None
    try:
        df = pd.read_csv(cache, encoding="utf-8-sig")
        df["日期"] = pd.to_datetime(df["日期"])
        df = df.set_index("日期").sort_index()
        return df[["Open", "High", "Low", "Close", "Volume"]]
    except Exception:
        return None


_G = {}   # 子进程共享(index_state_df, index_close, by_code, bool_cols)


def _bf_init(index_state_df, index_close, by_code, bool_cols):
    _G.update(index_state_df=index_state_df, index_close=index_close,
              by_code=by_code, bool_cols=bool_cols)


def _bf_proc(code):
    """处理单只票，返回该票所有信号的特征行列表。"""
    df = _load_local(code, "day", 10000)
    if df is None or len(df) < 70:
        return []
    isd, iclose = _G["index_state_df"], _G["index_close"]
    bool_cols, by_code = _G["bool_cols"], _G["by_code"]
    rel_df = F.relative_strength(df["Close"], iclose.reindex(df.index).ffill()) if iclose is not None else None
    ff = F.assemble_feature_frame(df, isd, rel_df, code=code)
    date_pos = {d.strftime("%Y-%m-%d"): i for i, d in enumerate(df.index)}
    rows = []
    for r in by_code[code]:
        sd = r["信号日期"]
        if sd not in date_pos:
            continue
        i = date_pos[sd]
        rec = {"股票代码": code, "股票名称": r["股票名称"], "板块": r["板块"],
               "买点类型": r["买点类型"], "信号日期": sd,
               "区间涨跌幅": float(r["区间涨跌幅(%)"]),
               "是否盈利": 1 if float(r["区间涨跌幅(%)"]) >= WIN_THRESH else 0}
        for col in bool_cols:
            rec[col] = F.window_or_at(ff[col], i, OFFSET) if col in ff.columns else ""
        for col in F.CONTINUOUS_COLS:
            val = ff[col].iloc[i] if col in ff.columns else None
            rec[col] = round(float(val), 4) if val is not None and pd.notna(val) else ""
        rows.append(rec)
    return rows


def _detect_bool_cols(codes, index_state_df, index_close):
    """用样本股探测布尔特征列集合。"""
    for code in codes:
        df = _load_local(code, "day", 10000)
        if df is None or len(df) < 70:
            continue
        rel = F.relative_strength(df["Close"], index_close.reindex(df.index).ffill()) if index_close is not None else None
        ff = F.assemble_feature_frame(df, index_state_df, rel, code=code)
        skip = set(F.CONTINUOUS_COLS) | {"大盘状态ID"}
        return [c for c in ff.columns if c not in skip]
    return []


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    rows = [r for r in csv.DictReader(open(LABELS, encoding="utf-8-sig"))
            if r["是否盈利"] != "无后续买点"]
    by_code = defaultdict(list)
    for r in rows:
        by_code[r["股票代码"]].append(r)
    codes = sorted(by_code)
    if limit:
        codes = codes[:limit]

    idx_df = _load_index()
    index_state_df = F.index_state(idx_df) if idx_df is not None else None
    index_close = idx_df["Close"] if idx_df is not None else None
    print(f"[阶段1] 大盘指数: {'已加载' if idx_df is not None else '缺失(市场环境置空)'}；"
          f"待处理股票 {len(codes)} 只", flush=True)

    cont_cols = F.CONTINUOUS_COLS
    bool_cols = _detect_bool_cols(codes, index_state_df, index_close)
    out_rows = []
    t0 = time.time()
    nproc = int(os.getenv("NPROC", "8"))
    from multiprocessing import Pool
    with Pool(nproc, initializer=_bf_init,
              initargs=(index_state_df, index_close, by_code, bool_cols)) as p:
        for k, rows in enumerate(p.imap_unordered(_bf_proc, codes, chunksize=30), 1):
            out_rows.extend(rows)
            if k % 1000 == 0:
                print(f"  …{k}/{len(codes)} 股，累计信号 {len(out_rows)}，耗时 {int(time.time()-t0)}s", flush=True)

    head = ["股票代码", "股票名称", "板块", "买点类型", "信号日期", "区间涨跌幅", "是否盈利"]
    cols = head + (bool_cols or []) + cont_cols
    with open(OUT, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for rec in out_rows:
            w.writerow(rec)
    win = sum(r["是否盈利"] for r in out_rows)
    print(f"[阶段1] 完成：{len(out_rows)} 个信号，盈利 {win} "
          f"({win/max(len(out_rows),1)*100:.1f}%)，布尔特征 {len(bool_cols or [])} 个，"
          f"写入 {OUT}，耗时 {int(time.time()-t0)}s", flush=True)


if __name__ == "__main__":
    main()
