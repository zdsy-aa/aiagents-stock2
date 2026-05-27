# chanlun_engine.py
"""严格多级别缠论引擎（纯函数，零 IO，零 Streamlit）。
自底向上：包含处理→分型→笔→线段→中枢→MACD背驰→6类买卖点→多级别联立。
靠手工构造 K 线序列单测锚定行为。输入 DataFrame 列 Open/High/Low/Close/Volume，索引升序。"""
from dataclasses import dataclass
from typing import List, Optional, Literal
import pandas as pd

Direction = Literal["up", "down"]


@dataclass
class KBar:
    """包含处理后的无包含K线。i_lo/i_hi 为其覆盖的原始K线下标闭区间。"""
    high: float
    low: float
    i_lo: int          # 原始 DataFrame 行号（起）
    i_hi: int          # 原始 DataFrame 行号（止）
    dir: Direction     # 合并时的延伸方向


@dataclass
class Fractal:
    kind: Literal["top", "bottom"]
    k: int             # 在 KBar 列表中的位置（中间那根）
    i: int             # 对应原始 DataFrame 行号（取中间 KBar 的 i_hi）
    price: float       # 顶=high，底=low


@dataclass
class Stroke:
    dir: Direction
    start: Fractal
    end: Fractal

    @property
    def high(self) -> float:
        return max(self.start.price, self.end.price)

    @property
    def low(self) -> float:
        return min(self.start.price, self.end.price)


@dataclass
class Segment:
    dir: Direction
    i_start: int       # 原始行号
    i_end: int
    p_start: float
    p_end: float

    @property
    def high(self) -> float:
        return max(self.p_start, self.p_end)

    @property
    def low(self) -> float:
        return min(self.p_start, self.p_end)


@dataclass
class Pivot:
    """中枢：基于线段。ZG/ZD 为中枢区间，GG/DD 为波动极值。"""
    ZG: float
    ZD: float
    GG: float
    DD: float
    i_start: int
    i_end: int
    seg_count: int


@dataclass
class TradePoint:
    kind: Literal["1买", "2买", "3买", "1卖", "2卖", "3卖"]
    i: int             # 原始行号
    price: float
    note: str = ""     # 文字说明（背驰/回踩等）


@dataclass
class ChanResult:
    kbars: List[KBar]
    fractals: List[Fractal]
    strokes: List[Stroke]
    segments: List[Segment]
    pivots: List[Pivot]
    points: List[TradePoint]


def merge_inclusion(df: pd.DataFrame) -> List[KBar]:
    """K线包含处理：相邻两根存在包含关系时按当前方向合并。
    方向：第一次未定，用前两根非包含K线确定；向上取(高高,低高)，向下取(低低,高低)。"""
    rows = list(df[["High", "Low"]].itertuples(index=False, name=None))
    if not rows:
        return []
    ks: List[KBar] = [KBar(high=rows[0][0], low=rows[0][1], i_lo=0, i_hi=0, dir="up")]
    for i in range(1, len(rows)):
        h, l = rows[i]
        last = ks[-1]
        contained = (h <= last.high and l >= last.low) or (h >= last.high and l <= last.low)
        if contained:
            # 方向：用 last 与其前一根比较；只有一根时默认 up
            updir = ks[-2].high < last.high if len(ks) >= 2 else True
            if updir:
                last.high = max(last.high, h); last.low = max(last.low, l); last.dir = "up"
            else:
                last.high = min(last.high, h); last.low = min(last.low, l); last.dir = "down"
            last.i_hi = i
        else:
            d: Direction = "up" if h > last.high else "down"
            ks.append(KBar(high=h, low=l, i_lo=i, i_hi=i, dir=d))
    return ks
