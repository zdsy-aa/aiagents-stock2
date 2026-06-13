# features.py —— 纯特征函数：输入标准OHLCV(DataFrame, index=日期)，输出布尔/连续特征列。
# 所有特征仅用当前及之前数据(无未来函数)。TDX公式移植自 强信号共振选股V5.txt 内联段。
import numpy as np
import pandas as pd

# ---------------- TDX 函数 → pandas 移植助手 ----------------
def MA(x, n):   return x.rolling(n, min_periods=n).mean()
def EMA(x, n):  return x.ewm(span=n, adjust=False).mean()
def SMA(x, n, m):  # TDX SMA(X,N,M)= 递归 Y=(M*X+(N-M)*Y')/N
    return x.ewm(alpha=m / n, adjust=False).mean()
def REF(x, n):  return x.shift(n)
def HHV(x, n):  return x.rolling(n, min_periods=1).max()
def LLV(x, n):  return x.rolling(n, min_periods=1).min()
def SUM(x, n):  return x.rolling(n, min_periods=1).sum()
def COUNT(c, n): return c.astype(float).rolling(n, min_periods=1).sum()
def STD(x, n):  return x.rolling(n, min_periods=n).std()
def CROSS(a, b): return (a > b) & (a.shift(1) <= b.shift(1))


def TR(df):
    h, l, pc = df["High"], df["Low"], df["Close"].shift(1)
    return pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)


def BARSLAST(cond):
    """距上次cond为真的bar数；从未为真则取很大值。"""
    cond = cond.fillna(False).to_numpy().astype(bool)
    out = np.empty(len(cond), dtype=float)
    last = -10**9
    for i, v in enumerate(cond):
        if v:
            last = i
        out[i] = i - last
    return pd.Series(out, index=cond.shape and None)  # placeholder, replaced below


def barslast(cond_series):
    cond = cond_series.fillna(False).to_numpy().astype(bool)
    out = np.full(len(cond), 9999.0)
    last = None
    for i, v in enumerate(cond):
        if last is not None:
            out[i] = i - last
        if v:
            last = i
    return pd.Series(out, index=cond_series.index)


# ===================================================================
# A. 价格形态类（含斐波均线 5/13/34/55/89/144/233）
# ===================================================================
FIB = [5, 13, 34, 55, 89, 144, 233]


def price_form_features(df):
    c, h, l = df["Close"], df["High"], df["Low"]
    ma5, ma10, ma20, ma60 = (MA(c, w) for w in (5, 10, 20, 60))
    hhv60, llv60 = HHV(h, 60), LLV(l, 60)
    out = pd.DataFrame(index=df.index)
    out["多头排列"] = ((ma5 > ma10) & (ma10 > ma20) & (ma20 > ma60)).astype(int)
    out["空头排列"] = ((ma5 < ma10) & (ma10 < ma20) & (ma20 < ma60)).astype(int)
    out["趋势多头"] = ((c > ma20) & (ma20 > ma60)).astype(int)
    out["趋势空头"] = ((c < ma20) & (ma20 < ma60)).astype(int)
    out["上升中回调"] = ((c > ma60) & (c < ma20)).astype(int)
    out["突破前高"] = (c > hhv60.shift(1)).astype(int)
    out["距60日高点"] = c / (hhv60 + 1e-9)
    out["距60日低点"] = c / (llv60 + 1e-9)
    # 斐波均线
    fib_ma = {n: MA(c, n) for n in FIB}
    for n in FIB:
        out[f"站上MA{n}"] = (c > fib_ma[n]).astype(int)
    out["斐波短中多头"] = ((fib_ma[5] > fib_ma[13]) & (fib_ma[13] > fib_ma[34]) & (fib_ma[34] > fib_ma[55])).astype(int)
    out["斐波长多头"] = ((fib_ma[55] > fib_ma[89]) & (fib_ma[89] > fib_ma[144]) & (fib_ma[144] > fib_ma[233])).astype(int)
    out["斐波全多头"] = (out["斐波短中多头"].astype(bool) & out["斐波长多头"].astype(bool)).astype(int)
    out["MA55上穿MA89"] = CROSS(fib_ma[55], fib_ma[89]).astype(int)
    return out


# ===================================================================
# B. 成交量类
# ===================================================================
def volume_features(df):
    c, v = df["Close"], df["Volume"]
    vma5, vma20 = MA(v, 5), MA(v, 20)
    量比 = v / (MA(v, 5).shift(1) + 1e-9)
    price_up = c > c.shift(1)
    放量 = (v > vma5) & (v > vma20)
    out = pd.DataFrame(index=df.index)
    out["放量"] = 放量.astype(int)
    out["缩量"] = ((v < vma5) & (v < vma20)).astype(int)
    out["量比"] = 量比
    out["量比大于1"] = (量比 > 1).astype(int)
    out["量比大于1_3"] = (量比 > 1.3).astype(int)
    out["量比大于2"] = (量比 > 2).astype(int)
    out["量能递增"] = (vma5 > vma20).astype(int)
    out["价涨量增"] = (price_up & 放量).astype(int)
    out["价涨量缩"] = (price_up & (v < vma5)).astype(int)
    return out


# ===================================================================
# D. 经典技术指标 MACD / BOLL / KDJ / RSI
# ===================================================================
def classic_indicators(df):
    c, h, l = df["Close"], df["High"], df["Low"]
    lc = c.shift(1)
    out = pd.DataFrame(index=df.index)
    # MACD(12,26,9)
    dif = EMA(c, 12) - EMA(c, 26)
    dea = EMA(dif, 9)
    bar = dif - dea
    out["MACD_DIF大于0"] = (dif > 0).astype(int)
    out["MACD金叉态"] = (dif > dea).astype(int)
    out["MACD柱递增"] = ((bar > bar.shift(1)) & (bar.shift(1) > bar.shift(2))).astype(int)
    out["MACD零轴上金叉"] = (CROSS(dif, dea) & (dif > 0)).astype(int)
    out["MACD底背离"] = ((c < LLV(c, 20).shift(1)) & (bar > LLV(bar, 20).shift(1))).astype(int)
    # BOLL(20,2)
    mid = MA(c, 20)
    std = STD(c, 20)
    up, dn = mid + 2 * std, mid - 2 * std
    width = (up - dn) / (mid + 1e-9)
    out["BOLL收上中轨"] = (c > mid).astype(int)
    out["BOLL突破上轨"] = (c > up).astype(int)
    out["BOLL触下轨反弹"] = ((l <= dn) & (c > dn)).astype(int)
    out["BOLL开口扩张"] = (width > width.shift(1)).astype(int)
    # KDJ(9,3,3)
    rsv = (c - LLV(l, 9)) / (HHV(h, 9) - LLV(l, 9) + 1e-9) * 100
    k = SMA(rsv, 3, 1)
    d = SMA(k, 3, 1)
    j = 3 * k - 2 * d
    out["KDJ金叉态"] = (k > d).astype(int)
    out["KDJ_J超卖"] = (j < 20).astype(int)
    out["KDJ低位金叉"] = (CROSS(k, d) & (k < 30)).astype(int)
    out["KDJ_D小于30"] = (d < 30).astype(int)
    # RSI(6,13)
    up_move = (c - lc).clip(lower=0)
    abs_move = (c - lc).abs()
    rsi6 = SMA(up_move, 6, 1) / (SMA(abs_move, 6, 1) + 1e-9) * 100
    rsi13 = SMA(up_move, 13, 1) / (SMA(abs_move, 13, 1) + 1e-9) * 100
    out["RSI6大于50"] = (rsi6 > 50).astype(int)
    out["RSI金叉"] = CROSS(rsi6, rsi13).astype(int)
    out["RSI6超卖"] = (rsi6 < 30).astype(int)
    out["RSI底背离"] = ((c < LLV(c, 20).shift(1)) & (rsi6 > LLV(rsi6, 20).shift(1))).astype(int)
    return out


# ===================================================================
# D(威科夫量价) + E(威科夫B1/B3、中枢) —— 移植自 强信号共振选股V5 内联段
#   注：CAPITAL(流通股本)本地无 → 换手率相关用近似/略过，黄金柱去掉换手率档。
# ===================================================================
def wyckoff_features(df):
    o, c, h, l, v = df["Open"], df["Close"], df["High"], df["Low"], df["Volume"]
    lc = c.shift(1)
    out = pd.DataFrame(index=df.index)
    # 自适应周期(简化用固定N=20,M=60与内联默认一致量级)
    当前波幅 = MA(TR(df) / c * 100, 10)
    长期波幅 = MA(TR(df) / c * 100, 60)
    适应系数 = (当前波幅 / (长期波幅 + 1e-9)).clip(0.7, 1.5)
    N = np.maximum((20 * 适应系数).astype("float").round().fillna(20), 10).astype(int)
    Nc = 20  # 评分类用常数N，避免变长窗口；与内联默认同量级
    涨停幅度 = 0.1
    涨停 = (c >= lc * (1 + 涨停幅度) * 0.99) & (c > lc)
    跌停 = (c <= lc * (1 - 涨停幅度) * 1.01) & (c < lc)
    量缩显著 = v < MA(v, 20) * 0.8
    修正量 = np.where(涨停 & 量缩显著, v * 2, np.where(跌停 & 量缩显著, v * 0.5, v))
    修正量 = pd.Series(修正量, index=df.index)
    VOL_MA_S, VOL_MA_L = MA(修正量, 5), MA(修正量, 20)
    放量 = (修正量 > VOL_MA_S) & (修正量 > VOL_MA_L)
    量比 = 修正量 / (MA(修正量, 5).shift(1) + 1e-9)
    价涨, 价跌 = c > lc, c < lc
    振幅 = (h - l) / (lc + 1e-9) * 100
    多方占比 = (c - l) / (h - l + 1e-9)
    空方占比 = (h - c) / (h - l + 1e-9)
    强势上攻 = (价涨 & 放量) | 涨停
    净资金流 = (多方占比 - 空方占比) * 修正量
    净资金累计 = SUM(净资金流, Nc) / 10000
    净资金均线 = MA(净资金累计, Nc)
    MA20, MA60, MA120 = MA(c, 20), MA(c, 60), MA(c, 120)
    # 威科夫得分
    趋势总分 = (np.sign((MA(c, 5) - MA20)) + np.sign(MA20 - MA60) + np.sign(MA60 - MA120))
    区间高, 区间低 = HHV(h, Nc), LLV(l, Nc)
    波动率R = (区间高 - 区间低) / (区间低 + 1e-9) * 100
    平均波动 = MA(波动率R, 60)
    波动分 = np.where(波动率R < 平均波动 * 0.7, 2, np.where(波动率R < 平均波动, 1, 0))
    量缩程度 = VOL_MA_S / (VOL_MA_L + 1e-9)
    量能分 = np.where(量缩程度 > 1.3, 2, np.where(量缩程度 > 1.0, 1, np.where(量缩程度 < 0.7, -2, np.where(量缩程度 < 1.0, -1, 0))))
    资金分 = np.where((净资金累计 > 净资金均线) & (净资金累计 > 0), 2,
                   np.where(净资金累计 > 净资金均线, 1,
                   np.where((净资金累计 < 净资金均线) & (净资金累计 < 0), -2,
                   np.where(净资金累计 < 净资金均线, -1, 0))))
    价格位置 = (c - 区间低) / (区间高 - 区间低 + 1e-9)
    位置分 = np.where(价格位置 > 0.7, 1, np.where(价格位置 < 0.3, -1, 0))
    威科夫得分 = pd.Series(趋势总分 * 2 + 波动分 + 量能分 + 资金分 + 位置分, index=df.index)
    out["威科夫得分大于4"] = (威科夫得分 >= 4).astype(int)
    out["威科夫得分大于7"] = (威科夫得分 >= 7).astype(int)
    积累阶段 = (威科夫得分 >= -4) & (威科夫得分 <= 0) & (波动分 >= 1) & (c < MA60)
    out["积累阶段"] = 积累阶段.astype(int)
    # 弹簧 B3
    积累SC = 价跌 & (量比 > 2) & (振幅 > MA(振幅, Nc) + STD(振幅, Nc)) & (c < MA60)
    距SC = barslast(积累SC)
    SC有效 = 距SC < 999
    N日支撑, N日阻力 = LLV(l, Nc), HHV(h, Nc)
    跌破支撑 = l < N日支撑.shift(1)
    收回支撑 = c > N日支撑.shift(1)
    下影线长 = (c - l) / (h - l + 1e-9) > 0.6
    弹簧原始 = 跌破支撑 & 收回支撑 & 下影线长 & (量比 < 1.5) & (~跌停) & (多方占比 > 0.5)
    弹簧在积累 = SC有效 & (距SC >= 3) & (距SC <= 30) & (积累阶段 | 积累阶段.shift(1).fillna(False) | 积累阶段.shift(2).fillna(False))
    out["威科夫B3弹簧"] = (弹簧原始 & 弹簧在积累).astype(int)
    # 突破 B1
    B1原始 = 积累阶段.shift(1).fillna(False) & 强势上攻 & (c > N日阻力.shift(1))
    out["威科夫B1突破"] = B1原始.astype(int)
    # 黄金柱(去换手率档) + 量能金叉
    倍量 = (v >= v.shift(1) * 2) & (v < v.shift(1) * 3)
    价稳均线 = (c > MA(c, 5)) & (c > MA(c, 10))
    均线粘合 = (MA(c, 5) - MA(c, 10)).abs() / (MA(c, 10) + 1e-9) < 0.01
    真一字板 = 涨停 & (h == l)
    黄金柱 = 倍量 & 价稳均线 & 均线粘合 & (~真一字板)
    out["黄金柱"] = 黄金柱.astype(int)
    out["妖股启动"] = ((COUNT(黄金柱, 3) == 3) & (c > c.shift(1)) & (c.shift(1) > c.shift(2))).astype(int)
    out["量能金叉"] = CROSS(MA(v, 5), MA(v, 60)).astype(int)
    # 中枢(缠论式)上方
    ZS_N = 34
    ZS_U, ZS_D = LLV(h, ZS_N), HHV(l, ZS_N)
    out["中枢上方"] = ((ZS_U > ZS_D) & (c > ZS_U)).astype(int)
    return out


# ===================================================================
# F. 六脉神剑（移植内联六脉，红灯数）
# ===================================================================
def liumai_features(df):
    c, h, l = df["Close"], df["High"], df["Low"]
    lc = c.shift(1)
    out = pd.DataFrame(index=df.index)
    LM_DIFF = EMA(c, 8) - EMA(c, 13)
    LM_DEA = EMA(LM_DIFF, 5)
    MACD多 = LM_DIFF > LM_DEA
    LM_RSV = (c - LLV(l, 8)) / (HHV(h, 8) - LLV(l, 8) + 1e-9) * 100
    LM_K = SMA(LM_RSV, 3, 1)
    LM_D = SMA(LM_K, 3, 1)
    KDJ多 = LM_K > LM_D
    RSI短 = SMA((c - lc).clip(lower=0), 5, 1) / (SMA((c - lc).abs(), 5, 1) + 1e-9) * 100
    RSI长 = SMA((c - lc).clip(lower=0), 13, 1) / (SMA((c - lc).abs(), 13, 1) + 1e-9) * 100
    RSI多 = RSI短 > RSI长
    LWR原 = (-(HHV(h, 13) - c)) / (HHV(h, 13) - LLV(l, 13) + 1e-9) * 100
    LWR_K = SMA(LWR原, 3, 1)
    LWR_D = SMA(LWR_K, 3, 1)
    LWR多 = LWR_K > LWR_D
    BBI = (MA(c, 3) + MA(c, 6) + MA(c, 12) + MA(c, 24)) / 4
    BBI多 = c > BBI
    MTM_S = 100 * EMA(EMA(c - lc, 5), 3) / (EMA(EMA((c - lc).abs(), 5), 3) + 1e-9)
    MTM_L = 100 * EMA(EMA(c - lc, 13), 8) / (EMA(EMA((c - lc).abs(), 13), 8) + 1e-9)
    MTM多 = MTM_S > MTM_L
    红灯 = (MACD多.astype(int) + KDJ多.astype(int) + RSI多.astype(int) +
            LWR多.astype(int) + BBI多.astype(int) + MTM多.astype(int))
    六红 = 红灯 >= 6
    五红 = 红灯 >= 5
    out["六脉红灯大于5"] = 五红.astype(int)
    out["六脉红灯大于6"] = 六红.astype(int)
    out["六脉6红首发"] = (六红 & (~六红.shift(1).fillna(False))).astype(int)
    out["六脉5红首发"] = (五红 & (~五红.shift(1).fillna(False))).astype(int)
    return out


# ===================================================================
# C. 市场环境类（大盘 + 相对强弱 + 多周期共振）
# ===================================================================
def index_state(idx_df):
    p = idx_df["Close"]
    ma20, ma60 = MA(p, 20), MA(p, 60)
    chg5 = (p - p.shift(5)) / (p.shift(5) + 1e-9) * 100
    chg60 = (p - p.shift(60)) / (p.shift(60) + 1e-9) * 100
    多头 = (p > ma20) & (ma20 > ma60)
    空头 = (p < ma20) & (ma20 < ma60)
    危险 = (p < ma60) & (chg60 < -10)
    state = np.where(危险, 4, np.where(空头, 3, np.where(多头, 1, 2)))
    out = pd.DataFrame(index=idx_df.index)
    out["大盘状态ID"] = state.astype(int)
    out["大盘多头"] = 多头.astype(int)
    out["大盘空头"] = 空头.astype(int)
    out["大盘安全"] = (p > ma20).astype(int)
    out["SID等于1"] = (state == 1).astype(int)
    out["SID等于2"] = (state == 2).astype(int)
    out["SID小于等于2"] = (state <= 2).astype(int)
    out["大盘5日上涨"] = (chg5 > 0).astype(int)
    out["_盘价"] = p
    return out


def relative_strength(stock_close, index_close):
    s10 = (stock_close - stock_close.shift(10)) / (stock_close.shift(10) + 1e-9) * 100
    i10 = (index_close - index_close.shift(10)) / (index_close.shift(10) + 1e-9) * 100
    rs = (1 + s10 / 100) / (1 + i10 / 100 + 1e-9) * 100 - 100
    out = pd.DataFrame(index=stock_close.index)
    out["相对强弱"] = rs
    out["相对强弱大于0"] = (rs > 0).astype(int)
    out["相对强弱大于5"] = (rs > 5).astype(int)
    return out


def multiperiod_resonance(df):
    # 移植自 04_短线打板体系/多时间框架V8.txt（纯OHLCV，无未来函数）。
    c = df["Close"]
    MA20_V, MA60_V = MA(c, 20), MA(c, 60)
    月线方向 = np.sign(MA20_V - MA20_V.shift(5))
    季线方向 = np.sign(MA60_V - MA60_V.shift(10))
    半年方向 = np.sign(MA(c, 120) - MA(c, 120).shift(20))
    s = (月线方向 + 季线方向 + 半年方向)
    多头共振 = (月线方向 == 1) & (季线方向 == 1) & (半年方向 == 1)
    空头共振 = (月线方向 == -1) & (季线方向 == -1) & (半年方向 == -1)
    out = pd.DataFrame(index=df.index)
    out["偏多共振"] = (s >= 2).astype(int)
    out["多头共振"] = 多头共振.astype(int)
    # V8 新增：做多权重(连续 -3..3)、空头共振、带15根冷却的多/空首发
    out["做多权重"] = s.astype(float)
    out["空头共振"] = 空头共振.astype(int)
    out["多头首发"] = _resonance_first(多头共振).astype(int)
    out["空头首发"] = _resonance_first(空头共振).astype(int)
    return out


def _resonance_first(state):
    """共振首发 + 15根冷却：复刻 V8 的 BARSLAST(REF(首发原,1))>=15 去抖。
    state: 布尔Series(多头/空头共振)。首发原=今真昨假；距上次=与上一个'首发原'位置的间隔，
    <15根的后续首发被抑制(沿用 events_export 冷却思想，但口径=对上一个raw首发计距)。"""
    raw = (state & ~state.shift(1, fill_value=False)).to_numpy()
    idx = np.arange(len(raw), dtype=float)
    last_pos = np.where(raw, idx, np.nan)
    prev = pd.Series(last_pos).shift(1).ffill().to_numpy()  # 严格早于当前的最近raw位置
    dist = idx - prev  # 无前者时为NaN
    keep = raw & (np.isnan(dist) | (dist >= 15))
    return pd.Series(keep, index=state.index)


# ===================================================================
# E. 通达信扩展信号（移植自各指标源文件；只算原始形态，不含大盘门槛）
#    数据缺失说明：CAPITAL/FINANCE/WINNER 本地无 → 相关子门槛(换手/市值/筹码)略去；
#    尖刺(WINNER)整体不可移植，已跳过。摇钱树三重底用简化代理。
# ===================================================================
def tdx_extra_features(df, code=None):
    o, c, h, l, v = df["Open"], df["Close"], df["High"], df["Low"], df["Volume"]
    lc = c.shift(1)
    p = 0.2 if (code and str(code)[:3] in ("300", "301")) else 0.1
    out = pd.DataFrame(index=df.index)
    涨停 = (c >= lc * (1 + p) * 0.99) & (c > lc)
    跌停 = (c <= lc * (1 - p) * 1.01) & (c < lc)
    真一字 = 涨停 & (h == l)
    非一字涨停 = 涨停 & (~真一字)
    阳线, 阴线, 价跌 = c > o, c < o, c < lc
    多方占比 = (c - l) / (h - l + 1e-9)
    放量 = (v > v.shift(1)) & (v > MA(v, 5))
    # ---- 火箭 ----
    二连板 = 非一字涨停 & 涨停.shift(1).fillna(False)
    三连板 = 二连板 & 涨停.shift(2).fillna(False)
    一板 = 非一字涨停 & (c.shift(1) < c.shift(2) * (1 + p) * 0.99)  # 去FINANCE门槛
    A1 = EMA(c, 14); A1X = (A1 - A1.shift(1)) / (A1.shift(1) + 1e-9) * 100
    ZJ_K = EMA(c, 2); 快 = EMA(EMA(ZJ_K, 2), 3); 慢 = EMA(EMA(EMA(EMA(ZJ_K, 2), 2), 2), 7)
    火箭 = (一板 | 二连板 | 三连板 |
            (CROSS(A1X, pd.Series(0, index=df.index)) & (c >= HHV(h, 7).shift(1)) &
             非一字涨停 & CROSS(快, 慢) & (c >= 快) & (c > o)))
    out["火箭信号"] = 火箭.astype(int)
    out["二连板"] = 二连板.astype(int)
    # ---- 回马枪 ----
    距涨停 = barslast(非一字涨停)
    有涨停史 = 距涨停 < 999
    涨停价 = c.where(非一字涨停).ffill()
    回调幅度 = (涨停价 - c) / (涨停价 + 1e-9) * 100
    回调中 = 有涨停史 & (距涨停 >= 3) & (距涨停 <= 10) & (c < 涨停价 * 0.95)
    合理回调 = (回调幅度 >= 3) & (回调幅度 <= 12)
    起攻 = 阳线 & (v > v.shift(1) * 1.3) & (c > h.shift(1)) & 回调中 & 合理回调
    out["回马枪"] = 起攻.astype(int)
    out["二次涨停"] = (非一字涨停 & 有涨停史 & (距涨停 >= 3) & (距涨停 <= 15)).astype(int)
    # ---- 纳财 ----
    阴阳1 = (阳线 & 阴线.shift(1).fillna(False)) | (阴线 & 阳线.shift(1).fillna(False))
    阴阳2 = (阳线.shift(1).fillna(False) & 阴线.shift(2).fillna(False)) | (阴线.shift(1).fillna(False) & 阳线.shift(2).fillna(False))
    震荡结构 = 阴阳1 & 阴阳2
    位置抬升 = LLV(l, 3) > LLV(l, 3).shift(3)
    宝盆 = 震荡结构 & 位置抬升
    out["纳财"] = (宝盆 & (c > HHV(h, 5).shift(1)) & 放量).astype(int)
    # ---- 极限抄底（去套牢盘）----
    跌幅20 = (c - HHV(c, 20)) / (HHV(c, 20) + 1e-9) * 100
    跌幅60 = (c - HHV(c, 60)) / (HHV(c, 60) + 1e-9) * 100
    极限跌 = (跌幅20 <= -15) | (跌幅60 <= -25)
    RSI6 = SMA((c - lc).clip(lower=0), 6, 1) / (SMA((c - lc).abs(), 6, 1) + 1e-9) * 100
    RSI超跌 = RSI6 <= 20
    下影长 = (c - l) / (h - l + 1e-9) > 0.5
    止跌K = (阳线 & 下影长) | ((多方占比 > 0.7) & (~跌停))
    缩量企稳 = (v < MA(v, 5) * 0.7) & (~价跌)
    out["极限抄底"] = (极限跌 & RSI超跌 & (止跌K | 缩量企稳)).astype(int)
    # ---- 中枢位置V10 ----
    HH, LL = HHV(h, 34), LLV(l, 34)
    ZS = (c - LL) / (HH - LL + 1e-9) * 100
    out["中枢进机会区"] = ((ZS < 15) & (ZS.shift(1) >= 15)).astype(int)
    out["中枢极限底"] = ((ZS < 5) & (ZS.shift(1) >= 5)).astype(int)
    out["中枢上穿中轴"] = ((ZS > 50) & (ZS.shift(1) <= 50)).astype(int)
    out["中枢底部蓄力"] = ((COUNT(ZS < 20, 5) >= 3) & (ZS > ZS.shift(1))).astype(int)
    out["中枢底部回升"] = ((ZS.shift(2) < 20) & (ZS > ZS.shift(1)) & (ZS > ZS.shift(2))).astype(int)
    # ---- 摇钱树（金叉点+KDJ底精确，三重底用代理）----
    EMA5, EMA10 = EMA(c, 5), EMA(c, 10)
    斜率 = (EMA5 - EMA5.shift(3)) / (EMA5.shift(3) + 1e-9) * 100
    金叉点 = (斜率 > 0) & (斜率.shift(1) <= 0) & CROSS(EMA5, EMA10) & (c.shift(1) > c.shift(2) * 1.025) & (c < c.shift(1))
    VARA = (c - LLV(l, 9)) / (HHV(h, 9) - LLV(l, 9) + 1e-9) * 100
    KLD = SMA(VARA, 3, 1); VARB = SMA(KLD, 3, 1); JLD = 3 * KLD - 2 * VARB
    VAR1 = SMA((c - LLV(l, 5)) / (HHV(h, 5) - LLV(l, 5) + 1e-9) * 100, 5, 1)
    VAR2 = 4 * VAR1 - 3 * SMA(VAR1, 3.2, 1)
    KDJ底 = CROSS(VAR2, pd.Series(8.0, index=df.index)) | CROSS(JLD, pd.Series(1.0, index=df.index))
    底代理 = (l == LLV(l, 20))  # 简化三重底：近20日新低
    out["摇钱树"] = ((COUNT(底代理, 5) >= 1) & (COUNT(金叉点, 5) >= 1) & (COUNT(KDJ底, 5) >= 1)).astype(int)
    # ---- 主力启动（去换手率）----
    振幅 = (h - l) / (lc + 1e-9) * 100
    净资金流 = (多方占比 - (h - c) / (h - l + 1e-9)) * v
    主力参与 = (振幅 > MA(振幅, 20) + STD(振幅, 20)) & 放量
    主力累计 = SUM(净资金流.where(主力参与, 0), 20) / 10000
    主力强度 = 主力累计 / (SUM(净资金流.abs(), 20) + 1e-9) * 100
    MA5, MA10, MA20, MA60 = MA(c, 5), MA(c, 10), MA(c, 20), MA(c, 60)
    均线多头 = (MA5 > MA10) & (MA10 > MA20) & (c > MA5) & (MA20 >= MA20.shift(3))
    主力流入 = (主力累计 > 主力累计.shift(5)) & (主力强度 > 15)
    当日涨 = (c - lc) / (lc + 1e-9) * 100
    涨幅合理 = (当日涨 <= 6) & ((c - LLV(c, 60)) / (LLV(c, 60) + 1e-9) * 100 < 60)
    out["主力启动"] = (均线多头 & 主力流入 & (COUNT(主力参与, 5) >= 1) & 涨幅合理).astype(int)
    # ---- 超短打板（去换手/市值/尖刺）----
    量比 = v / (MA(v, 5).shift(1) + 1e-9)
    超短均线多头 = (MA5 > MA10) & (MA10 > MA20) & (c > MA5)
    out["超短打板"] = ((当日涨 >= 3) & (当日涨 <= 5) & (量比 > 1.5) & 超短均线多头 &
                     放量 & (out["摇钱树"].astype(bool))).astype(int)
    return out


# ===================================================================
# 庄散（买卖点.txt 移植）：吸筹/庄家/散户 + 买1/买2/卖1/卖2
# ===================================================================
def zhuangsan_features(df):
    c, h, l = df["Close"], df["High"], df["Low"]
    out = pd.DataFrame(index=df.index)
    # 散户线
    sanhu = 100 * (HHV(h, 55) - c) / (HHV(h, 55) - LLV(l, 55) + 1e-9)
    # 庄家线 = EMA(KDJ-J, 6)
    rsv = (c - LLV(l, 34)) / (HHV(h, 34) - LLV(l, 34) + 1e-9) * 100
    k = SMA(rsv, 3, 1); d = SMA(k, 3, 1); j = 3 * k - 2 * d
    zhuang = EMA(j, 6)
    # 吸筹（化简 VAR1≡1, VAR7≡1）
    lref = l.shift(1)
    var3 = SMA((l - lref).abs(), 3, 1) / (SMA((l - lref).clip(lower=0), 3, 1) + 1e-9) * 100
    var4 = EMA(var3 * 10, 3)                      # CLOSE*1.3 恒真分支
    var5 = LLV(l, 30); var6 = HHV(var4, 30)
    raw = EMA(((var4 + var6 * 2) / 2).where(l <= var5, 0.0), 3) / 618
    xichou = raw.clip(upper=100)
    out["吸筹值"] = xichou
    out["庄家线"] = zhuang
    out["散户线"] = sanhu
    out["庄散买1"] = CROSS(pd.Series(14.0, index=df.index), xichou).astype(int)
    out["庄散买2"] = (CROSS(zhuang, sanhu) & (zhuang < 50)).astype(int)
    out["庄散卖1"] = CROSS(pd.Series(88.0, index=df.index), zhuang).astype(int)
    out["庄散卖2"] = CROSS(sanhu, zhuang).astype(int)
    return out


# ===================================================================
# G. 六脉神剑齐红/齐绿首发信号
# ===================================================================
def liumai_signal_features(df):
    c, h, l = df["Close"], df["High"], df["Low"]
    lc = c.shift(1)
    macd = EMA(c, 8) - EMA(c, 13);  x1 = macd > EMA(macd, 5)
    rsv = (c - LLV(l, 8)) / (HHV(h, 8) - LLV(l, 8) + 1e-9) * 100
    kk = SMA(rsv, 3, 1);  x2 = kk > SMA(kk, 3, 1)
    r1 = SMA((c - lc).clip(lower=0), 5, 1) / (SMA((c - lc).abs(), 5, 1) + 1e-9) * 100
    r2 = SMA((c - lc).clip(lower=0), 13, 1) / (SMA((c - lc).abs(), 13, 1) + 1e-9) * 100
    x3 = r1 > r2
    lwr = (-(HHV(h, 13) - c)) / (HHV(h, 13) - LLV(l, 13) + 1e-9) * 100
    lw = SMA(lwr, 3, 1);  x4 = lw > SMA(lw, 3, 1)
    bbi = (MA(c, 3) + MA(c, 6) + MA(c, 12) + MA(c, 24)) / 4;  x5 = c > bbi
    dc = c - lc
    m1 = 100 * EMA(EMA(dc, 5), 3) / (EMA(EMA(dc.abs(), 5), 3) + 1e-9)
    m2 = 100 * EMA(EMA(dc, 13), 8) / (EMA(EMA(dc.abs(), 13), 8) + 1e-9)
    x6 = m1 > m2
    allred = x1 & x2 & x3 & x4 & x5 & x6
    allgreen = (~x1) & (~x2) & (~x3) & (~x4) & (~x5) & (~x6)
    out = pd.DataFrame(index=df.index)
    # 首发去抖：要求转入该状态前连续5根都不在该状态(真正的状态转换,过滤微抖反复触发)
    red_prev5 = allred.shift(1).fillna(False).rolling(5, min_periods=1).sum()
    green_prev5 = allgreen.shift(1).fillna(False).rolling(5, min_periods=1).sum()
    out["六脉齐红首发"] = (allred & (red_prev5 == 0)).astype(int)
    out["六脉齐绿首发"] = (allgreen & (green_prev5 == 0)).astype(int)
    out["六脉红灯数"] = (x1.astype(int)+x2.astype(int)+x3.astype(int)+x4.astype(int)+x5.astype(int)+x6.astype(int))
    return out


# ===================================================================
# 资金流向（资金移动V5 / 日资金主图V5 移植，仅OHLCV+成交额可算部分）
# ===================================================================
def capitalflow_features(df):
    c, h, l, v = df["Close"], df["High"], df["Low"], df["Volume"]
    out = pd.DataFrame(index=df.index)
    rng = (h - l) + 1e-9
    多方占比 = (c - l) / rng
    空方占比 = (h - c) / rng
    # 涨跌停/修正量(自适应)
    涨停幅度 = 0.10  # 简化:主板10%(科创/创业板20%此处不细分,影响极小)
    涨停 = (c >= REF(c, 1) * (1 + 涨停幅度) * 0.99) & (c > REF(c, 1))
    跌停 = (c <= REF(c, 1) * (1 - 涨停幅度) * 1.01) & (c < REF(c, 1))
    真一字板 = 涨停 & (h == l)
    VL = 20
    量缩显著 = v < MA(v, VL) * 0.8
    修正量 = v.where(~(涨停 & 量缩显著), v * 2)
    修正量 = 修正量.where(~(跌停 & 量缩显著), v * 0.5)
    修正量 = 修正量.where(~真一字板, v)
    放量 = (修正量 > MA(修正量, 5)) & (修正量 > MA(修正量, 20))
    振幅 = (h - l) / (REF(c, 1) + 1e-9) * 100
    净资金流 = (多方占比 - 空方占比) * 修正量
    N = 20
    大单阈值 = MA(振幅, N) + STD(振幅, N)
    主力参与 = (振幅 > 大单阈值) & 放量
    主力净方向 = 净资金流.where(主力参与, 0.0)
    主力累计 = SUM(主力净方向, N) / 10000
    流动规模 = SUM(净资金流.abs(), N) + 1e-9
    主力强度 = 主力累计 / 流动规模 * 100
    # 资金短/中线金叉死叉(带10根冷却,简化为CROSS+方向)
    osc = 修正量 * (2 * (c - l) / rng - 1)
    DIF短 = EMA(osc, 5); DIF长 = EMA(osc, 20)
    资金金叉 = CROSS(DIF短, DIF长) & (DIF长 < 0)
    资金死叉 = CROSS(DIF长, DIF短) & (DIF长 > 0)
    # 机构进出(成交额V*C, 大单>20万判定, 滚动240日)
    成交额 = v * c / 100
    大单 = 成交额 / 8 > 20
    涨 = c > REF(c, 1)
    机构买 = SUM(成交额.where(大单 & 涨, 0.0), 240)
    机构卖 = SUM(成交额.where(大单 & ~涨, 0.0), 240)
    资金强度 = (机构买 - 机构卖) / (机构买 + 机构卖 + 1e-9) * 100
    # 输出
    out["主力强度"] = 主力强度
    out["资金强度"] = 资金强度
    out["主力参与"] = 主力参与.astype(int)
    out["资金金叉"] = 资金金叉.astype(int)
    out["资金死叉"] = 资金死叉.astype(int)
    out["主力净流入"] = (主力强度 > 0).astype(int)
    out["机构净买"] = (资金强度 > 0).astype(int)
    return out


# ===================================================================
# Phase E 批次2：波动率/市场环境类
#   来源：核心_波动V3.txt / 波动率风险管理V4.txt（纯OHLCV可算部分）
#   跳过：市场温度计依赖 INDEXC/INDEXV(大盘价量,本函数无大盘数据)
#          多头共振/偏多共振已在 multiperiod_resonance 输出
#          ATR_K/动态止损幅 为止损参数，非买点特征
# ===================================================================
def volatility_env_features(df):
    """
    波动率/市场环境特征。
    连续量：波动率、波动率百分位、波动档(1=低/2=中/3=高)、MA20斜率
    布尔量：低波动、高波动、趋势加速、缩量企稳
    """
    c, h, l, v = df["Close"], df["High"], df["Low"], df["Volume"]
    out = pd.DataFrame(index=df.index)

    # ---------- ATR(14) ----------
    # TR(df) 已封装真实波幅
    atr = MA(TR(df), 14)

    # ---------- 波动率 = ATR/Close*100 ----------
    # 核心_波动V3: 波动率:ATR值/(CLOSE+0.0001)*100
    波动率 = atr / (c + 1e-4) * 100
    out["波动率"] = 波动率

    # ---------- 波动率百分位 (120日滚动) ----------
    # 核心_波动V3: 波动低于今日:COUNT(REF(波动率,1)<=波动率,120)
    #              波动率百分位:波动低于今日/120*100
    波动低于今日 = COUNT(REF(波动率, 1) <= 波动率, 120)
    波动率百分位 = 波动低于今日 / 120 * 100
    out["波动率百分位"] = 波动率百分位

    # ---------- 波动率分档（布尔） ----------
    # 核心_波动V3: 低波:<30 / 高波:>70
    低波 = 波动率百分位 < 30
    高波 = 波动率百分位 > 70
    out["低波动"] = 低波.astype(int)
    out["高波动"] = 高波.astype(int)

    # ---------- 波动档编号（连续量 1/2/3）----------
    # 核心_波动V3: IF(低波,1,IF(高波,3,2))
    波动档 = np.where(低波, 1, np.where(高波, 3, 2)).astype(float)
    # 波动率百分位有NaN时（数据不足120根），档位也为NaN
    波动档 = pd.Series(波动档, index=df.index).where(波动率百分位.notna())
    out["波动档"] = 波动档

    # ---------- MA20斜率（连续量）----------
    # 核心_波动V3: MA20斜率:(MA20_V-REF(MA20_V,5))/(REF(MA20_V,5)+0.0001)*100
    ma20 = MA(c, 20)
    ma20_ref5 = REF(ma20, 5)
    ma20斜率 = (ma20 - ma20_ref5) / (ma20_ref5 + 1e-4) * 100
    out["MA20斜率"] = ma20斜率

    # ---------- 趋势加速（布尔）----------
    # 核心_波动V3: MA20斜率>REF(MA20斜率,5) AND MA20斜率>0
    out["趋势加速"] = ((ma20斜率 > REF(ma20斜率, 5)) & (ma20斜率 > 0)).astype(int)

    # ---------- 缩量企稳（布尔）----------
    # 含义：成交量萎缩（低于5日均量）且价格不下跌 → 底部缩量止跌信号
    vma5 = MA(v, 5)
    out["缩量企稳"] = ((v < vma5) & (c >= c.shift(1).fillna(c))).astype(int)

    return out


# ===================================================================
# Phase E 批次3：威科夫扩展买点 B2/B4/B5/B6
#   来源：威科夫_主图V7.txt（B2/B4/B5/B6原始公式，纯OHLCV可算部分）
#   已移植：B1突破/B3弹簧/得分/积累阶段 → wyckoff_features，此处不重复
#   跳过项：
#     B4 中 筹码集中(WINNER函数,需逐笔成交数据) → 去掉该条件保留其余
#     买入允许 条件中 空头共振/盘危险 依赖大盘INDEXC → 跳过大盘过滤
# ===================================================================
def wyckoff_ext_features(df):
    """
    威科夫扩展买点特征（B2/B4/B5/B6），纯OHLCV可算。
    布尔量：威科夫B2回踩、威科夫B4强势杆、威科夫B5底背离、威科夫B6缺口突破
    """
    o, c, h, l, v = df["Open"], df["Close"], df["High"], df["Low"], df["Volume"]
    lc = c.shift(1)
    out = pd.DataFrame(index=df.index)

    # ---------- 公共中间量（与 wyckoff_features 保持一致的计算方式）----------
    涨停幅度 = 0.1
    涨停 = (c >= lc * (1 + 涨停幅度) * 0.99) & (c > lc)
    跌停 = (c <= lc * (1 - 涨停幅度) * 1.01) & (c < lc)
    量缩显著 = v < MA(v, 20) * 0.8
    修正量 = np.where(涨停 & 量缩显著, v * 2, np.where(跌停 & 量缩显著, v * 0.5, v))
    修正量 = pd.Series(修正量, index=df.index)
    VOL_MA_S = MA(修正量, 5)
    VOL_MA_L = MA(修正量, 20)
    放量 = (修正量 > VOL_MA_S) & (修正量 > VOL_MA_L)
    缩量 = (修正量 < VOL_MA_S) & (修正量 < VOL_MA_L)
    量比 = 修正量 / (MA(修正量, 5).shift(1) + 1e-9)
    价涨 = c > lc
    价跌 = c < lc
    振幅 = (h - l) / (lc + 1e-9) * 100
    多方占比 = (c - l) / (h - l + 1e-9)
    空方占比 = (h - c) / (h - l + 1e-9)
    强势上攻 = (价涨 & 放量) | 涨停

    Nc = 20
    净资金流 = (多方占比 - 空方占比) * 修正量
    净资金累计 = SUM(净资金流, Nc) / 10000
    净资金均线 = MA(净资金累计, Nc)
    MA20 = MA(c, 20)
    MA60 = MA(c, 60)

    # 威科夫得分（复算，用于判断上涨阶段/积累阶段）
    MA5 = MA(c, 5)
    MA120 = MA(c, 120)
    趋势总分 = (np.sign(MA5 - MA20) + np.sign(MA20 - MA60) + np.sign(MA60 - MA120))
    区间高 = HHV(h, Nc)
    区间低 = LLV(l, Nc)
    波动率R = (区间高 - 区间低) / (区间低 + 1e-9) * 100
    平均波动 = MA(波动率R, 60)
    波动分 = np.where(波动率R < 平均波动 * 0.7, 2, np.where(波动率R < 平均波动, 1, 0))
    量缩程度 = VOL_MA_S / (VOL_MA_L + 1e-9)
    量能分 = np.where(量缩程度 > 1.3, 2, np.where(量缩程度 > 1.0, 1,
                np.where(量缩程度 < 0.7, -2, np.where(量缩程度 < 1.0, -1, 0))))
    资金分 = np.where((净资金累计 > 净资金均线) & (净资金累计 > 0), 2,
                np.where(净资金累计 > 净资金均线, 1,
                np.where((净资金累计 < 净资金均线) & (净资金累计 < 0), -2,
                np.where(净资金累计 < 净资金均线, -1, 0))))
    价格位置 = (c - 区间低) / (区间高 - 区间低 + 1e-9)
    位置分 = np.where(价格位置 > 0.7, 1, np.where(价格位置 < 0.3, -1, 0))
    威科夫得分 = pd.Series(趋势总分 * 2 + 波动分 + 量能分 + 资金分 + 位置分, index=df.index)

    积累阶段 = (威科夫得分 >= -4) & (威科夫得分 <= 0) & (pd.Series(波动分, index=df.index) >= 1) & (c < MA60)
    上涨阶段 = 威科夫得分 >= 4

    # ---------- B2：回踩确认(LPS最后支撑点) ----------
    # 源：B2原始:=上涨阶段 AND LOW<=MA20*1.02 AND LOW>=MA20*0.98
    #           AND CLOSE>OPEN AND 净资金累计>净资金均线
    B2原始 = (上涨阶段 &
               (l <= MA20 * 1.02) & (l >= MA20 * 0.98) &
               (c > o) &
               (净资金累计 > 净资金均线))
    out["威科夫B2回踩"] = B2原始.astype(int)

    # ---------- B4：缩量后强势信号杆 ----------
    # 源：B4原始:=COUNT(缩量 AND 价跌,10)>=5 AND 强势上攻 AND 量比>1.5
    #           AND 主力累计>REF(主力累计,1) AND 筹码集中
    # 跳过：筹码集中(依赖WINNER,非纯OHLCV)
    大单阈值 = MA(振幅, Nc) + STD(振幅, Nc)
    主力参与 = (振幅 > 大单阈值) & 放量
    主力净方向 = 净资金流.where(主力参与, 0.0)
    主力累计 = SUM(主力净方向, Nc) / 10000
    B4原始 = (COUNT(缩量 & 价跌, 10) >= 5) & 强势上攻 & (量比 > 1.5) & (主力累计 > 主力累计.shift(1))
    out["威科夫B4强势杆"] = B4原始.astype(int)

    # ---------- B5：底背离回踩 ----------
    # 源：B5原始:=连续底背离 AND 价涨 AND CLOSE>REF(CLOSE,1) AND CLOSE<MA60
    # 底背离：量小+价跌幅小+价在MA20下
    量力度 = 修正量 / (MA(修正量, Nc) + 1e-9)
    价幅度 = (c - lc).abs() / (MA((c - lc).abs(), Nc) + 1e-9)
    量价效率 = 价幅度 / (量力度 + 1e-9)
    效率均值 = MA(量价效率, Nc)
    底背离 = ((修正量 < VOL_MA_L) & 价跌 & (~跌停) &
               ((c - lc).abs() < MA((c - lc).abs(), Nc) * 0.5) &
               (c < MA20))
    连续底背离 = COUNT(底背离, 5) >= 2
    B5原始 = 连续底背离 & 价涨 & (c > lc) & (c < MA60)
    out["威科夫B5底背离"] = B5原始.astype(int)

    # ---------- B6：突破缺口强势上攻 ----------
    # 源：突破缺口:=向上缺口 AND (积累阶段 OR REF(积累阶段,1))
    #      B6原始:=突破缺口 AND 强势上攻
    向上缺口 = l > h.shift(1)
    突破缺口 = 向上缺口 & (积累阶段 | 积累阶段.shift(1).fillna(False))
    B6原始 = 突破缺口 & 强势上攻
    out["威科夫B6缺口突破"] = B6原始.astype(int)

    return out


# ===================================================================
# I. 缠论结构类特征（Phase E 批次4）
# 源: MACD背驰V8.txt / 趋势评分V8.txt / 缠论Pro副图V6.txt
# 纯OHLCV可算；跳过 WINNER/CAPITAL/FINANCE/大盘指数依赖项
# ===================================================================
# 跳过项：
#   缠论Pro副图V6 中 市值条件:=FINANCE(40) → MA13/MA26自适应周期跳过，固定用13/26
#   缠论Pro副图V6 中 放量确认:=V>MA(V,5)*成交量倍数 → 成交量倍数未定义，用1.5代替
#   成交量倍数 参数已在原副图中作为全局参数，此处合理默认1.5
# ===================================================================
def chanlun_struct_features(df):
    """
    缠论结构类特征，纯OHLCV可算。
    布尔量：MACD底背驰/缠论底分型/缠论方向多/缠论一买/缠论二买/缠论V2过滤/缠论趋势强势/缠论评分大于65
    连续量：缠论趋势评分(0~100)/MACD背驰强度(负面积收缩率，值越小背驰越强)
    """
    o, c, h, l, v = df["Open"], df["Close"], df["High"], df["Low"], df["Volume"]
    lc = c.shift(1)
    out = pd.DataFrame(index=df.index)

    # ---- 公共: 合并K线（包含关系处理）----
    # TDX: DIR=上涨1/下跌-1/持平0; IS_CON=包含关系; CH/CL=合并后高低
    DIR = np.where(c > lc, 1, np.where(c < lc, -1, 0))
    DIR = pd.Series(DIR, index=df.index)
    IS_CON = ((h >= REF(h, 1)) & (l <= REF(l, 1))) | ((h <= REF(h, 1)) & (l >= REF(l, 1)))
    CH = pd.Series(np.where(IS_CON,
                             np.where(DIR >= 0, np.maximum(h, REF(h, 1)), np.minimum(h, REF(h, 1))),
                             h), index=df.index)
    CL = pd.Series(np.where(IS_CON,
                             np.where(DIR >= 0, np.maximum(l, REF(l, 1)), np.minimum(l, REF(l, 1))),
                             l), index=df.index)

    # ---- 公共: 顶底分型 ----
    # TDX: TOP_RAW = REF(CH,1)>REF(CH,2) AND REF(CH,1)>CH AND REF(CL,1)>REF(CL,2) AND REF(CL,1)>CL
    TOP_RAW = ((REF(CH, 1) > REF(CH, 2)) & (REF(CH, 1) > CH) &
               (REF(CL, 1) > REF(CL, 2)) & (REF(CL, 1) > CL))
    BOT_RAW = ((REF(CL, 1) < REF(CL, 2)) & (REF(CL, 1) < CL) &
               (REF(CH, 1) < REF(CH, 2)) & (REF(CH, 1) < CH))
    顶分型 = TOP_RAW & (barslast(REF(TOP_RAW, 1)) >= 4)
    底分型 = BOT_RAW & (barslast(REF(BOT_RAW, 1)) >= 4)

    out["缠论底分型"] = 底分型.astype(int)

    # ---- 公共: MACD ----
    DIF = EMA(c, 12) - EMA(c, 26)
    DEA = EMA(DIF, 9)
    MACD_BAR = 2 * (DIF - DEA)

    # ======================================================
    # 1. MACD底背驰（来自 MACD背驰V8.txt）
    #    底背驰原始: 底分型 AND 价创30日新低 AND 近10日负面积 < 前次底分型时负面积*0.8
    #    + 冷却期 >= 10
    # ======================================================
    CL_AREA = pd.Series(np.where(MACD_BAR < 0, MACD_BAR.abs(), 0), index=df.index)
    neg_area_10 = SUM(CL_AREA, 10)

    # 前一次底分型距离
    dist_bot = barslast(REF(底分型, 1))  # 距上一个底分型的bar数
    # 前一次底分型时的负面积（用 shift(dist_bot+1) 近似→逐行取）
    # 用 pandas apply 方式：对每个位置取 REF(neg_area_10, dist_bot+1)
    # 简化：用 barslast 给出偏移，矢量化实现
    dist_bot_int = dist_bot.fillna(9999).clip(0, len(df) - 1).astype(int)
    _dbi = dist_bot_int.to_numpy(); _na = neg_area_10.to_numpy(); _n = len(df)
    ref_neg_area = pd.Series(
        [_na[max(0, i - int(_dbi[i]) - 1)] if int(_dbi[i]) < 9999 else np.nan
         for i in range(_n)],
        index=df.index
    )

    底背驰原始 = 底分型 & (LLV(l, 30) == l) & (neg_area_10 < ref_neg_area * 0.8)
    dist_bot_div = barslast(REF(底背驰原始, 1))
    MACD底背驰 = 底背驰原始 & ((dist_bot_div >= 10) | (dist_bot_div >= 999))

    out["MACD底背驰"] = MACD底背驰.astype(int)

    # MACD背驰强度：当底背驰时，负面积收缩比率 = neg_area_10 / (ref_neg_area + 1e-9)
    # 值越小表示背驰越强（接近0=强背驰）；非底背驰时为0
    背驰强度原始 = (neg_area_10 / (ref_neg_area + 1e-9)).clip(0, 2)
    out["MACD背驰强度"] = pd.Series(
        np.where(MACD底背驰, 背驰强度原始, 0.0), index=df.index
    ).astype(float)

    # ======================================================
    # 2. 缠论趋势评分（来自 趋势评分V8.txt）
    #    缠论得分 = MIN(均线分 + 量能分 + MACD分 + 斜率分, 100)
    # ======================================================
    # 自适应成交量参数：适应系数基于当前/长期波幅之比
    # 简化：前N日NaN用 fillna(1.0) 处理，再取整得到稳定周期
    当前波幅 = MA(TR(df) / c * 100, 10)
    长期波幅 = MA(TR(df) / c * 100, 60)
    适应系数 = (当前波幅 / (长期波幅 + 1e-4)).clip(0.7, 1.5).fillna(1.0)
    vs_arr = np.maximum(np.floor(5 * 适应系数.to_numpy()).astype(int), 3)
    vl_arr = np.maximum(np.floor(20 * 适应系数.to_numpy()).astype(int), 10)
    # 取序列众数作为固定周期（避免逐行不同长度rolling）
    import statistics
    vs_val = max(int(statistics.mode(vs_arr)), 3)
    vl_val = max(int(statistics.mode(vl_arr)), 10)
    VOL_MA_S_t = MA(v, vs_val)
    VOL_MA_L_t = MA(v, vl_val)
    量缩程度_t = VOL_MA_S_t / (VOL_MA_L_t + 1e-9)
    量能分 = pd.Series(
        np.where(量缩程度_t > 1.3, 2,
        np.where(量缩程度_t > 1.0, 1,
        np.where(量缩程度_t < 0.7, -2,
        np.where(量缩程度_t < 1.0, -1, 0)))),
        index=df.index
    )

    MA5_t  = MA(c, 5)
    MA10_t = MA(c, 10)
    MA20_t = MA(c, 20)
    MA60_t = MA(c, 60)
    均线分 = ((c > MA5_t).astype(int) * 10 +
              (MA5_t > MA10_t).astype(int) * 10 +
              (MA10_t > MA20_t).astype(int) * 10 +
              (MA20_t > MA60_t).astype(int) * 10)

    MACD分 = pd.Series(
        np.where((DIF > DEA) & (DIF > 0), 25,
        np.where(DIF > DEA, 18,
        np.where(DIF > 0, 12,
        np.where(DIF > DEA * 0.8, 5, 0)))),
        index=df.index
    )

    CL_M20斜 = (MA20_t - REF(MA20_t, 5)) / (REF(MA20_t, 5) + 1e-4) * 100
    斜率分 = pd.Series(
        np.where(CL_M20斜 > 0.5, 20,
        np.where(CL_M20斜 > 0.1, 15,
        np.where(CL_M20斜 > 0, 10,
        np.where(CL_M20斜 > -0.3, 5, 0)))),
        index=df.index
    )

    缠论得分 = (均线分 + 量能分 + MACD分 + 斜率分).clip(upper=100)
    out["缠论趋势评分"] = 缠论得分.astype(float)

    # 布尔：评分首次突破70（冷却10日）
    突破强势原 = CROSS(缠论得分, pd.Series(70, index=df.index))
    突破距上次 = barslast(REF(突破强势原, 1))
    突破强势 = 突破强势原 & ((突破距上次 >= 10) | (突破距上次 >= 999))
    out["缠论趋势强势"] = 突破强势.astype(int)

    # 布尔：评分 >= 65
    out["缠论评分大于65"] = (缠论得分 >= 65).astype(int)

    # ======================================================
    # 3. 缠论方向/买点（来自 缠论Pro副图V6.txt）
    #    方向 = IF(距底<距顶,1,IF(距顶<距底,-1,0))
    #    一买: 方向=1 AND L<MA13 AND 底分型 AND 上一底低点 < 上上底低点
    #    二买: 方向=1 AND L<MA26 AND 底分型 AND 上一底低点 > 上上底低点
    #    V2过滤: (趋势允许 AND 结构保持 AND (量能确认 OR 背驰加分))
    # ======================================================
    距顶 = barslast(顶分型)
    距底 = barslast(底分型)
    方向 = pd.Series(
        np.where(距底 < 距顶, 1, np.where(距顶 < 距底, -1, 0)),
        index=df.index
    )
    out["缠论方向多"] = (方向 == 1).astype(int)

    # 固定 EMA 周期 13/26（跳过 FINANCE 市值自适应）
    MA13 = EMA(c, 13)
    MA26 = EMA(c, 26)

    # CL_DD1 = REF(CL_, 距底+1)：上一底分型时的合并K线低点
    # 逐行取（距底为变化量）
    dist_bot_int2 = 距底.fillna(9999).clip(0, len(df) - 1).astype(int)
    # 预算 numpy 数组,循环内 O(1) 索引(原版每行重算整条 barslast → O(n²),8000行=40s)
    _dbi2 = dist_bot_int2.to_numpy()
    _CL = CL.to_numpy()
    _bl_prev_bot = barslast(REF(底分型, 1)).to_numpy()  # 关键:只算一次
    CL_DD1 = pd.Series(
        [_CL[max(0, i - int(_dbi2[i]) - 1)] if int(_dbi2[i]) < 9999 else np.nan
         for i in range(_n)],
        index=df.index
    )

    # 距底前：前一个底分型距当前的距离
    # REF(BARSLAST(REF(底分型,1)),距底) + 距底 + 1
    # 逐行计算 CL_DD2（上上一个底分型时的CL）
    def _get_prev_bot_cl(i):
        db = int(_dbi2[i])
        if db >= 9999 or i - db - 1 < 0:
            return np.nan
        # 在 i-db-1 处再往前找底分型(用预算数组,不重算)
        sub_idx = max(0, i - db - 1)
        prev_bot = _bl_prev_bot[sub_idx]
        if np.isnan(prev_bot) or prev_bot >= 9999:
            return _CL[sub_idx]
        pp = int(prev_bot) + db + 1
        ref_idx = max(0, i - pp - 1)
        return _CL[ref_idx]

    CL_DD2 = pd.Series([_get_prev_bot_cl(i) for i in range(_n)], index=df.index)

    # 一买: 方向=1 AND L<MA13 AND 底分型 AND CL_DD1 < CL_DD2
    一买1 = (方向 == 1) & (l < MA13) & 底分型 & (CL_DD1 < CL_DD2)
    # 二买: 方向=1 AND L<MA26 AND 底分型 AND CL_DD1 > CL_DD2
    二买1 = (方向 == 1) & (l < MA26) & 底分型 & (CL_DD1 > CL_DD2)
    # 强二买
    强二买1 = (方向 == 1) & (c < MA13) & 底分型 & (CL_DD1 > CL_DD2)

    out["缠论一买"] = 一买1.astype(int)
    out["缠论二买"] = (二买1 | 强二买1).astype(int)

    # V2 过滤：趋势允许 AND 结构保持 AND (量能确认 OR 背驰加分)
    趋势允许 = (MA(c, 20) >= MA(c, 60)) | (barslast(c < MA(c, 60)) < 20)
    结构保持 = (CL_DD1 >= CL_DD2) | (l > REF(LLV(l, 20), 1))
    VOL_MA5_v2 = MA(v, 5)
    量能确认 = (v > VOL_MA5_v2 * 1.5) | (COUNT(v > VOL_MA5_v2 * 1.5, 3) >= 1)
    背驰加分 = MACD底背驰 | (COUNT(MACD底背驰.astype(float), 5) >= 1)
    V1_RAW = 一买1 | 二买1 | 强二买1
    V1 = V1_RAW & ~(REF(V1_RAW, 1).fillna(False))
    V2 = V1 & 趋势允许 & 结构保持 & (量能确认 | 背驰加分)

    out["缠论V2过滤"] = V2.astype(int)

    return out


# ===================================================================
# 组装 + ±2 窗口
# ===================================================================
CONTINUOUS_COLS = ["量比", "距60日高点", "距60日低点", "相对强弱", "吸筹值", "庄家线", "散户线", "六脉红灯数",
                   "主力强度", "资金强度",
                   "波动率", "波动率百分位", "波动档", "MA20斜率",
                   "缠论趋势评分", "MACD背驰强度", "做多权重"]


def assemble_feature_frame(df, index_state_df=None, rel_df=None, code=None):
    """合并全部特征为每日特征表。index_state_df/rel_df 可为None(大盘缺失时)。"""
    parts = [price_form_features(df), volume_features(df), classic_indicators(df),
             wyckoff_features(df), liumai_features(df), multiperiod_resonance(df),
             tdx_extra_features(df, code), zhuangsan_features(df), liumai_signal_features(df),
             capitalflow_features(df), volatility_env_features(df),
             wyckoff_ext_features(df), chanlun_struct_features(df)]
    if index_state_df is not None:
        cols = [c for c in index_state_df.columns if not c.startswith("_")]
        parts.append(index_state_df[cols].reindex(df.index).ffill())
    if rel_df is not None:
        parts.append(rel_df.reindex(df.index))
    return pd.concat(parts, axis=1)


def window_or_at(col, i, offset=2):
    lo, hi = max(0, i - offset), min(len(col) - 1, i + offset)
    if lo > hi:
        return 0
    return int((col.iloc[lo:hi + 1].fillna(0) > 0).any())
