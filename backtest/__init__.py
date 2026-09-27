"""backtest 包:组合与回测闭环(Phase3)。

Task3.0 提供面板数据基座:load_panel / split_train_test 与口径常量。
"""
from backtest.dataio import (
    LABEL_COL,
    RET_COL,
    TEST_MIN_YEAR,
    TRAIN_MAX_YEAR,
    load_panel,
    split_train_test,
)

__all__ = [
    "load_panel",
    "split_train_test",
    "LABEL_COL",
    "RET_COL",
    "TRAIN_MAX_YEAR",
    "TEST_MIN_YEAR",
]
