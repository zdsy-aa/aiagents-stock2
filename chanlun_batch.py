# chanlun_batch.py
"""缠论选股批量扫描：经 akshare_gw.local 只读 TDX 本地库，算近7交易日买点落库。
手动：docker exec agentsstock1 python3 /app/chanlun_batch.py"""
import logging
import os
import time
from datetime import datetime
import pandas as pd

from base_db import DATA_DIR
from chanlun_engine import analyze, stop_loss_for, match_sell_after
from chanlun_universe import list_universe, board_of
from chanlun_signal_db import ChanlunSignalDB

logger = logging.getLogger(__name__)

_RENAME = {"开盘": "Open", "最高": "High", "最低": "Low", "收盘": "Close", "成交量": "Volume"}


def _load(symbol: str, kind: str, limit: int, live_bars=None):
    """经本地源取标准 OHLCV（索引=日期）；无数据返回 None。
    live_bars={code:bar} 且本品种有今日实时bar时，把今日bar注入日K末尾(盘中模式)。"""
    from akshare_gateway import akshare_gw
    df = akshare_gw.local.get_kline(symbol, kline_type=kind, limit=limit)
    if df is None or df.empty:
        return None
    df = df.rename(columns=_RENAME).set_index("日期").sort_index()
    df = df[["Open", "High", "Low", "Close", "Volume"]]
    if live_bars and kind == "day":
        import sys as _sys
        if "/app/data/profit_mining" not in _sys.path:   # 防逐股重复插入撑大 sys.path
            _sys.path.insert(0, "/app/data/profit_mining")
        import intraday_quote as IQ
        code = str(symbol)[-6:].zfill(6)
        df = IQ.inject_today_bar(df, live_bars.get(code), pd.Timestamp.now().normalize())
    return df


def scan_codes(codes, db: ChanlunSignalDB, scan_date=None, days=7, name_board=None, live_bars=None) -> int:
    """扫一批 code，把近 days 交易日内的买点写库。返回写入条数。
    name_board: {code: (name, board)}；缺省 board 用前缀推断、name 留空。
    live_bars: 盘中模式 {code:bar}，仅注入日线末根做盘中重算。"""
    scan_date = scan_date or datetime.now().strftime("%Y-%m-%d")
    name_board = name_board or {}
    rows = []
    for code in codes:
        try:
            df_day = _load(code, "day", 500, live_bars=live_bars)
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
                    "level": "日线", "scan_date": scan_date,
                })
        except Exception as e:
            logger.debug(f"[缠论批量] {code} 跳过: {type(e).__name__}: {str(e)[:80]}")
    db.upsert_signals(rows)
    return len(rows)


def export_scan_csv(db: ChanlunSignalDB, scan_date: str, out_dir: str = None, suffix: str = "") -> str:
    """把指定批次完整名单导出 CSV 备份(仅备份，不参与前台展示)。返回文件路径。
    suffix: 文件名后缀(盘中各时段用 _HHMM 区分，避免互相/被盘后覆盖)。"""
    out_dir = out_dir or os.path.join(DATA_DIR, "chanlun_history")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{scan_date}{suffix}.csv")
    df = db.get_signals_by_scan_date(scan_date)
    df.to_csv(path, index=False, encoding="utf-8-sig")  # utf-8-sig 便于 Excel 中文
    return path


def main():
    logging.basicConfig(level=logging.INFO,
                        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s")
    scan_date = datetime.now().strftime("%Y-%m-%d")
    intraday = os.getenv("CHANLUN_INTRADAY") == "1"
    live_bars = None
    if intraday:
        import sys
        sys.path.insert(0, "/app/data/profit_mining")
        import intraday_quote as IQ
        live_bars = IQ.fetch_market_snapshot()
        db = ChanlunSignalDB("chanlun_signals_intraday.db")
        logger.info(f"[缠论盘中] 实时快照 {len(live_bars)} 只，写独立库 chanlun_signals_intraday.db")
    else:
        db = ChanlunSignalDB()
    db.clear_scan(scan_date)  # 同日重跑先清
    universe = list_universe()
    name_board = {c: (n, b) for c, n, b in universe}
    codes = [c for c, _, _ in universe]
    logger.info(f"[缠论批量] 股票池 {len(codes)} 只，开始扫描 scan_date={scan_date}"
                + ("（盘中模式）" if intraday else ""))
    t0 = time.time()
    n = scan_codes(codes, db, scan_date=scan_date, name_board=name_board, live_bars=live_bars)
    logger.info(f"[缠论批量] 完成：写入 {n} 条买点信号，耗时 {time.time()-t0:.0f}s")
    try:
        if intraday:   # 盘中备份另存 intraday 子目录并带时段后缀，不覆盖盘后/各时段彼此
            csv_path = export_scan_csv(db, scan_date,
                                       out_dir=os.path.join(DATA_DIR, "chanlun_history", "intraday"),
                                       suffix="_" + datetime.now().strftime("%H%M"))
        else:
            csv_path = export_scan_csv(db, scan_date)
        logger.info(f"[缠论批量] 已导出 CSV 备份：{csv_path}")
    except Exception as e:
        logger.warning(f"[缠论批量] CSV 备份导出失败(不影响落库): {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
