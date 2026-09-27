# backtest/dataio.py
"""信号面板读取与训练/测试划分。

两个面板并存(控制器裁决,Task 3.2 勘误):
- load_panel():买点事件面板(signal_features.csv + turnover_signal.csv,97,329 行),
  口径与 profit_mining/refine_backtest.load() 一致。Task 3.0 产物,保留;不用于对齐验收。
- load_confirm_panel():确认面板 confirm_panel.npz(15,115,796 行日K × 168 布尔位压缩列
  + 17 连续列 + 标签),Top50 JSON 的胜率/支持挖掘底座(mine_confirm.py),Task 3.2
  对齐验收数据基座。confirm_panel_v2.npz(v2=True)多含 y_dn 下跌标签与见顶/见底日
  列,tq_confirm_top10.py 文件头 TQ51~57 涨跌占比的挖掘底座(mine_combo11.py)。
"""
import functools

import numpy as np
import pandas as pd

HERE = __file__ and __import__("pathlib").Path(__file__).resolve().parent
SF = "/home/tdxback/aiagents-stock/data/profit_mining/signal_features.csv"
TS = "/home/tdxback/aiagents-stock/data/profit_mining/turnover_signal.csv"
CONFIRM_PATH = "/home/tdxback/aiagents-stock/data/profit_mining/confirm_panel.npz"
CONFIRM_V2_PATH = "/home/tdxback/aiagents-stock/data/profit_mining/confirm_panel_v2.npz"
LABEL_COL = "是否盈利"
RET_COL = "区间涨跌幅"
DOWN_LABEL_COL = "是否下跌"
TRAIN_MAX_YEAR = 2024
TEST_MIN_YEAR = 2025

def load_panel():
    sf = pd.read_csv(SF, encoding="utf-8-sig")
    ts = pd.read_csv(TS, encoding="utf-8-sig")
    for d in (sf, ts):
        d["股票代码"] = d["股票代码"].astype(str)
        d["信号日期"] = d["信号日期"].astype(str)
    ts = ts.drop_duplicates(["股票代码", "信号日期"])
    df = sf.merge(ts, on=["股票代码", "信号日期"], how="left").reset_index(drop=True)
    df[LABEL_COL] = pd.to_numeric(df[LABEL_COL], errors="coerce").fillna(0).astype(int)
    df["年"] = df["信号日期"].str[:4]
    df[RET_COL] = pd.to_numeric(df[RET_COL], errors="coerce")
    return df

def split_train_test(df):
    train = df[df["年"].astype(int) <= TRAIN_MAX_YEAR].copy()
    test = df[df["年"].astype(int) >= TEST_MIN_YEAR].copy()
    return train, test


def confirm_panel_columns():
    """确认面板列名清单(只读 npz 头,不解包位,毫秒级)。

    = 168 布尔列(bool_cols 顺序=位序)+ 17 连续列 + 是否盈利/区间涨跌幅 +
      (v2) 是否下跌 + 股票代码/信号日期/年。
    """
    d = np.load(CONFIRM_PATH, allow_pickle=True)
    cols = [str(c) for c in d["bool_cols"]] + [str(c) for c in d["cont_cols"]]
    return tuple(cols + [LABEL_COL, RET_COL, DOWN_LABEL_COL, "股票代码", "信号日期", "年"])


def _y_dn_column(Y, v2):
    """v2 面板的下跌标签列(Y[:,2] = 未来20日最低/收盘-1 <= -10%);v1 无该列。"""
    if v2 and Y.shape[1] > 2:
        return Y[:, 2].astype(np.float64)
    return None


@functools.lru_cache(maxsize=1)
def load_confirm_panel(limit=None, v2=False):
    """读确认面板 -> pd.DataFrame(可复现:固定 npz,确定性解包,无随机)。

    - 行空间 = 全A 4426 股 × 任意日K时点(15,115,796 行;v2: 15,125,987 行,
      比 v1 多 2026-09-03~07 的 5 个交易日、少部分 1990 早期行,行集不同)。
    - B 位压缩:uint8 (n,21),packbits(bitorder='little'),21×8=168 位对应
      bool_cols 列名;解包用 np.unpackbits 逐字节向量化(非 Python 循环),
      列名 = bool_cols[k](k=0..167),位序实测与 mine_confirm 的
      `P[:, k//8] & (1 << (k%8))` 提取一致(Top50 支持数完全对齐验证)。
    - C 连续列保留 float32(含 NaN)。
    - Y: v1 = [是否盈利, 区间涨跌幅](y_up=未来20日最高/收盘-1>=10%,
      ext_up=最高/收盘-1);v2 增 [是否下跌(y_dn=未来20日最低/收盘-1<=-10%),
      最大跌幅, 见顶日, 见底日],仅 y_dn 以「是否下跌」列载入。
      标签 NaN(每股末尾 20 根无前视窗口的 bar)整行剔除 —— 与 mine_confirm 的
      m_valid 口径一致(支持数对齐的前提)。
    - dates = 距 1970-01-01 天数(int64),转「信号日期」YYYYMMDD(int32)与「年」(int16);
      切分口径:年 <= 2024 训练、>= 2025 测试(等价 mine 的 dates < 20089)。
    - limit: 冒烟参数,只取前 N 行(原始行序)后再剔 NaN 标签行,仅测试用。
    - 解包时间实测 ~60s(15M 行,机器相关);进程内 lru_cache(maxsize=1) 缓存。
    """
    path = CONFIRM_V2_PATH if v2 else CONFIRM_PATH
    d = np.load(path, mmap_mode="r", allow_pickle=True)
    B, C, Y = d["B"], d["C"], d["Y"]
    dates, sid = d["dates"], d["sid"]
    bool_cols = [str(c) for c in d["bool_cols"]]
    cont_cols = [str(c) for c in d["cont_cols"]]
    codes = d["codes"]
    if limit:
        B, C, Y = B[:limit], C[:limit], Y[:limit]
        dates, sid = dates[:limit], sid[:limit]
    valid = ~np.isnan(Y[:, 0])
    # 先按标签有效性切片再解包:峰值内存仅约 2× 最终 DataFrame
    B, C, Y = B[valid], C[valid], Y[valid]
    dates, sid = dates[valid], sid[valid]
    # dates(int64 天数,距 1970-01-01) -> 年/信号日期,向量化
    dts = pd.to_datetime(dates.astype(np.int64), unit="D")  # datetime64[ns]
    year = dts.year.to_numpy().astype(np.int16)
    ymd = (dts.year.to_numpy().astype(np.int32) * 10000
           + dts.month.to_numpy().astype(np.int32) * 100
           + dts.day.to_numpy().astype(np.int32))
    del dts
    cols = {}
    n_bits = len(bool_cols)
    # B 位解包:逐字节 unpackbits(每字节 -> 8 位),峰值仅一字节块的中间数组
    for j in range(B.shape[1]):
        bits = np.unpackbits(B[:, j], bitorder="little").reshape(-1, 8)  # (n, 8) uint8 0/1
        for b in range(8):
            k = j * 8 + b
            if k >= n_bits:
                break
            cols[bool_cols[k]] = bits[:, b]
    for i, name in enumerate(cont_cols):
        cols[name] = C[:, i]
    cols[LABEL_COL] = Y[:, 0].astype(np.float64)
    cols[RET_COL] = Y[:, 1].astype(np.float64)
    dn = _y_dn_column(Y, v2)
    if dn is not None:
        cols[DOWN_LABEL_COL] = dn
    cols["信号日期"] = ymd
    cols["年"] = year
    cols["股票代码"] = pd.Categorical.from_codes(sid, codes.astype(str))
    df = pd.DataFrame(cols)
    return df
