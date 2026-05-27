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


def build_pivots(segments: List[Segment]) -> List[Pivot]:
    """连续≥3段重叠构成中枢；重叠继续则延伸，断开则结束并尝试新中枢。"""
    pivots: List[Pivot] = []
    n = len(segments)
    i = 0
    while i + 2 < n:
        s1, s2, s3 = segments[i], segments[i + 1], segments[i + 2]
        zd = max(s1.low, s2.low, s3.low)
        zg = min(s1.high, s2.high, s3.high)
        if zd <= zg:
            gg = max(s1.high, s2.high, s3.high)
            dd = min(s1.low, s2.low, s3.low)
            j = i + 3
            seg_count = 3
            # 严格重叠才延伸：仅触及边沿(low==zg 或 high==zd)的「离开段」不并入，
            # 它正是三类买卖点的「离开中枢段」。
            while j < n and segments[j].low < zg and segments[j].high > zd:
                gg = max(gg, segments[j].high); dd = min(dd, segments[j].low)
                seg_count += 1
                j += 1
            pivots.append(Pivot(ZG=zg, ZD=zd, GG=gg, DD=dd,
                                i_start=s1.i_start, i_end=segments[j - 1].i_end,
                                seg_count=seg_count))
            i = j  # 中枢后从断开段继续
        else:
            i += 1
    return pivots


def compute_macd(close: pd.Series, fast=12, slow=26, signal=9):
    """标准 MACD：返回 (dif, dea, hist)。hist = (dif-dea)*2。"""
    ema_f = close.ewm(span=fast, adjust=False).mean()
    ema_s = close.ewm(span=slow, adjust=False).mean()
    dif = ema_f - ema_s
    dea = dif.ewm(span=signal, adjust=False).mean()
    hist = (dif - dea) * 2
    return dif, dea, hist


def seg_macd_power(hist: pd.Series, i0: int, i1: int) -> float:
    """区间 [i0,i1] 内 MACD 柱的绝对面积之和（力度）。"""
    if i1 < i0:
        i0, i1 = i1, i0
    seg = hist.iloc[i0:i1 + 1]
    return float(seg.abs().sum())


def is_diverging(power_late: float, power_prev: float, ratio: float = 0.9) -> bool:
    """后段力度显著小于前段（< ratio*前段）即判背驰。"""
    if power_prev <= 0:
        return False
    return power_late < ratio * power_prev


def detect_trade_points(segments: List[Segment], pivots: List[Pivot],
                        close: pd.Series) -> List[TradePoint]:
    """单级别 6 类买卖点。close 用于 MACD 背驰（索引与原始行号对齐）。"""
    pts: List[TradePoint] = []
    _, _, hist = compute_macd(close)

    def power(seg: Segment) -> float:
        return seg_macd_power(hist, seg.i_start, seg.i_end)

    # --- 1买/1卖：同向相邻段（中间隔一反向段）的力度背驰 ---
    for j in range(2, len(segments)):
        cur, prev = segments[j], segments[j - 2]
        if cur.dir != prev.dir:
            continue
        if cur.dir == "down" and cur.p_end < prev.p_end and is_diverging(power(cur), power(prev)):
            pts.append(TradePoint("1买", cur.i_end, cur.p_end, "下跌段力度背驰"))
        if cur.dir == "up" and cur.p_end > prev.p_end and is_diverging(power(cur), power(prev)):
            pts.append(TradePoint("1卖", cur.i_end, cur.p_end, "上涨段力度背驰"))

    # --- 2买/2卖：1买/1卖之后回踩不破极值 ---
    one_buys = [p for p in pts if p.kind == "1买"]
    one_sells = [p for p in pts if p.kind == "1卖"]
    for ob in one_buys:
        after = [s for s in segments if s.i_start >= ob.i]
        for a, b in zip(after, after[1:]):
            if a.dir == "up" and b.dir == "down" and b.p_end > ob.price:
                pts.append(TradePoint("2买", b.i_end, b.p_end, "回踩不破1买低点"))
                break
    for os_ in one_sells:
        after = [s for s in segments if s.i_start >= os_.i]
        for a, b in zip(after, after[1:]):
            if a.dir == "down" and b.dir == "up" and b.p_end < os_.price:
                pts.append(TradePoint("2卖", b.i_end, b.p_end, "反弹不创1卖高点"))
                break

    # --- 3买/3卖：突破中枢后回踩/反抽不破中枢边沿 ---
    for pv in pivots:
        after = [s for s in segments if s.i_start >= pv.i_end]
        for a, b in zip(after, after[1:]):
            if a.dir == "up" and a.high > pv.ZG and b.dir == "down" and b.low > pv.ZG:
                pts.append(TradePoint("3买", b.i_end, b.p_end, f"上破中枢ZG={pv.ZG}回踩不破"))
                break
            if a.dir == "down" and a.low < pv.ZD and b.dir == "up" and b.high < pv.ZD:
                pts.append(TradePoint("3卖", b.i_end, b.p_end, f"下破中枢ZD={pv.ZD}反抽不破"))
                break
    pts.sort(key=lambda p: p.i)
    return pts


def analyze_one(df: pd.DataFrame) -> ChanResult:
    ks = merge_inclusion(df)
    fs = find_fractals(ks)
    sts = build_strokes(fs)
    segs = build_segments(sts)
    pvs = build_pivots(segs)
    close = df["Close"].reset_index(drop=True)
    pts = detect_trade_points(segs, pvs, close)
    return ChanResult(kbars=ks, fractals=fs, strokes=sts, segments=segs, pivots=pvs, points=pts)


def analyze(df_day: pd.DataFrame, df_30m: Optional[pd.DataFrame] = None) -> ChanResult:
    """日线为本级别；30分钟次级别同类型买卖点确认。"""
    day = analyze_one(df_day)
    if df_30m is None or len(df_30m) < 20:
        for p in day.points:
            p.note = (p.note + "；无次级别确认").strip("；")
        return day
    sub = analyze_one(df_30m)
    sub_kinds = {p.kind for p in sub.points}
    for p in day.points:
        confirmed = p.kind in sub_kinds
        p.note = (p.note + ("；30m确认" if confirmed else "；无次级别确认")).strip("；")
    return day


def buy_point_with_exit(bp: TradePoint, pivots: List[Pivot]) -> dict:
    """把一个买点打包成含止损/离场条件的 dict。"""
    nearest_zd = None
    for pv in pivots:
        if pv.i_end <= bp.i:
            nearest_zd = pv.ZD
    base_stop = bp.price * 0.98
    stop = min(base_stop, nearest_zd) if nearest_zd is not None else base_stop
    exit_rule = ("出现日线级别一卖(顶背驰,30m确认)或二卖(反弹不创新高)或三卖"
                 "(跌破中枢ZD后反抽不破)；或跌破止损位离场")
    return {
        "signal_type": bp.kind,
        "buy_price": round(float(bp.price), 3),
        "stop_loss": round(float(stop), 3),
        "exit_rule": exit_rule,
        "note": bp.note,
    }
