# combo_batch.py
"""缠论×六脉组合扫描: 读 chanlun_signals.db 最新买点, 对每个买点检查其信号日
±3 交易日窗口内是否出现六脉多头数≥5, 命中落 combo_signals.db。
须在 chanlun_batch 之后跑。手动: docker exec agentsstock1 python3 /app/combo_batch.py"""
import logging
import time
from datetime import datetime
import pandas as pd

from chanlun_batch import _load                         # 复用本地源加载
from chanlun_signal_db import ChanlunSignalDB
from chanlun_universe import board_of
from liumai_engine import compute_flags, score_of, DIMS
from combo_signal_db import ComboSignalDB

logger = logging.getLogger(__name__)
_WINDOW = 3          # ±3 交易日
_MIN_BULL = 5        # 六脉≥5 红
_BUY = ("1买", "2买", "3买")
_MIN_BARS = 30


def scan(chanlun_db: ChanlunSignalDB, combo_db: ComboSignalDB, scan_date=None) -> int:
    """返回写入条数。chanlun_db 仅读, combo_db 写。"""
    scan_date = scan_date or datetime.now().strftime("%Y-%m-%d")
    chan = chanlun_db.get_latest_signals()
    if chan is None or chan.empty:
        return 0
    buys = chan[chan["signal_type"].isin(_BUY)]
    if buys.empty:
        combo_db.upsert_signals([])
        return 0
    rows = []
    for code, grp in buys.groupby("code"):
        try:
            df_day = _load(code, "day", 300)
            if df_day is None or len(df_day) < _MIN_BARS:
                continue
            flags = compute_flags(df_day)
            bc = flags[DIMS].sum(axis=1).astype(int)
            dates = [pd.Timestamp(x).strftime("%Y-%m-%d") for x in df_day.index]
            date_to_pos = {d: i for i, d in enumerate(dates)}
            for _, r in grp.iterrows():
                sig_date = str(r["signal_date"])
                pos = date_to_pos.get(sig_date)
                if pos is None:
                    continue
                lo, hi = max(0, pos - _WINDOW), min(len(bc) - 1, pos + _WINDOW)
                window = bc.iloc[lo:hi + 1]
                hit = window[window >= _MIN_BULL]
                if hit.empty:
                    continue
                first_label = hit.index[0]
                rows.append({
                    "code": code, "name": r.get("name", "") or "",
                    "board": r.get("board") or board_of(code),
                    "chanlun_type": r["signal_type"], "chanlun_date": sig_date,
                    "buy_reason": r.get("buy_reason", "") or "",
                    "liumai_date": pd.Timestamp(first_label).strftime("%Y-%m-%d"),
                    "liumai_bull_count": int(hit.iloc[0]),
                    "liumai_score": score_of(flags.loc[first_label]),
                    "scan_date": scan_date,
                })
        except Exception as e:
            logger.debug(f"[组合] {code} 跳过: {type(e).__name__}: {str(e)[:80]}")
    combo_db.upsert_signals(rows)
    return len(rows)


def main():
    logging.basicConfig(level=logging.INFO,
                        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s")
    scan_date = datetime.now().strftime("%Y-%m-%d")
    chanlun_db = ChanlunSignalDB()
    combo_db = ComboSignalDB()
    combo_db.clear_scan(scan_date)
    logger.info(f"[组合] 开始扫描 scan_date={scan_date}(读缠论最新买点)")
    t0 = time.time()
    n = scan(chanlun_db, combo_db, scan_date=scan_date)
    logger.info(f"[组合] 完成: 命中 {n} 条(缠论买点±3交易日内六脉≥5红), 耗时 {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
