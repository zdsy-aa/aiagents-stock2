# chanlun_batch.py
"""缠论选股批量扫描：经 akshare_gw.local 只读 TDX 本地库，算近7交易日买点落库。
手动：docker exec agentsstock1 python3 /app/chanlun_batch.py"""
import logging
import time
from datetime import datetime
import pandas as pd

from chanlun_engine import analyze, buy_point_with_exit
from chanlun_universe import list_universe, board_of
from chanlun_signal_db import ChanlunSignalDB

logger = logging.getLogger(__name__)

_RENAME = {"开盘": "Open", "最高": "High", "最低": "Low", "收盘": "Close", "成交量": "Volume"}


def _load(symbol: str, kind: str, limit: int):
    """经本地源取标准 OHLCV（索引=日期）；无数据返回 None。"""
    from akshare_gateway import akshare_gw
    df = akshare_gw.local.get_kline(symbol, kline_type=kind, limit=limit)
    if df is None or df.empty:
        return None
    df = df.rename(columns=_RENAME).set_index("日期").sort_index()
    return df[["Open", "High", "Low", "Close", "Volume"]]


def scan_codes(codes, db: ChanlunSignalDB, scan_date=None, days=7, name_board=None) -> int:
    """扫一批 code，把近 days 交易日内的买点写库。返回写入条数。
    name_board: {code: (name, board)}；缺省 board 用前缀推断、name 留空。"""
    scan_date = scan_date or datetime.now().strftime("%Y-%m-%d")
    name_board = name_board or {}
    rows = []
    for code in codes:
        try:
            df_day = _load(code, "day", 500)
            if df_day is None or len(df_day) < 60:
                continue
            df_30m = _load(code, "30min", 2000)
            res = analyze(df_day, df_30m)
            if not res.points:
                continue
            recent_dates = set(df_day.index[-days:])
            day_index = list(df_day.index)
            name, board = name_board.get(code, ("", board_of(code)))
            for p in res.points:
                if p.kind not in ("1买", "2买", "3买"):
                    continue
                if p.i < 0 or p.i >= len(day_index):
                    continue
                sig_dt = day_index[p.i]
                if sig_dt not in recent_dates:
                    continue
                info = buy_point_with_exit(p, res.pivots)
                rows.append({
                    "code": code, "name": name, "board": board,
                    "signal_type": info["signal_type"],
                    "signal_date": pd.Timestamp(sig_dt).strftime("%Y-%m-%d"),
                    "buy_price": info["buy_price"], "stop_loss": info["stop_loss"],
                    "exit_rule": info["exit_rule"], "level": "日线", "scan_date": scan_date,
                })
        except Exception as e:
            logger.debug(f"[缠论批量] {code} 跳过: {type(e).__name__}: {str(e)[:80]}")
    db.upsert_signals(rows)
    return len(rows)


def main():
    logging.basicConfig(level=logging.INFO,
                        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s")
    scan_date = datetime.now().strftime("%Y-%m-%d")
    db = ChanlunSignalDB()
    db.clear_scan(scan_date)  # 同日重跑先清
    universe = list_universe()
    name_board = {c: (n, b) for c, n, b in universe}
    codes = [c for c, _, _ in universe]
    logger.info(f"[缠论批量] 股票池 {len(codes)} 只，开始扫描 scan_date={scan_date}")
    t0 = time.time()
    n = scan_codes(codes, db, scan_date=scan_date, name_board=name_board)
    logger.info(f"[缠论批量] 完成：写入 {n} 条买点信号，耗时 {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
