# PostgreSQL 静态数据仓库（pg_warehouse）

## 1. 数据仓库用途

统一归档项目「行情基础数据」与「信号/分析数据」两大块，供**跨股、跨表、跨策略**的统一 SQL 查询与长期存档：

- **行情基础数据**：K 线日线 / 5 分钟 / 30 分钟，股票代码表，交易日历。
- **信号数据**：15 个信号库共 44 张表（缠论、组合、六脉、龙虎榜、低价牛、主力批量、舆情流、持仓、绩增、七章选股、板块策略、智能监控、股票分析、个股监控等）。

原始数据分散在一堆 SQLite 文件中（`tdx-data/database/*.db` 与 `data/*.db`），无法跨表 JOIN；本仓库将其统一灌入 PostgreSQL，成为长期可查、可归档的单一数据源。

## 2. Schema 分层

- `market` —— 行情基础数据（5 张表）：`stock_codes`（股票代码表）、`trade_calendar`（交易日历）、`kline_day`（日线）、`kline_5min`（5 分钟线）、`kline_30min`（30 分钟线）。
- `signals` —— 信号 / 分析数据（44 张表），按来源信号库分组，详见下表。

## 3. 表清单

### market（行情基础数据，5 张表）

| PG 表名 | 源 | 说明 |
| --- | --- | --- |
| `market.stock_codes` | `tdx-data/database/codes.db → codes` | 股票代码表 |
| `market.trade_calendar` | `tdx-data/database/workday.db → workday` | 交易日历 |
| `market.kline_day` | `tdx-data/database/kline/*.db → DayKline` | 日线 |
| `market.kline_5min` | `tdx-data/database/kline/*.db → Minute5Kline` | 5 分钟线 |
| `market.kline_30min` | `tdx-data/database/kline/*.db → Minute30Kline` | 30 分钟线 |

> K 线 3 张表均以每只股票一个源 `.db` 文件、按 `code` 维度聚合成单表（约 2 亿行总量）。

### signals（信号 / 分析数据，44 张表，按来源库分组）

| 来源信号库 | 表 |
| --- | --- |
| `data/chanlun_signals.db` | `chanlun_signals` |
| `data/chanlun_signals_intraday.db` | `chanlun_signals_intraday` |
| `data/combo_signals.db` | `combo_signals` |
| `data/liumai_signals.db` | `liumai_signals` |
| `data/longhubang.db` | `longhubang_records`、`longhubang_analysis`、`stock_tracking` |
| `data/low_price_bull_monitor.db` | `low_price_bull_monitored_stocks`、`low_price_bull_sell_alerts` |
| `data/main_force_batch.db` | `main_force_batch_analysis_history` |
| `data/news_flow.db` | `news_flow_snapshots`、`news_flow_platform_news`、`news_flow_stock_related_news`、`news_flow_hot_topics`、`news_flow_statistics`、`news_flow_sentiment_records`、`news_flow_alerts`、`news_flow_ai_analysis`、`news_flow_scheduler_logs`、`news_flow_alert_config`、`news_flow_keyword_rankings`、`news_flow_keyword_history` |
| `data/portfolio_stocks.db` | `portfolio_stocks`、`portfolio_analysis_history` |
| `data/profit_growth_monitor.db` | `profit_growth_monitored_stocks`、`profit_growth_sell_alerts` |
| `data/qizhang_picks.db` | `qizhang_daily_picks`、`qizhang_realized`、`qizhang_run_meta` |
| `data/sector_strategy.db` | `sector_raw_data`、`sector_news_data`、`sector_analysis_reports`、`sector_tracking`、`sector_data_versions` |
| `data/smart_monitor.db` | `smart_monitor_tasks`、`smart_monitor_ai_decisions`、`smart_monitor_trade_records`、`smart_monitor_position_monitor`、`smart_monitor_notifications`、`smart_monitor_system_logs` |
| `data/stock_analysis.db` | `stock_analysis_records` |
| `data/stock_monitor.db` | `stock_monitor_monitored_stocks`、`stock_monitor_price_history`、`stock_monitor_notifications` |

## 4. 查看字段注释

进入容器内 psql：

```bash
docker exec -it pg-warehouse psql -U stock -d stock_warehouse
```

然后查看某表结构与注释：

```sql
\d+ market.kline_day
```

## 5. 全量导入（幂等，重建表）

```bash
cd pg_warehouse
PG_HOST=localhost python3 import_all.py
```

说明：

- 先 `DROP` 再重建 `market` 与 `signals` 下的全部表，随后从各源 SQLite 全量灌入，**幂等**（连跑两次不会数据翻倍）。
- 无 `localhost` 场景（如在校验服务器或在容器内直连）时，请将 `PG_HOST` 指向可解析的 PG 主机。
- 全量导入约需 10–30 分钟（约 2 亿行 K 线），期间会输出导入进度日志。

## 6. 增量同步（幂等）

```bash
cd pg_warehouse
PG_HOST=localhost python3 sync_daily.py
```

说明：

- **幂等**：连跑两次，第二次新增为 0。
- qizhang 三表（`qizhang_daily_picks` / `qizhang_realized` / `qizhang_run_meta`）走**全量覆盖**，其余表按主键 `ON CONFLICT` 增量/去重。

## 7. 调度说明

`pg-sync-updater` sidecar 容器每天 **21:00** 自动触发增量同步。由于依赖各上游日程，实际同步在各来源之后进行：

- K 线：18:00 后
- 缠论：20:00 后
- 七章（qizhang）选股：20:30 后

`sync_daily.py` 的幂等特性保证即便调度与上游时间有偏差、重复触发，也不会产生重复数据。

## 8. 连接方式

宿主机（本机）直连：

```bash
psql -h localhost -p 5432 -U stock -d stock_warehouse
```

- 用户名 `stock`，库名 `stock_warehouse`，端口 5432。
- 密码见项目根目录 `.env` 中的 `PG_PASSWORD`（不写入本文件）。

容器内（如 `pg-warehouse` 容器）连接时，host 用 `postgres` 而非 `localhost`。

## 9. 数据类型口径（导入时已做统一转换）

| 源类型 | 转换后 | 说明 |
| --- | --- | --- |
| 价格（Open/High/Low/Close 等） | `NUMERIC`（元） | 源为 ×1000 的整数，已除以 1000 转成元 |
| 金额 `Amount` | `NUMERIC`（元） | 源为 ×1000 的整数，已转成元 |
| Unix 秒（K 线 `Date`、`InDate`、`EditDate`、`Unix`、股票表 `EditDate`/`InDate`） | `timestamptz`（Asia/Shanghai） | 由 Unix 秒转时间戳 |
| 信号库 `TIMESTAMP` 字段（源实际为本地时间 TEXT 字符串） | `timestamptz` | 用文本转换逻辑 `to_tstamp_str` 处理，与 K 线 `to_ts` 不同源 |
| `BOOLEAN` 0/1 | `boolean` | 源 0/1 转 PG 布尔 |

## 10. 相关文件

- `schema.sql` —— market schema（含建表 DDL 与唯一索引）。
- `db.py` / `convert.py` —— 连接管理与类型转换逻辑。
- `import_all.py` —— 全量导入入口。
- `sync_daily.py` —— 增量同步入口。
