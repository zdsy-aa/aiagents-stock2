# fetch_mktcap_snapshot.py —— 拉全市场市值快照,存 代码+总市值 → stock_mktcap_snapshot.csv。
# 数据源:腾讯 qt.gtimg.cn(东财已被IP封锁)。用法: python3 fetch_mktcap_snapshot.py
import os
import sys
import time

OUT = "/app/data/profit_mining/stock_mktcap_snapshot.csv"
EVENTS = "/app/data/profit_mining/events_labeled.csv"

GTIMG = "http://qt.gtimg.cn/q="
MKTCAP_IDX = 45      # 腾讯响应按 ~ 切分后 idx45=总市值(亿元);idx44=流通市值
YI = 1e8             # 亿 → 元


def extract_mktcap(df):
    """全市场快照 df → 仅 [代码, 总市值] 两列(代码转str)。缺总市值列则抛 ValueError。
    (保留供 test_group_dims 等 df 路径使用;腾讯路径走 fetch_mktcap。)"""
    if df is None or "代码" not in df.columns or "总市值" not in df.columns:
        raise ValueError(f"快照缺 代码/总市值 列；实际列={None if df is None else list(df.columns)}")
    out = df[["代码", "总市值"]].copy()
    out["代码"] = out["代码"].astype(str).str.zfill(6)
    out = out.dropna(subset=["总市值"])
    return out


def _prefix(code):
    """6位代码 → 带交易所前缀(腾讯查询用)。6/9→sh, 0/3→sz, 4/8→bj, 其余→sz。"""
    c = str(code).zfill(6)
    head = c[0]
    if head in ("6", "9"):
        ex = "sh"
    elif head in ("4", "8"):
        ex = "bj"
    else:               # 0/3 及其它
        ex = "sz"
    return ex + c


def _parse_line(line):
    """单行 v_xxx="f0~f1~..."; → (代码6位, 总市值元) | None(格式非法/字段不足/非数字)。"""
    if '"' not in line:
        return None
    try:
        payload = line.split('"', 2)[1]
    except IndexError:
        return None
    f = payload.split("~")
    if len(f) <= MKTCAP_IDX:
        return None
    code = f[2].strip()
    try:
        mktcap = float(f[MKTCAP_IDX]) * YI
    except (ValueError, IndexError):
        return None
    return code, mktcap


def _fetch_batch(prefixed):
    """实际网络取数:prefixed=['sh600519',...] → 腾讯响应文本(GBK)。"""
    import urllib.request
    url = GTIMG + ",".join(prefixed)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=15).read().decode("gbk", "ignore")


def fetch_mktcap(codes, batch=60, fetch=None):
    """批量取市值 → DataFrame[代码(6位zfill), 总市值(元)]。
    fetch(prefixed_list)->文本 可注入便于测试;默认走腾讯。单批失败重试1次仍失败则跳过该批。"""
    import pandas as pd
    if fetch is None:
        fetch = _fetch_batch
    codes = [str(c).zfill(6) for c in dict.fromkeys(codes)]   # 去重保序
    rows = []
    for i in range(0, len(codes), batch):
        chunk = codes[i:i + batch]
        prefixed = [_prefix(c) for c in chunk]
        text = None
        for attempt in range(2):                              # 一次重试
            try:
                text = fetch(prefixed)
                break
            except Exception as e:
                if attempt == 1:
                    print(f"  [跳过] 批 {chunk[0]}…{chunk[-1]} 取数失败: {e}", flush=True)
        if not text:
            continue
        for line in text.strip().splitlines():
            if not line.strip():
                continue
            parsed = _parse_line(line)
            if parsed:
                rows.append({"代码": str(parsed[0]).zfill(6), "总市值": parsed[1]})
    return pd.DataFrame(rows, columns=["代码", "总市值"])


def _universe():
    """events_labeled.csv 去重股票代码(≈全A历史)。"""
    import csv
    codes = []
    seen = set()
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
            print(f"[市值快照] 当天已存在 {OUT}，跳过")
            return
    codes = _universe()
    print(f"[市值快照] 股票池 {len(codes)} 只，开始向腾讯取数 …", flush=True)
    out = fetch_mktcap(codes)
    if len(out) == 0:                                # 全空直接抛错,不静默写空表
        raise ValueError("腾讯市值取数 0 行，疑似全部失败")
    out["采集日期"] = time.strftime("%Y-%m-%d")
    out.to_csv(OUT, index=False, encoding="utf-8-sig")
    print(f"[市值快照] 写 {OUT}，{len(out)} 行")


if __name__ == "__main__":
    main()
