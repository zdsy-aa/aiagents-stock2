"""interfaces 包:对外统一程序接口(Phase4)。

薄封装现有能力,不改被封装模块的既有行为。Task4.0 先落公共约定,后续任务补充:

  - common        ANALYSIS_KEYS / Scenario / api_error / SCREEN_RESULT_COLS(Task4.0)
  - analyze       analyze_stock(Task4.1,已导出) / build_scenarios(interfaces.analyze)
  - screen        screen_stocks / scan_signals(Task4.2)
  - backtest_api  run_backtest_api / html_report.gen_report(Task4.3)
  - ai_trace      comparison_table / trace_save(Task4.4)
  - bridge        registry_to_spec / guard_partial(Task4.5)
"""
from .common import ANALYSIS_KEYS, SCREEN_RESULT_COLS, Scenario, api_error
from .analyze import analyze_stock

__all__ = ["ANALYSIS_KEYS", "SCREEN_RESULT_COLS", "Scenario", "api_error", "analyze_stock"]
