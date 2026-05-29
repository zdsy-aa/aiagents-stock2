# chanlun_selector.py
"""缠论选股：读 chanlun_signals.db 最新批次，返回 (ok, df, msg)（对齐其它 *_selector）。
返回英文列(数据层)，中文展示由 chanlun_ui 负责。"""
import logging
from typing import Tuple, Optional, List
import pandas as pd
from chanlun_signal_db import ChanlunSignalDB

# 选股展示用的数据列（英文，UI 再做中文表头）
KEEP_COLS = ["code", "name", "board", "signal_type", "signal_date",
             "buy_reason", "buy_price", "stop_loss",
             "sell_type", "sell_date", "sell_reason"]
DISPLAY_NAMES = {"code": "代码", "name": "名称", "board": "板块",
                 "signal_type": "买点", "signal_date": "买点信号日期",
                 "buy_reason": "买入理由", "buy_price": "买入参考价", "stop_loss": "止损位",
                 "sell_type": "卖点", "sell_date": "卖点信号日期", "sell_reason": "卖出理由"}


class ChanlunSelector:
    def __init__(self, db: Optional[ChanlunSignalDB] = None):
        self.logger = logging.getLogger(__name__)
        self.db = db or ChanlunSignalDB()

    def get_chanlun_picks(self, types: Optional[List[str]] = None,
                          scan_date: Optional[str] = None
                          ) -> Tuple[bool, Optional[pd.DataFrame], str]:
        df = (self.db.get_signals_by_scan_date(scan_date) if scan_date
              else self.db.get_latest_signals())
        if df is None or df.empty:
            return False, None, "暂无缠论买点信号（批量扫描尚未运行或近7交易日无信号）"
        if types:
            df = df[df["signal_type"].isin(types)]
        if df.empty:
            return False, None, "所选买点类型暂无信号"
        scan_date = df["scan_date"].iloc[0]
        view = df[KEEP_COLS].reset_index(drop=True)
        return True, view, f"扫描批次 {scan_date}，共 {len(view)} 只"

    def list_dates(self) -> List[str]:
        """可选的扫描批次日期(倒序)，供前台日期下拉。"""
        return self.db.list_scan_dates()
