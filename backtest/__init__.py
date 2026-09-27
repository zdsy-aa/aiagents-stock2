"""backtest 包:组合与回测闭环(Phase3)。

Task3.0 提供面板数据基座:load_panel / load_confirm_panel / split_train_test
与口径常量;Task4.3(Phase3 终审前置项)起补全包级导出:数据基座 / 组合求值 /
统一回测引擎 / 参数测试 / 失败库 / 版本管理 / Markdown 报告。

注意 report.py 内部 `from backtest import versioning` 依赖包级子模块属性,
故 versioning 先于 report 导入。
"""
from backtest.dataio import (
    DOWN_LABEL_COL,
    LABEL_COL,
    RET_COL,
    TEST_MIN_YEAR,
    TRAIN_MAX_YEAR,
    confirm_panel_columns,
    load_confirm_panel,
    load_panel,
    split_train_test,
)
from backtest.combo_engine import build_57_specs, eval_combo
from backtest.engine import DATE_COL, HOLD_DAYS, TRADING_DAYS_PER_YEAR, run_backtest
from backtest.param_test import grid_test, overfit_flag, sensitivity, walk_forward
from backtest.failure_db import (
    CATEGORIES,
    classify_failure,
    failure_stats,
    init_db,
    record_failures,
)
from backtest.versioning import VERSIONS_PATH, bump_version, param_history
from backtest.report import DEFAULT_REPORT_DIR, gen_report, gen_report_57

__all__ = [
    # 数据基座(dataio)
    "load_panel",
    "load_confirm_panel",
    "confirm_panel_columns",
    "split_train_test",
    "LABEL_COL",
    "RET_COL",
    "DOWN_LABEL_COL",
    "TRAIN_MAX_YEAR",
    "TEST_MIN_YEAR",
    # 组合求值(combo_engine / signal_specs)
    "eval_combo",
    "build_57_specs",
    # 统一回测引擎(engine)
    "run_backtest",
    "DATE_COL",
    "HOLD_DAYS",
    "TRADING_DAYS_PER_YEAR",
    # 参数测试(param_test)
    "grid_test",
    "sensitivity",
    "walk_forward",
    "overfit_flag",
    # 失败库(failure_db)
    "init_db",
    "classify_failure",
    "record_failures",
    "failure_stats",
    "CATEGORIES",
    # 版本管理(versioning)
    "VERSIONS_PATH",
    "bump_version",
    "param_history",
    # Markdown 报告(report)
    "gen_report",
    "gen_report_57",
    "DEFAULT_REPORT_DIR",
]
