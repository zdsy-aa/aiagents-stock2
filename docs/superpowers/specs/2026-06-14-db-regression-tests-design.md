# db 层防回归测试安全网 设计

2026-06-14。#3「db 层重构」经 brainstorm 收敛:base 模式已统一(10 个 *_db.py 全继承 BaseDatabase),
不做大重构/迁 ORM。真正痛点=**改大 db 时静默丢方法**(历史:base_db 重构丢 portfolio 方法,事后才补回归测试)。
根因=**未测的大 db 模块缺测试**。本任务=给这 6 个未测模块补 characterization 测试,**纯新增测试、零生产改动**。

## 目标
- 给 6 个未测 db 模块补特征(characterization)测试,覆盖各自主要公共 CRUD 方法的 save→get(+update/delete) 回路。
- 效果:未来重构若丢失/改坏任一被测方法,`pytest tests/` 立即失败(防回归安全网)。
- **不改任何生产代码**(不动 base_db、不动 6 个 db 模块、不抽重复、不迁 ORM)。

## 现状(brainstorm 已确认)
- 10 个 *_db.py 全继承 `BaseDatabase`(base 提供 `conn()`/WAL/`cleanup_old_data`)。
- 已有测试:base_db / chanlun_signal_db / combo_signal_db / liumai_signal_db / portfolio_db(回归) / db_executemany。
- **未测的 6 个**:news_flow_db(28方法) / monitor_db(17) / longhubang_db(11) / smart_monitor_db(10) / main_force_batch_db(9) / sector_strategy_db(8)。
- 6 个均:构造器带 db_path 默认值(可传临时路径)、**零外部依赖**(无 akshare/requests,纯自有 sqlite CRUD)→ 合成数据可完整测。
- ⚠️ `smart_monitor_db.SmartMonitorDB` 构造参数名是 **`db_file`**(非 db_path);其余 5 个是 `db_path`。

## 范围:6 个新测试文件(tests/, pytest)
每文件一/数个测试函数,用 `tempfile` 临时 sqlite 路径实例化,合成数据跑核心回路:
1. `tests/test_news_flow_db.py` — `NewsFlowDatabase(db_path=tmp)`:save_flow_snapshot → get_latest_snapshot / get_recent_snapshots / get_snapshot_detail 回路;save_sentiment_record → get_recent_scores;get_daily_statistics 不崩。
2. `tests/test_monitor_db.py` — `StockMonitorDatabase(db_path=tmp)`:add_monitored_stock → get_monitored_stocks;update_stock_price/update_last_checked;add_notification → get_pending_notifications → mark_notification_sent;has_recent_notification。
3. `tests/test_longhubang_db.py` — `LonghubangDatabase(db_path=tmp)`:save_longhubang_data → get_longhubang_data / get_top_stocks;save_analysis_report → get_analysis_reports / get_analysis_report → delete_analysis_report。
4. `tests/test_smart_monitor_db.py` — `SmartMonitorDB(db_file=tmp)`:add_monitor_task → get_monitor_tasks → update_monitor_task → delete_monitor_task;save_ai_decision → get_ai_decisions。
5. `tests/test_main_force_batch_db.py` — `MainForceBatchDatabase(db_path=tmp)`:save_batch_analysis → get_all_history / get_record_by_id / get_statistics → delete_record。
6. `tests/test_sector_strategy_db.py` — `SectorStrategyDatabase(db_path=tmp)`:save_raw_data → get_latest_raw_data;save_analysis_report → get_analysis_reports / get_analysis_report → delete_analysis_report。

每测试:断言写入值能取回(round-trip);delete 后取不到;update 后值变。被测的具体方法签名/字段以**实际代码为准**(实现计划阶段逐个读源码确定入参/返回结构,不臆造)。

## 测试规范(吸取本会话 flaky 教训)
- 每测试用**独立临时库**(`tempfile.mkdtemp()/x.db`),互不影响。
- **不做任何类级 monkeypatch / 全局态修改**(上次 AppTest 类级替换泄漏致 test_liumai_selector 假阳)。
- 不依赖执行顺序;不写真实 data/*.db。
- 放 `tests/`,与现有 test_*_signal_db 同风格(pytest 可收集;`python3 -m pytest tests/test_xxx.py` 可单跑)。

## 风险控制
- **零生产代码改动**:本任务只增 tests/ 文件。
- 完工跑 `pytest tests/` 全量,确认新测全绿 + 无回归(0 failed,排除已知环境项)。

## 非目标(YAGNI)
- 不改 base_db / 6 个 db 模块 / 任何生产逻辑。
- 不抽重复 boilerplate、不统一 news_flow 直连(留"诊断后另议")。
- 不迁 ORM。
- 不追求 100% 方法覆盖(覆盖主要 CRUD 回路即可达到"防丢方法"目的;纯展示/统计类方法只验不崩)。

## 数据依赖
无(纯临时 sqlite + 合成数据)。
