# liumai_selector.py
"""六脉神剑选股: 读 liumai_signals.db 最新批次, 返回 (ok, df, msg)。"""
import logging
from typing import Tuple, Optional, List
import pandas as pd
from liumai_signal_db import LiumaiSignalDB

KEEP_COLS = ["code", "name", "board", "signal_date", "bull_count", "score", "state",
             "macd", "kdj", "rsi", "lwr", "bbi", "mtm"]
DISPLAY_NAMES = {"code": "代码", "name": "名称", "board": "板块",
                 "signal_date": "信号日期", "bull_count": "多头数", "score": "得分",
                 "state": "状态", "macd": "MACD", "kdj": "KDJ", "rsi": "RSI",
                 "lwr": "LWR", "bbi": "BBI", "mtm": "MTM"}


class LiumaiSelector:
    def __init__(self, db: Optional[LiumaiSignalDB] = None):
        self.logger = logging.getLogger(__name__)
        self.db = db or LiumaiSignalDB()

    def get_picks(self, min_bull: int = 5, scan_date: Optional[str] = None
                  ) -> Tuple[bool, Optional[pd.DataFrame], str]:
        df = (self.db.get_signals_by_scan_date(scan_date) if scan_date
              else self.db.get_latest_signals())
        if df is None or df.empty:
            return False, None, "暂无六脉神剑信号(批量扫描尚未运行)"
        df = df[df["bull_count"] >= min_bull]
        if df.empty:
            return False, None, f"暂无多头数≥{min_bull}的信号"
        scan_date = df["scan_date"].iloc[0]
        view = df[KEEP_COLS].reset_index(drop=True)
        return True, view, f"扫描批次 {scan_date}, 共 {len(view)} 只(多头数≥{min_bull})"

    def list_dates(self) -> List[str]:
        return self.db.list_scan_dates()
