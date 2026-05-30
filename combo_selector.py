# combo_selector.py
"""缠论×六脉组合选股: 读 combo_signals.db 最新批次, 返回 (ok, df, msg)。"""
import logging
from typing import Tuple, Optional, List
import pandas as pd
from combo_signal_db import ComboSignalDB

KEEP_COLS = ["code", "name", "board", "chanlun_type", "chanlun_date", "buy_reason",
             "liumai_date", "liumai_bull_count", "liumai_score"]
DISPLAY_NAMES = {"code": "代码", "name": "名称", "board": "板块",
                 "chanlun_type": "缠论买点", "chanlun_date": "缠论信号日",
                 "buy_reason": "缠论理由", "liumai_date": "六脉达标日",
                 "liumai_bull_count": "六脉多头数", "liumai_score": "六脉得分"}


class ComboSelector:
    def __init__(self, db: Optional[ComboSignalDB] = None):
        self.logger = logging.getLogger(__name__)
        self.db = db or ComboSignalDB()

    def get_picks(self, scan_date: Optional[str] = None
                  ) -> Tuple[bool, Optional[pd.DataFrame], str]:
        df = (self.db.get_signals_by_scan_date(scan_date) if scan_date
              else self.db.get_latest_signals())
        if df is None or df.empty:
            return False, None, "暂无组合信号(批量扫描尚未运行, 或当日无缠论买点±3日内六脉≥5红)"
        scan_date = df["scan_date"].iloc[0]
        view = df[KEEP_COLS].reset_index(drop=True)
        return True, view, f"扫描批次 {scan_date}, 共 {len(view)} 只(缠论买点×六脉≥5红)"

    def list_dates(self) -> List[str]:
        return self.db.list_scan_dates()
