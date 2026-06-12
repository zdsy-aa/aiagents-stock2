# liumai_batch.py
"""六脉神剑批量扫描: 经 akshare_gw.local 取日线, 算最新多头数, ≥5 者落库。
手动: docker exec agentsstock1 python3 /app/liumai_batch.py"""
import logging
import time
from datetime import datetime

from chanlun_batch import _load                     # 复用本地源加载(标准 OHLCV)
from chanlun_universe import list_universe, board_of
from liumai_engine import latest_snapshot, DIMS
from liumai_signal_db import LiumaiSignalDB

logger = logging.getLogger(__name__)
_MIN_BULL = 5


def scan_codes(codes, db: LiumaiSignalDB, scan_date=None, name_board=None) -> int:
    """扫一批 code, 最新多头数≥5 者写库。返回写入条数。
    name_board: {code: (name, board)}; 缺省 board 用前缀推断、name 留空。"""
    scan_date = scan_date or datetime.now().strftime("%Y-%m-%d")
    name_board = name_board or {}
    rows = []
    for code in codes:
        try:
            df_day = _load(code, "day", 300)
            snap = latest_snapshot(df_day)
            if snap is None or snap["bull_count"] < _MIN_BULL:
                continue
            name, board = name_board.get(code, ("", board_of(code)))
            row = {"code": code, "name": name, "board": board,
                   "signal_date": snap["signal_date"], "bull_count": snap["bull_count"],
                   "score": snap["score"], "state": snap["state"], "scan_date": scan_date}
            for d in DIMS:
                row[d.lower()] = snap[d]
            rows.append(row)
        except Exception as e:
            logger.debug(f"[六脉批量] {code} 跳过: {type(e).__name__}: {str(e)[:80]}")
    db.upsert_signals(rows)
    return len(rows)


def main():
    logging.basicConfig(level=logging.INFO,
                        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s")
    scan_date = datetime.now().strftime("%Y-%m-%d")
    db = LiumaiSignalDB()
    db.clear_scan(scan_date)                          # 同日重跑先清
    universe = list_universe()
    name_board = {c: (n, b) for c, n, b in universe}
    codes = [c for c, _, _ in universe]
    logger.info(f"[六脉批量] 股票池 {len(codes)} 只, 开始扫描 scan_date={scan_date}")
    t0 = time.time()
    n = scan_codes(codes, db, scan_date=scan_date, name_board=name_board)
    logger.info(f"[六脉批量] 完成: 写入 {n} 条(多头数≥5), 耗时 {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
