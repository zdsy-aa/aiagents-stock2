"""缠论图解 + 未来3天条件信号 只读页。

输入股票代码 → 缠论日线图(中枢/买卖点标注 + 未来3交易日决策区关键价位横线)
+ 图下6类买卖点未来条件。复用 chanlun_engine 只读，不下单/不发邮件。
"""
import logging

import pandas as pd

logger = logging.getLogger(__name__)

N_BARS = 120          # 图上展示最近日K根数
FUTURE_DAYS = 3       # 未来决策区交易日数


def forward_conditions(result, df):
    """基于当前 ChanResult 反推各类买卖点关键价位与条件文本。

    返回 list[dict(signal, direction, level, text, confidence)]；仅在对应结构存在时输出该条。
    3买/3卖←最近中枢ZG/ZD；2买/2卖←最近1买/1卖价；1买/1卖←最近下跌/上涨段端点(近似,需背驰确认)。
    """
    out = []
    pv = result.pivots[-1] if result.pivots else None
    if pv is not None:
        out.append({"signal": "3买", "direction": "up", "level": round(pv.ZG, 2),
                    "text": f"若价站上中枢ZG={pv.ZG:.2f}后回踩不破 → 3买（中枢突破）", "confidence": "明确"})
        out.append({"signal": "3卖", "direction": "down", "level": round(pv.ZD, 2),
                    "text": f"若跌破中枢ZD={pv.ZD:.2f}后反抽不破 → 3卖（中枢跌破）", "confidence": "明确"})

    one_buys = [p for p in result.points if p.kind == "1买"]
    one_sells = [p for p in result.points if p.kind == "1卖"]
    if one_buys:
        lv = one_buys[-1].price
        out.append({"signal": "2买", "direction": "up", "level": round(lv, 2),
                    "text": f"若回踩不破最近1买低点{lv:.2f} → 2买", "confidence": "明确"})
    if one_sells:
        lv = one_sells[-1].price
        out.append({"signal": "2卖", "direction": "down", "level": round(lv, 2),
                    "text": f"若反弹不破最近1卖高点{lv:.2f} → 2卖", "confidence": "明确"})

    downs = [s for s in result.segments if s.dir == "down"]
    ups = [s for s in result.segments if s.dir == "up"]
    if downs:
        z = downs[-1].low
        out.append({"signal": "1买", "direction": "down", "level": round(z, 2),
                    "text": f"若跌破前低{z:.2f}且下跌力度较前段衰减（MACD底背驰）→ 1买",
                    "confidence": "近似（需背驰确认）"})
    if ups:
        z = ups[-1].high
        out.append({"signal": "1卖", "direction": "up", "level": round(z, 2),
                    "text": f"若上破前高{z:.2f}且上涨力度衰减（MACD顶背驰）→ 1卖",
                    "confidence": "近似（需背驰确认）"})
    return out


def _next_trading_days(last_date, n=FUTURE_DAYS, is_trading_day=None):
    """从 last_date 之后推 n 个交易日(date 列表)。is_trading_day 可注入(默认用 intraday_quote)。"""
    if is_trading_day is None:
        import sys
        if "/app/data/profit_mining" not in sys.path:
            sys.path.insert(0, "/app/data/profit_mining")
        from intraday_quote import is_cn_trading_day as is_trading_day
    out = []
    d = pd.Timestamp(last_date)
    while len(out) < n:
        d = d + pd.Timedelta(days=1)
        if is_trading_day(d):
            out.append(d.date())
    return out
