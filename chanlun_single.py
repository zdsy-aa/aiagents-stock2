# chanlun_single.py
"""缠论单股查询：实时加载某股日线+30分钟K线，跑引擎，列出全历史所有买卖点(6类)。
与批量库(chanlun_signals.db)完全解耦——本模块只读 TDX 本地源、纯实时计算。"""
from typing import Tuple, Optional
import pandas as pd
from chanlun_batch import _load                       # 复用本地源加载(标准 OHLCV)
from chanlun_engine import analyze, stop_loss_for

_BUY = ("1买", "2买", "3买")

KEEP_COLS = ["signal_type", "signal_date", "price", "stop_loss", "reason", "level"]
DISPLAY_NAMES = {"signal_type": "信号类型", "signal_date": "信号日期",
                 "price": "信号参考价", "stop_loss": "止损位",
                 "reason": "缠论理由", "level": "级别"}


def _normalize(code: str) -> str:
    """规整为纯 6 位数字代码(去掉 sh/sz/bj 前缀与空白)。"""
    c = code.strip().lower()
    for pre in ("sh", "sz", "bj"):
        if c.startswith(pre):
            c = c[len(pre):]
    return c.strip()


def query_stock_signals(code: str) -> Tuple[bool, Optional[pd.DataFrame], str]:
    sym = _normalize(code)
    if not sym.isdigit() or len(sym) != 6:
        return False, None, "请输入 6 位股票代码（如 600519）"
    try:
        df_day = _load(sym, "day", 500)
        if df_day is None or len(df_day) < 60:
            return False, None, f"{sym} 本地无足够日线数据（需≥60根），无法计算"
        df_30m = _load(sym, "30min", 2000)
        res = analyze(df_day, df_30m)
    except Exception as e:  # 本地源/引擎异常不抛到页面，给友好提示
        return False, None, f"{sym} 计算失败：{type(e).__name__}: {str(e)[:80]}"
    if not res.points:
        return False, None, f"{sym} 全历史未检出缠论买卖点信号"
    day_index = list(df_day.index)
    rows = []
    for p in res.points:
        if p.i < 0 or p.i >= len(day_index):
            continue
        rows.append({
            "signal_type": p.kind,
            "signal_date": pd.Timestamp(day_index[p.i]).strftime("%Y-%m-%d"),
            "price": round(float(p.price), 3),
            "stop_loss": stop_loss_for(p, res.pivots) if p.kind in _BUY else None,
            "reason": p.note,
            "level": "日线",
        })
    if not rows:  # 引擎给了点但索引全越界(理论上需引擎 bug)，按无信号处理
        return False, None, f"{sym} 全历史未检出缠论买卖点信号"
    df = pd.DataFrame(rows, columns=KEEP_COLS).sort_values(
        "signal_date", ascending=False).reset_index(drop=True)
    return True, df, f"{sym} 全历史共 {len(df)} 个缠论信号（含买卖点）"
