# 项目资产清单(ASSETS.md)

> 盘点日期:2026-09-26(Task 1.1 资产清单盘点)
> 维护约定:资产新增/删除/迁移时,由对应任务同步更新本清单;可用 `python3 scripts/assets_check.py` 一键校验各资产域在库。
> 下游引用:本清单供全部后续任务(Phase 1~5)与 Phase 6「全目录分析与记忆」引用。
> 盘点原则:只列真实存在、路径已验证的资产;已迁移/不存在的路径如实标注「已迁移/不存在(2026-09-26 盘点)」。

## 结论摘要

| 资产域 | 位置 | 数量(2026-09-26 实测) |
|---|---|---|
| 代码 | aiagents-stock(122 顶层 .py + views/ 10 + tests/ 50)、通达信py脚本(5 .py)、行业数据集脚本(7 .py,原 tdxgp 已迁移) | 约 194 个 .py + tdx-api Go 服务 |
| 指标 | 通达信指标/20260424001/tdx_v4_standalone(7 个公式子目录 + 99_说明手册) | 32 个公式 .txt + 4 个手册 .txt |
| 数据 | aiagents-stock/tdx-data/database/kline(5604 个 .db)、data/*.db(15 个信号/业务库)、data/profit_mining(223 个研究文件)、通达信股票上下游分析/a_shares_raw.json | — |
| 文档 | aiagents-stock/docs(73 .md + plans/specs)、各目录 .md(共 115 个)与 .xlsx 交付物(3 个) | — |

## 一、代码域

### 1.1 aiagents-stock(Streamlit 主应用)

- 路径:`/home/tdxback/aiagents-stock/*.py`、`views/*.py`
- 用途:AI 股票分析主应用(分析/选股/策略/监测/配置,共 21 页面路由)
- 维护方式:手工编码(个人项目,单开发者)
- 更新频率:需求驱动

#### 1.1.1 页面 → 入口脚本反查(nav_model.py 单源 + views/page_router.py 路由)

| 大类 | 页面 | show_flag | 入口 UI | 支撑模块(核心) |
|---|---|---|---|---|
| 分析 | 股票分析-日(首页) | None | views/analysis_home.py | views/analysis_runner.py(流程编排)、stock_analysis_engine.py、stock_data.py、ai_agents.py、deepseek_client.py、database.py、views/analysis_views.py、pdf_generator.py |
| 选股 | 主力选股 | show_main_force | main_force_ui.py | main_force_selector.py、main_force_analysis.py、main_force_batch_db.py、main_force_pdf_generator.py、main_force_history_ui.py |
| 选股 | 低价擒牛 | show_low_price_bull | low_price_bull_ui.py | low_price_bull_selector.py、low_price_bull_strategy.py、low_price_bull_monitor.py、low_price_bull_service.py、low_price_bull_monitor_ui.py |
| 选股 | 小市值 | show_small_cap | small_cap_ui.py | small_cap_selector.py |
| 选股 | 净利增长 | show_profit_growth | profit_growth_ui.py | profit_growth_selector.py、profit_growth_monitor.py |
| 选股 | 低估值 | show_value_stock | value_stock_ui.py | value_stock_selector.py、value_stock_strategy.py |
| 选股 | 缠论选股 | show_chanlun | chanlun_ui.py | chanlun_engine.py、chanlun_selector.py、chanlun_signal_db.py、chanlun_batch.py、chanlun_single.py、chanlun_universe.py、chanlun_chart_ui.py |
| 选股 | 六脉神剑 | show_liumai | liumai_ui.py | liumai_engine.py、liumai_selector.py、liumai_signal_db.py、liumai_batch.py |
| 选股 | 缠论×六脉 | show_combo | combo_ui.py | combo_selector.py、combo_batch.py、combo_signal_db.py |
| 选股 | 稳定选股 | show_stable | stable_ui.py | (样本外验证的稳健买卖策略页) |
| 选股 | 起涨预测 | show_qizhang | qizhang_predict_ui.py | qizhang_batch.py、qizhang_picks_db.py |
| 选股 | 当前策略 | show_current_strategy | current_strategy_ui.py | strategy_catalog.py(策略脚本总览只读页) |
| 策略 | 智策板块 | show_sector_strategy | sector_strategy_ui.py | sector_strategy_agents.py、sector_strategy_data.py、sector_strategy_db.py、sector_strategy_engine.py、sector_strategy_pdf.py、sector_strategy_scheduler.py |
| 策略 | 智瞰龙虎 | show_longhubang | longhubang_ui.py | longhubang_agents.py、longhubang_data.py、longhubang_db.py、longhubang_engine.py、longhubang_pdf.py、longhubang_scoring.py |
| 策略 | 新闻流量 | show_news_flow | news_flow_ui.py | news_flow_agents.py、news_flow_data.py、news_flow_db.py、news_flow_engine.py、news_flow_model.py、news_flow_pdf.py、news_flow_scheduler.py、news_flow_sentiment.py、news_flow_alert.py |
| 策略 | 宏观分析 | show_macro_analysis | macro_analysis_ui.py | macro_analysis_agents.py、macro_analysis_data.py、macro_analysis_engine.py |
| 策略 | 宏观周期 | show_macro_cycle | macro_cycle_ui.py | macro_cycle_agents.py、macro_cycle_data.py、macro_cycle_engine.py、macro_cycle_pdf.py |
| 策略 | 产业链 | show_industry_chain | industry_chain_ui.py | industry_chain_data.py(底层数据见 1.3 行业数据集) |
| 策略 | 板块分析 | show_sector_detail | sector_detail_ui.py | market_sentiment_data.py(市场情绪数据) |
| 配置 | 环境配置 | show_config | views/config_manager.py | config.py、config_manager.py |

注:监测面板不在 NAV 顶层导航中,由分析历史页/选股页内嵌进入:monitor_ui.py(views/history.py 置 show_monitor)、smart_monitor_ui.py(小市值/低价擒牛页内嵌)、portfolio_ui.py,及其支撑模块 monitor_db/manager/scheduler/service.py、smart_monitor_data/db/deepseek/engine/kline/qmt/tdx_data.py、portfolio_db/manager/scheduler.py。

#### 1.1.2 按功能分组完整清单(122 个顶层 .py + views/ 10 个)

- 分析:app.py、run.py、stock_analysis_engine.py、stock_data.py、ai_agents.py、deepseek_client.py、database.py、base_db.py、pdf_generator.py;views/analysis_home.py、views/analysis_runner.py、views/analysis_views.py、views/history.py
- 选股:main_force_analysis.py、main_force_batch_db.py、main_force_history_ui.py、main_force_pdf_generator.py、main_force_selector.py、main_force_ui.py;low_price_bull_monitor.py、low_price_bull_monitor_ui.py、low_price_bull_selector.py、low_price_bull_service.py、low_price_bull_strategy.py、low_price_bull_ui.py;small_cap_selector.py、small_cap_ui.py;profit_growth_monitor.py、profit_growth_selector.py、profit_growth_ui.py;value_stock_selector.py、value_stock_strategy.py、value_stock_ui.py;chanlun_batch.py、chanlun_chart_ui.py、chanlun_engine.py、chanlun_selector.py、chanlun_signal_db.py、chanlun_single.py、chanlun_ui.py、chanlun_universe.py;liumai_batch.py、liumai_engine.py、liumai_selector.py、liumai_signal_db.py、liumai_ui.py;combo_batch.py、combo_selector.py、combo_signal_db.py、combo_ui.py;stable_ui.py;qizhang_batch.py、qizhang_picks_db.py、qizhang_predict_ui.py;current_strategy_ui.py、strategy_catalog.py
- 策略:sector_strategy_agents.py、sector_strategy_data.py、sector_strategy_db.py、sector_strategy_engine.py、sector_strategy_pdf.py、sector_strategy_scheduler.py、sector_strategy_ui.py、sector_detail_ui.py;longhubang_agents.py、longhubang_data.py、longhubang_db.py、longhubang_engine.py、longhubang_pdf.py、longhubang_scoring.py、longhubang_ui.py;news_flow_agents.py、news_flow_alert.py、news_flow_data.py、news_flow_db.py、news_flow_engine.py、news_flow_model.py、news_flow_pdf.py、news_flow_scheduler.py、news_flow_sentiment.py、news_flow_ui.py;macro_analysis_agents.py、macro_analysis_data.py、macro_analysis_engine.py、macro_analysis_ui.py;macro_cycle_agents.py、macro_cycle_data.py、macro_cycle_engine.py、macro_cycle_pdf.py、macro_cycle_ui.py;industry_chain_data.py、industry_chain_ui.py
- 数据:akshare_gateway.py、data_source_manager.py、fund_flow_akshare.py、market_sentiment_data.py、qstock_news_data.py、news_announcement_data.py、quarterly_report_data.py、risk_data_fetcher.py、miniqmt_interface.py、smart_monitor_data.py、smart_monitor_kline.py、smart_monitor_tdx_data.py、smart_monitor_qmt.py;tdx-api/(Go 服务,本地行情 API,见 3.1)
- UI 与基础设施:ui_theme.py、views/sidebar.py、views/top_nav.py、views/nav_model.py、views/page_router.py、views/config_manager.py、config.py、config_manager.py、logger_config.py、model_config.py、notification_service.py、base_scheduler.py、monitor_scheduler.py、update_env_example.py
- 监测:monitor_db.py、monitor_manager.py、monitor_scheduler.py、monitor_service.py、monitor_ui.py;smart_monitor_db.py、smart_monitor_deepseek.py、smart_monitor_engine.py、smart_monitor_ui.py;portfolio_db.py、portfolio_manager.py、portfolio_scheduler.py、portfolio_ui.py
- 调度与运维:scheduler/(crontab、update.sh、Dockerfile)、ops/(export_watchlist_md.py、export_watchlist_xlsx.py、push_watchlist.py、send_mail.py、check.sh、check-cron.sh、daily_watchlist_and_mail.sh、intraday_watchlist_and_mail.sh、sector_strategy_and_mail.sh、README.md)
- 研究挖掘:data/profit_mining/(91 个 .py:特征构建、回测、维度挖掘、榜单分析;数据文件见 3.4)
- 测试:tests/(50 个 .py,unittest/pytest)

### 1.2 通达信py脚本(通达信客户端策略脚本)

- 路径:`/home/tdxback/通达信py脚本/*.py`(5 个)
- 用途:运行于通达信客户端的 TQ 策略脚本与数据测试
- 维护方式:手工编码
- 更新频率:需求驱动

| 文件 | 用途 |
|---|---|
| tq_confirm_top10.py | 「六脉缠论」规则集全市场每日盘后扫描,57 信号(买入 TQ01~TQ51、卖出 TQ52~TQ57)写入客户端板块 TQ01~TQ57 |
| tq_alert_top10.py | 同上 57 信号盘中实时提醒(候选池轮询、(日期,代码,信号号)去重、send_warn 预警) |
| tqcenter.py | TQ 脚本公共库(JSON/ctypes/numpy/pandas,通达信数据接口封装) |
| tdxdata_test.py | 通达信数据接口测试脚本 |
| tdxquant_试跑.py | TDX 量化试跑脚本 |

### 1.3 行业数据集脚本(原 tdxgp)

- 路径:`/home/tdxback/tdxgp` → **已迁移/不存在(2026-09-26 盘点)**
- 实际位置:`/home/tdxback/通达信股票上下游分析/*.py`(7 个)
- 用途:A 股产业链/上下游数据抓取、清洗与文档生成(数据见 3.3)
- 维护方式:手工编码 + 脚本自动生成数据
- 更新频率:按需

| 文件 | 用途 |
|---|---|
| fetch_a_share.py | 抓取 A 股主营业务数据(产出 a_shares_raw.json) |
| fetch_rotate.py | 行业轮动数据抓取 |
| fix_gaps.py、fix_industry.py | 数据缺口修复/行业归属修复 |
| generate_docs.py | 生成 .md/.xlsx 交付物 |
| industry_chain.py、supply_chain.py | 产业链/上下游业务往来计算 |

## 二、指标域(通达信指标)

- 路径:`/home/tdxback/通达信指标/20260424001/tdx_v4_standalone/`(7 个公式子目录 + 99_说明手册;另有同目录 tdx_v4_standalone.zip 压缩备份)
- 用途:通达信主图/副图/选股公式,按体系分目录组织
- 维护方式:通达信公式编辑器维护,导出为 .txt 存放
- 更新频率:按需(文件名版本号 V3~V10 递增)

### 2.1 七个子目录公式文件清单(文件名 + 所属体系)

| 所属体系 | 目录 | 公式文件 |
|---|---|---|
| 公共核心 | 00_公共核心模块 | 核心_基础V3.txt、核心_大盘V3.txt、核心_波动V3.txt |
| 威科夫 | 01_威科夫体系 | 威科夫_主图V7.txt、威科夫评分副图V5.txt、资金监控V5.txt、黄金柱子V4.txt |
| 缠论结构 | 02_缠论结构体系 | MACD背驰V8.txt、中枢位置V10.txt、缠论Pro副图V6.txt、缠论_主图V9.txt、趋势评分V8.txt |
| 资金流向 | 03_资金流向体系 | 六脉神剑V5.txt、日资金主图V5.txt、资金移动V5.txt、黄金摇钱树V7.txt |
| 短线打板 | 04_短线打板体系 | 买卖点V4.txt、多时间框架V8.txt、宝盆纳财V5.txt、涨停回马枪V5.txt、论坛尖刺V5.txt |
| 通用风控 | 05_通用风控模块 | 市场温度计V4.txt、总控面板V5.txt、持仓管理面板V4.txt、极限抄底V5.txt、波动率风险管理V4.txt |
| 选股指标 | 06_选股指标 | 三合一选股V4.txt、主力启动原版V4.txt、主力启动强化版V5.txt、强信号共振选股V5.txt、抄底.txt、超短打板选股V5.txt |

共 32 个公式文件。

### 2.2 其它入口与说明文件

| 路径 | 用途 |
|---|---|
| 通达信指标/add_zb.txt | 新增指标入口文件(现状名,Phase 2 Task 2.0 将统一为 add_new.txt) |
| 通达信指标/缠论副图.txt | 缠论副图公式(根目录散件) |
| tdx_v4_standalone/导入说明_必读.txt | 公式导入说明 |
| tdx_v4_standalone/99_说明手册/ | 买卖信号详解.txt、升级指南_V3到V4.txt、指标使用手册.txt、速查卡.txt |

## 三、数据域

### 3.1 K线库

- 路径:`/home/tdxback/aiagents-stock/tdx-data/database/kline/`(5604 个 .db,每票一个库,含 day/30minute/5minute 表;简报原记 5599 库,以 2026-09-26 盘点实测 5604 为准)
- 同目录:`codes.db`(证券代码表)、`workday.db`(交易日历);上层 `cron.out`、`update.log` 为更新日志
- 用途:本地行情唯一数据源,供全部分析/选股/信号模块取数
- 维护方式:tdx-api(Go 服务)pull-kline 增量拉取 + scheduler/update.sh 覆盖校验与补漏重拉
- 更新频率:每日 18:00(scheduler/crontab `0 18 * * *`,容器 TZ=Asia/Shanghai)

### 3.2 策略信号库(aiagents-stock/data/*.db)

- 路径:`/home/tdxback/aiagents-stock/data/*.db`(15 个)
- 用途:各策略/业务的信号与状态落库
- 维护方式:各 *_signal_db.py / *_db.py 模块读写
- 更新频率:随各策略扫描/监测任务

清单:chanlun_signals.db、chanlun_signals_intraday.db、combo_signals.db、liumai_signals.db、longhubang.db、low_price_bull_monitor.db、main_force_batch.db、news_flow.db、portfolio_stocks.db、profit_growth_monitor.db、qizhang_picks.db、sector_strategy.db、smart_monitor.db、stock_analysis.db、stock_monitor.db。

### 3.3 行业数据集

- 原路径:`/home/tdxback/tdxgp/a_shares_raw.json` → **已迁移/不存在(2026-09-26 盘点)**
- 实际路径:`/home/tdxback/通达信股票上下游分析/a_shares_raw.json`(A 股主营明细原始数据,约 960 KB,2026-09-18 更新);同目录另有产业链 xlsx/md 交付物(见 4.6)
- 用途:行业上下游/产业链分析数据源(industry_chain_ui 页面消费)
- 维护方式:1.3 节脚本抓取生成
- 更新频率:按需

### 3.4 研究挖掘数据(data/profit_mining)

- 路径:`/home/tdxback/aiagents-stock/data/profit_mining/`(223 个文件:csv/npz/json/日志/报告)
- 用途:特征构建、回测、维度挖掘、榜单分析的输入与中间产物(标签=信号后 20 交易日最高价≥买入价+10%;训练 1990-2024/测试 2025 起)
- 维护方式:数据文件由同目录脚本生成,DATA_FILES.md 打标登记(保留策略:功能在则不删)
- 更新频率:按需重跑覆盖

## 四、文档域

- 用途:项目说明、功能说明、配置指南、研究报告与交付物
- 维护方式:手工撰写为主,部分由脚本生成(generate_docs.py、export_watchlist_*.py)
- 更新频率:随功能/任务更新

| 位置 | 内容 | 数量(2026-09-26 实测) |
|---|---|---|
| aiagents-stock/docs/ | 功能说明/配置指南/部署文档;docs/plans/(1)、docs/specs/(3) 为计划与设计文档 | 73 个 .md |
| aiagents-stock/ 根目录 | README.md、BUILD_CN.md、CLAUDE.md、findings.md、progress.md、task_plan.md、新闻流量转化炒股法.md、新闻监测API调用说明.md | 8 个 .md |
| aiagents-stock/tdx-api/ | Go 服务 API 文档、部署文档 | 11 个 .md |
| 通达信py脚本/ | TQ提醒脚本使用说明.md、TQ确认信号使用说明.md、六脉缠论_信号说明_盘中提醒.md、六脉缠论_信号说明_盘后扫描.md | 4 个 .md |
| 通达信股票上下游分析/ | A股上下游业务往来.md、A股产业链总览.md、A股行业总览.md;交付物 xlsx:A股上下游业务往来.xlsx、A股产业链层级.xlsx、A股行业主营明细.xlsx | 3 个 .md + 3 个 .xlsx |
| 通达信指标/…/99_说明手册/ | 指标使用手册等(见 2.2) | 4 个 .txt |
| aiagents-stock/data/profit_mining/ | DATA_FILES.md 数据打标清单 + *_报告.md(回测/样本外检验/盈利方案等) | 15 个 .md |
| aiagents-stock/ops/ | README.md 运维说明 | 1 个 .md |

## 五、资产校验脚本

- 路径:`scripts/assets_check.py`
- 用法:`python3 scripts/assets_check.py`(一行输出五个资产域的文件数与最近修改时间戳)
- 校验根目录:aiagents-stock 代码、通达信脚本、指标库、K线库、行业数据集(原 /home/tdxback/tdxgp 已迁移/不存在,脚本指向实际路径 /home/tdxback/通达信股票上下游分析,见脚本内注释)
