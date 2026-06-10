# intraday_quote.py —— 盘中实时行情：取全市场快照 + 把"今日实时bar"拼到日K末尾。
#   供 chanlun 盘中重算 与 daily_watchlist 盘中模式 共用。
import pandas as pd

_COLS = ["Open", "High", "Low", "Close", "Volume"]


def inject_today_bar(df, bar, today):
    """把今日实时 bar 拼到标准 OHLCV df(index=日期) 末尾。
    bar={'Open','High','Low','Close','Volume'}；today=pd.Timestamp(当天)。
    末行已是今天→覆盖；否则追加。bar 为 None/空→原样返回。不改入参。"""
    if not bar:
        return df
    today = pd.Timestamp(today).normalize()
    row = {c: float(bar.get(c)) for c in _COLS if bar.get(c) is not None}
    if len(row) < len(_COLS):
        return df  # 字段不全，保守不注入
    out = df.copy()
    out.loc[today, _COLS] = [row[c] for c in _COLS]
    return out.sort_index()[_COLS]
