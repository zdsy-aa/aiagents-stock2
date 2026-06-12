# fetch_mktcap_snapshot.py —— 拉 akshare 全市场快照,存 代码+总市值 → stock_mktcap_snapshot.csv。
# 用法: python3 fetch_mktcap_snapshot.py  (已存在当天文件则跳过)
import os
import sys
import time

OUT = "/app/data/profit_mining/stock_mktcap_snapshot.csv"


def extract_mktcap(df):
    """全市场快照 df → 仅 [代码, 总市值] 两列(代码转str)。缺总市值列则抛 ValueError。"""
    if df is None or "代码" not in df.columns or "总市值" not in df.columns:
        raise ValueError(f"快照缺 代码/总市值 列；实际列={None if df is None else list(df.columns)}")
    out = df[["代码", "总市值"]].copy()
    out["代码"] = out["代码"].astype(str).str.zfill(6)
    out = out.dropna(subset=["总市值"])
    return out


def main():
    if os.path.exists(OUT):
        mtime = time.strftime("%Y-%m-%d", time.localtime(os.path.getmtime(OUT)))
        if mtime == time.strftime("%Y-%m-%d"):
            print(f"[市值快照] 当天已存在 {OUT}，跳过")
            return
    if "/app" not in sys.path:
        sys.path.insert(0, "/app")
    from akshare_gateway import akshare_gw
    df = akshare_gw.call("stock_zh_a_spot_em")
    out = extract_mktcap(df)              # 失败(限流/缺列)直接抛错,不静默写空表
    out["采集日期"] = time.strftime("%Y-%m-%d")
    out.to_csv(OUT, index=False, encoding="utf-8-sig")
    print(f"[市值快照] 写 {OUT}，{len(out)} 行")


if __name__ == "__main__":
    main()
