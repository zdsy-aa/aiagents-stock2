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


def find_fractals(ks: List[KBar]) -> List[Fractal]:
    """在无包含K线序列上识别顶/底分型（标准三K分型）。"""
    fs: List[Fractal] = []
    for k in range(1, len(ks) - 1):
        a, b, c = ks[k - 1], ks[k], ks[k + 1]
        if b.high > a.high and b.high > c.high:
            fs.append(Fractal(kind="top", k=k, i=b.i_hi, price=b.high))
        elif b.low < a.low and b.low < c.low:
            fs.append(Fractal(kind="bottom", k=k, i=b.i_hi, price=b.low))
    return fs


_MIN_K_GAP = 3  # 一笔两端分型在 KBar 序列上至少相隔 3（含独立K约束）


def build_strokes(fractals: List[Fractal]) -> List[Stroke]:
    """由交替的顶/底分型连成笔。同向连续分型取更极端者；间隔不足的丢弃。"""
    if len(fractals) < 2:
        return []
    # 1) 规整：保证顶底交替，同向取极端
    seq: List[Fractal] = [fractals[0]]
    for f in fractals[1:]:
        last = seq[-1]
        if f.kind == last.kind:
            if (f.kind == "top" and f.price > last.price) or (f.kind == "bottom" and f.price < last.price):
                seq[-1] = f
        else:
            seq.append(f)
    # 2) 强制间隔：间隔不足时丢掉该转折并在同类相邻分型间取极端，保持严格顶底交替
    changed = True
    while changed and len(seq) >= 2:
        changed = False
        out: List[Fractal] = [seq[0]]
        k = 1
        while k < len(seq):
            if seq[k].k - out[-1].k >= _MIN_K_GAP:
                out.append(seq[k]); k += 1
            else:
                changed = True
                if k + 1 < len(seq):
                    a, c = out[-1], seq[k + 1]   # a 与 c 同类（seq 交替）
                    if (a.kind == "top" and c.price > a.price) or \
                       (a.kind == "bottom" and c.price < a.price):
                        out[-1] = c
                    k += 2
                else:
                    k += 1  # 末尾间隔不足，丢弃
        seq = out
    # 3) 由严格交替的分型连笔
    strokes: List[Stroke] = []
    for a, b in zip(seq, seq[1:]):
        strokes.append(Stroke(dir="up" if a.kind == "bottom" else "down", start=a, end=b))
    return strokes


def build_segments(strokes: List[Stroke]) -> List[Segment]:
    """线段划分（趋势分段法）：笔严格顶底交替，其端点构成锯齿。
    上升线段在「更高的高点 + 更高的低点」中延续；当某个低点跌破前一个低点时，
    线段在此前的最高点处结束、反转为下降线段（下降对称）。给出方向清晰的线段序列。"""
    if len(strokes) < 3:
        return []
    # 端点序列（与笔交替）：[(i, price), ...]
    pts = [(strokes[0].start.i, strokes[0].start.price)]
    for s in strokes:
        pts.append((s.end.i, s.end.price))
    n = len(pts)
    first_up = strokes[0].dir == "up"  # True: 奇数下标为高点；False: 偶数下标为高点

    def is_high(idx: int) -> bool:
        return (idx % 2 == 1) if first_up else (idx % 2 == 0)

    segs: List[Segment] = []
    seg_start = 0
    seg_dir: Direction = "up" if pts[1][1] > pts[0][1] else "down"
    seg_extreme = 0                       # 当前线段方向上的极值端点下标
    last_high_idx: Optional[int] = None
    last_low_idx: Optional[int] = None

    for idx in range(1, n):
        price = pts[idx][1]
        if is_high(idx):
            if seg_dir == "up":
                if last_high_idx is None or price >= pts[seg_extreme][1]:
                    seg_extreme = idx     # 续创新高
            else:
                if last_high_idx is not None and price > pts[last_high_idx][1]:
                    # 下降段中高点升破前高 → 反转为上升，下降段在其最低点结束
                    segs.append(Segment("down", pts[seg_start][0], pts[seg_extreme][0],
                                        pts[seg_start][1], pts[seg_extreme][1]))
                    seg_dir = "up"; seg_start = seg_extreme; seg_extreme = idx
            last_high_idx = idx
        else:
            if seg_dir == "down":
                if last_low_idx is None or price <= pts[seg_extreme][1]:
                    seg_extreme = idx     # 续创新低
            else:
                if last_low_idx is not None and price < pts[last_low_idx][1]:
                    # 上升段中低点跌破前低 → 反转为下降，上升段在其最高点结束
                    segs.append(Segment("up", pts[seg_start][0], pts[seg_extreme][0],
                                        pts[seg_start][1], pts[seg_extreme][1]))
                    seg_dir = "down"; seg_start = seg_extreme; seg_extreme = idx
            last_low_idx = idx

    segs.append(Segment(seg_dir, pts[seg_start][0], pts[seg_extreme][0],
                        pts[seg_start][1], pts[seg_extreme][1]))
    return [s for s in segs if s.i_start != s.i_end]
