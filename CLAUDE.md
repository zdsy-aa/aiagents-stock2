# aiagents-stock 项目规则

> 本文件为长期项目记忆(Phase 6 Task 6.3 更新):六节为项目结构/核心逻辑/关键路径/运行方式/重要约定/已知问题;只记长期有效信息,不记日志/缓存/锁文件/临时路径。完整资产清单见 docs/项目资产说明.md(2026-09-28 实测)。

## 分支策略（重要）

**以后只在 `main` 分支上开发。**

- 所有新功能、修复、研究代码一律提交到 `main`，不再新建/使用长期特性分支。
- 远程为 `stock2`（`git@github.com:zdsy-aa/aiagents-stock2.git`），`main` 跟踪 `stock2/main`。
- 由用户自行 `git push stock2 main`（除非用户明确要求代为推送）。
- 历史背景：曾长期在 `feat/liumai-and-combo-screening` 上开发，导致生产功能栈（六脉/组合/星级/盘中化/稳定选股/邮件改版）只在 feat、`main` 落后一大截。2026-06-12 已用 `git merge feat→main`（merge 062b8d6，零冲突）把整条栈合回 main，`main ≡ feat`。从此统一到 main，避免再次分叉。
- `feat/liumai-and-combo-screening` 视为历史分支，不再继续在其上开发。

## 项目结构

分层为「应用—引擎—接口—自动化」：

- **顶层四个自建包**（Phase 2~5 产物）：
  - `indicators/` 指标管线：registry.py / evaluator.py / tdx_parser.py / tdx_builtins.py（registry.json 当前 3 项注册）
  - `backtest/` 统一回测：engine.py / combo_engine.py / dataio.py / param_test.py / failure_db.py / signal_specs.py / versioning.py / report.py
  - `interfaces/` 统一接口：ai_trace.py / analyze.py / backtest_api.py / bridge.py / common.py / html_report.py / screen.py
  - `automation/` 自动化与风控：cli.py / jobs.py / notify.py / alert.py / chip_data.py / market_env.py / risk_filter.py / signal_tracking.py / home_scan.py / asset_watch.py
- **`views/`** 页面路由与视图（10 个）；顶层 `*.py` 主应用与各策略模块（123 个，20 页面路由）。
- **数据网关**：`akshare_gateway.py`、`data_source_manager.py`。
- **`tdx-api/`**（Go 本地行情 API 服务）、**`pg_warehouse/`**（PostgreSQL 数仓同步）。
- **通达信脚本在仓库外**：`/home/tdxback/通达信py脚本/`（57 信号盘后扫描/盘中提醒，Windows 侧运行，本机 Linux 不执行）。

## 核心逻辑

- **数据流**：tdx-api 行情 → `kline-updater`（每日 18:00 增量，见 scheduler/crontab）写入本地 K 线库（tdx-data/database/kline/）→ 面板（data/profit_mining/*.npz / *.csv）→ backtest 回测。
- **指标管线**：仓库外 32 个通达信公式（/home/tdxback/通达信指标/）→ 公式解析 → AST 求值 → registry；partial（部分输出不可求值）/unsupported（函数求值抛 NotImplementedError）语义贯穿注册与消费。
- **57 信号**（TQ01~TQ57）是核心策略资产：训练段 ≤2024、测试段 ≥2025；对齐验收已达成（tests/test_alignment_57.py，胜率/占比容差 ±0.3pp、支持完全一致）。
- **回测指标**（backtest/report.py 表格列）：训练/测试胜率、训练/测试支持、平均收益、最大回撤、连续亏损、盈亏比、涨跌占比、过拟合标志。
- **AI 辅助，不替代规则**：AI 分析是辅助层，规则信号为准。

## 关键路径

- 收盘后任务链：`python -m automation.cli --phase post_market`（另支持 pre_market / intraday / all；失败任务自动邮件告警）。
- 指标转换：`scripts/indicator_pipeline.py run MACD`（子命令 check-new / run / run-all / smoke / docs）。
- 57 信号对齐验收：`tests/test_alignment_57.py`。
- 回测报告：`report/回测报告_57信号_*.md`（57 信号整表，文件名带生成时间戳）。

## 运行方式

- **venv-data**：`/home/tdxback/venv-data`（pandas 3.0.6、pytest 9.1.1；pyarrow/streamlit/yfinance/sqlalchemy 未装，见已知问题）。
- **docker compose**：服务含 agentsstock（网页主应用）/ aktools / tdx-stock-web / kline-updater（每日 18:00 K 线增量）/ chanlun-updater / qizhang-updater / postgres / pg-sync-updater。
- **测试通道**：仓库根目录执行 `/home/tdxback/venv-data/bin/python -m pytest`（或 `-m pytest tests/<文件>`）。

## 重要约定

- **R4-A 错误契约**：输入非法抛 `ValueError`；依赖缺失抛 `RuntimeError` 且消息带接口名（interfaces/common.py `api_error()` 包装，根因挂 `__cause__`）；AI 失败降级为 degraded 状态。
- **统一口径**：股票代码 6 位；时间 YYYYMMDD；行情不复权。
- **registry partial/unsupported 必须消费**：消费方不得忽略这两个标记（partial 允许注册成功但输出须标注；unsupported 输出不可求值）。
- **registry_overrides.json 人工修正保护**：机器写回 registry.json 不经 overrides 合并；加载时人工修正按键级合并、override 优先，人工编辑不被流水线覆盖。
- **提交只含任务产物**：不提交日志/缓存/锁文件/临时路径等临时信息。
- 面向用户的输出一律用中文。
- 分析报告存 `/home/tdxback/report/` 并加 `_YYYYMMDD_HHMMSS` 时间戳后缀。
- `data/profit_mining/` 跟踪策略：**生产管线脚本入库**（被「📋 当前策略」页引用、或作为已入库下游脚本的上游依赖闭包：features.py / build_features*.py / events_export.py / event_registry.py / label_window.py / mine_combos*.py / mine_sell.py / walk_forward.py / mine_regime.py + 其测试，2026-06-13 修复跟踪断裂时入库）；纯探索/一次性实验脚本（backtest_*.py / portfolio_backtest*.py / eval_*.py / offset_sweep.py / refine_*.py 等）保持 untracked。判据：策略页/CLAUDE 文档引用到、或入库脚本 import 到的 → 入库；否则可不入库。
- 部署为 5 容器 docker；`./data` 挂载进容器即时生效，根目录代码（如 chanlun_batch.py）需重建镜像才生效。

## 已知问题

与 `docs/项目资产说明.md`「已知问题」8 条一致（逐条来源与复验见该文档，此处仅列纲要）：

1. 盈亏比无下行收益：确认面板「区间涨跌幅」为上行口径，57 信号盈亏比全 ∞、涨跌占比全「—」。
2. 筹码数据源不可用：akshare/tdx_file/本地客户端三源探测均不可用，`chip_decision()` 返回 unavailable。
3. venv-data 缺部分三方库：pyarrow/streamlit/yfinance/sqlalchemy 未装。
4. 分析每股双记录：stock_analysis_engine 直写与 ai_trace.trace_save 并存，待引擎单点化收口。
5. TDX 客户端未在 Linux 安装：57 信号扫描脚本仅 Windows 侧可跑，Linux 侧由 backtest/signal_specs.py + interfaces/screen.py 重实现。
6. registry 未支持函数 8 个：WINNER(28 处)/NAMELIKE/FINANCE/DYNAINFO/HHVBARS/LLVBARS/SUMBARS/DMA 求值期抛 NotImplementedError。
7. 买点事件面板截至 2026-05-28：signal_features.csv + turnover_signal.csv 最新信号日期 2026-05-28；确认面板 v1 覆盖至 2026-08-05、v2 至 2026-09-07，行集/口径不同须按 dataio 注释区分。
8. registry 覆盖率不足：32 公式文件仅 3 条注册（六脉神剑V5 / 核心_基础V3 partial / MACD，合计 58 输出），registry_overrides.json 为空。
