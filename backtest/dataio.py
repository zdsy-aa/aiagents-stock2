# backtest/dataio.py
"""信号面板读取与训练/测试划分。口径与 profit_mining/refine_backtest.load() 一致。"""
import pandas as pd

HERE = __file__ and __import__("pathlib").Path(__file__).resolve().parent
SF = "/home/tdxback/aiagents-stock/data/profit_mining/signal_features.csv"
TS = "/home/tdxback/aiagents-stock/data/profit_mining/turnover_signal.csv"
LABEL_COL = "是否盈利"
RET_COL = "区间涨跌幅"
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
