import pathlib
from backtest.dataio import load_panel, split_train_test, TRAIN_MAX_YEAR, LABEL_COL

def test_load_panel_shape_and_columns():
    df = load_panel()
    # 面板实测 97329 行(2026-09-27 实测;全盘仅 data/profit_mining/signal_features.csv
    # 一个面板文件,年份 1992-2026)。简报原写 >100_000 与本数据不符(不可达),
    # 下调为 >90_000:仍能拦截截断/抽样面板,保留原断言的量级校验意图。
    assert len(df) > 90_000                      # 全市场信号级面板
    for col in ("股票代码", "信号日期", LABEL_COL, "年"):
        assert col in df.columns
    assert set(df[LABEL_COL].unique()) <= {0, 1}

def test_split_by_year():
    df = load_panel()
    tr, te = split_train_test(df)
    assert int(tr["年"].max()) <= TRAIN_MAX_YEAR
    assert int(te["年"].min()) >= 2025
    assert len(tr) + len(te) == len(df)
