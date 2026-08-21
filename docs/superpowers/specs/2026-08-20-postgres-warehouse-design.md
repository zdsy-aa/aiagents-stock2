# PostgreSQL 静态数据仓库 设计文档

> 日期：2026-08-20
> 状态：待评审
> 范围：新增一个独立的 PostgreSQL 数据仓库，把项目内「行情基础数据 + 全部信号库」一次性导入并存档，之后每日增量同步。现有生产代码**零改动**（继续读写 SQLite），新库独立、只读、可查询、可分析。

---

## 1. 背景与目标

项目当前数据分散在多处 SQLite：

- **行情基础数据** `tdx-data/database/`：5579 个 `kline/<code>.db`（每股一文件，各含 `DayKline` / `Minute5Kline` / `Minute30Kline` 三表），外加 `codes.db`（5.4 万行股票代码表）、`workday.db`（交易日历）。
- **信号/分析数据** `data/*.db`：15 个策略库、约 40 张表（缠论、六脉、组合、龙虎榜、新闻流、主力、组合管理、起涨、板块、智能监控等）。

这些数据是「只读参考 / 历史存档」性质，但散在 5579 个文件里，难以跨股、跨表、跨策略做统一查询与分析。

**目标**：建一个干净、字段有中文注释的 PostgreSQL 数据仓库，把这些数据合并归档，支持：
1. 统一 SQL 查询（跨股、跨时间、跨信号）；
2. 长期存档与备份；
3. 每日增量同步，持续可用。

**非目标**：不替换现有 SQLite，不改动任何生产代码路径（kline 拉取、盘中选股、各策略写库逻辑全部保持不变）。

---

## 2. 选型理由（PostgreSQL）

- 用户明确指定 PostgreSQL。
- 数据规模约 **2.2 亿行**（K 线）+ 5.4 万代码 + 交易日历 + ~40 张信号表。PG 对该量级分析查询成熟稳定。
- 原生支持 `COMMENT ON` 表/列注释，满足「表要有清晰注释」的硬性要求。
- 独立服务，可被 psql / 其他工具 / 后续代码直接连接。

---

## 3. 架构总览

新增一个 `pg_warehouse/` 目录承载全部脚本与文档，并在现有 `docker-compose.yml` 增加一个 PostgreSQL 服务、一个每日同步 sidecar 容器。

```
aiagents-stock/
├── docker-compose.yml          # 增 postgres 服务 + pg-sync-updater sidecar（改动）
├── .env                        # 增 PG_* 配置变量（改动）
├── .env.example                # 同步增 PG_* 示例（改动）
├── pg_warehouse/               # 新增目录
│   ├── schema.sql              # 建库/建表/建索引/全部 COMMENT（DDL）
│   ├── import_all.py           # 全量导入（一次性）
│   ├── sync_daily.py           # 每日增量同步
│   ├── sync_schedule.sh        # sidecar 调度入口
│   └── README.md               # 使用说明
└── (现有代码全部不动)
```

---

## 4. PostgreSQL 部署（Docker）

在 `docker-compose.yml` 的 `services:` 下新增：

```yaml
postgres:
  image: postgres:16
  container_name: pg-warehouse
  logging: *default-logging
  environment:
    - TZ=Asia/Shanghai
    - POSTGRES_USER=${PG_USER}
    - POSTGRES_PASSWORD=${PG_PASSWORD}
    - POSTGRES_DB=${PG_DB}
  volumes:
    - ./pgdata:/var/lib/postgresql/data   # 持久化，防重建丢失
  ports:
    - "5432:5432"                          # 宿主机 psql/工具直连
  restart: unless-stopped
  networks:
    - agentsstock-network
  healthcheck:
    test: ["CMD-SHELL", "pg_isready -U ${PG_USER} -d ${PG_DB}"]
    interval: 10s
    timeout: 5s
    retries: 5
    start_period: 10s
```

`.env` / `.env.example` 新增（示例值）：

```
PG_USER=stock
PG_PASSWORD=<生成强密码>
PG_DB=stock_warehouse
```

`.gitignore` **新增** `pgdata/`（当前未忽略，需补一行，避免提交数据库数据卷）。

---

## 5. Schema 设计

两个 schema 分层：`market`（行情基础数据）、`signals`（信号/分析数据）。

### 5.1 `market` schema

| 表 | 来源 | 行数级 | 说明 |
|---|---|---|---|
| `stock_codes` | codes.db | 5.4 万 | 股票代码表 |
| `trade_calendar` | workday.db | 数千 | 交易日历 |
| `kline_day` | 5579 个 kline/*.db 的 DayKline | ~4700 万 | 日线（合并加 code 列） |
| `kline_5min` | Minute5Kline | ~1.5 亿 | 5 分钟线 |
| `kline_30min` | Minute30Kline | ~2500 万 | 30 分钟线 |

**K 线合并**：5579 个文件合并成 3 张大表，每行新增 `code` 列；`(code, ts)` 建联合唯一索引（增量去重的依据）。

### 5.2 `signals` schema

每个信号库对应同名表，表名沿用原 SQLite 表名（`sqlite_sequence` 系统表跳过）。共约 40 张表：

- `chanlun_signals`、`chanlun_signals_intraday`（缠论信号，表名 `signals` 加前缀区分）
- `combo_signals`、`liumai_signals`
- `longhubang_records`、`longhubang_analysis`、`stock_tracking`
- `low_price_bull_monitored_stocks`、`low_price_bull_sell_alerts`
- `main_force_batch_analysis_history`
- `news_flow_*`（12 表：snapshots/platform_news/stock_related_news/hot_topics/statistics/sentiment/alerts/ai_analysis/scheduler_logs/alert_config/keyword_rankings/keyword_history）
- `portfolio_stocks`、`portfolio_analysis_history`
- `profit_growth_*`、`qizhang_*`（daily_picks/realized/run_meta）
- `sector_*`（raw_data/news_data/analysis_reports/tracking/data_versions）
- `smart_monitor_*`、`stock_analysis_records`、`stock_monitor_*`

> 命名冲突处理：多个库都有 `monitored_stocks`、`sell_alerts`、`notifications` 等同名表，统一加**来源前缀**（如 `low_price_bull_monitored_stocks`）避免冲突。信号库单表主键 `id` 在 PG 中重建为 `BIGSERIAL`，原 `id` 值保留导入。

### 5.3 注释规范

- 每张表 `COMMENT ON TABLE`：中文，说明数据来源、含义、更新频率。
- 每个字段 `COMMENT ON COLUMN`：中文，说明含义 + 口径（如「价格，单位元（源存储为 ×1000 整数）」「bar 时间戳，UTC+8」）。
- 主键/外键/索引命名统一，DDL 内联注释。

---

## 6. 数据类型规范化（易读）

原则：**只对「编码严重、不直观」的字段做规范化**；信号库本就以 TEXT/REAL 存字符串，基本照搬，避免过度转换。

### 6.1 K 线表（编码最严重，重点转换）

| 源字段 | 源类型 | PG 类型 | 说明 |
|---|---|---|---|
| `Code` | TEXT | `TEXT` | 股票代码 |
| `Date` | INTEGER（Unix 秒） | `TIMESTAMPTZ` | bar 时间戳，源为 Unix 秒，UTC+8 |
| `Open/High/Low/Close` | INTEGER（×1000） | `NUMERIC(16,3)` | 价格，单位元（源存储为 ×1000 整数） |
| `Volume` | INTEGER | `BIGINT` | 成交量（手/股，随源） |
| `Amount` | INTEGER | `NUMERIC(20,2)` | 成交额，单位元 |
| `InDate` | INTEGER（Unix 秒） | `TIMESTAMPTZ` | 入库时间戳 |

### 6.2 codes / workday

- Unix 秒字段（`EditDate`、`InDate`、`Unix`）→ `TIMESTAMPTZ`；`Date`（TEXT 日期）→ `DATE`；其余照搬。

### 6.3 信号库

- `TEXT` 日期/时间字符串照搬为 `TEXT`（已是 ISO 可读字符串，不强行转）。
- `BOOLEAN` 字段（SQLite 存 0/1）→ `BOOLEAN`。
- `TIMESTAMP` 字段 → `TIMESTAMPTZ`。
- 其余 REAL/INTEGER/TEXT 照搬。

---

## 7. 导入与增量同步

### 7.1 全量导入 `import_all.py`

1. 连接 PG（读 `.env` 的 `PG_*`）。
2. 执行 `schema.sql` 建表（幂等：`DROP ... IF EXISTS` 后重建，或首次空库）。
3. **K 线**：逐股读 SQLite → pandas 批量 → `COPY` 写入，带进度日志 + 单股失败不中断（记录到错误清单）。
   - 预计 2.2 亿行，`COPY` 批量约 10–30 分钟。
4. **codes / workday**：直接读入。
5. **信号库**：逐表读入（数据量小，秒级）。
6. 输出汇总：每表导入行数 + 失败清单。

### 7.2 每日增量 `sync_daily.py`

对每张表按「源时间字段」做增量对比，只追加 `> PG 当前 max` 的新行：

- K 线：按 `code` 各自对比 `max(ts)`，追加新 bar（兼容停牌/落后票）。
- 信号库：按主键 `id` 或时间字段对比追加。
- 幂等：`(code, ts)` 唯一索引 + `ON CONFLICT DO NOTHING`，重复跑安全。

### 7.3 调度 sidecar `pg-sync-updater`

- **复用主应用镜像**（`aiagents-stock-app`），与现有 `chanlun-updater` / `qizhang-updater` sidecar 完全同模式：仅挂卷 + 改启动命令，不单独构建镜像。
- 镜像内运行 `pg_warehouse/sync_schedule.sh`（内部用 python 定时循环或 crond，触发 `sync_daily.py`）。
- 挂载：`./pg_warehouse:/app/pg_warehouse:ro`（脚本）、`./tdx-data:/app/tdx-data:ro`、`./data:/app/data:ro`（源数据只读）、`./.env:/app/.env`（PG 连接配置）。
- 调度时间：**每天 21:00**（晚于 kline 18:00、缠论 20:00、起涨 20:30，保证所有源数据已更新）。
- 依赖：`postgres` service healthy；本容器不跑 streamlit，`healthcheck: disable: true`（与 chanlun/qizhang-updater 一致）。

> **新增 Python 依赖**：`psycopg2-binary` 加入 `requirements.txt`（主应用镜像重建后可用）。这只新增一个 pip 包，**不改动任何现有代码逻辑**。

---

## 8. 风险与对策

| 风险 | 对策 |
|---|---|
| 导入耗时 10–30 分钟 | `COPY` 批量 + 进度日志 + 断点续传（按已导入股跳过） |
| 磁盘占用 15–25 GB | 导入前 `df` 检查剩余空间，不足则告警退出 |
| 停牌/退市股 K 线落后 | 增量按 `code` 各自对比 max，天然兼容 |
| 信号库表名冲突 | 加来源前缀，命名见 5.2 |
| 源数据被 SQLite 写锁 | 导入脚本只读打开 SQLite（`file:...?mode=ro`），不阻塞生产写 |

---

## 9. 验收标准

1. `docker compose up -d postgres` 后 `pg_isready` 健康，`psql` 可连。
2. 全量导入后，`market` 3 张 K 线表总行数 ≈ 2.2 亿（与源 SQLite 行数核对一致）；`signals` 各表行数与源库一致。
3. 所有表/列均有中文 `COMMENT`，可 `\d+` 查看。
4. 抽查：某只票的 `kline_day` 行数 = 对应 SQLite `DayKline` 行数；价格值 = 源值 ÷ 1000。
5. 连续跑两次 `sync_daily.py`，第二次 0 新增（幂等验证）。
6. 现有生产功能（streamlit 页面、kline 更新、盘中选股）不受影响。

---

## 10. 待办（不在本次范围）

- 前台查询页面（把 PG 仓库接到 streamlit 展示）——后续单独需求。
- 历史数据跨库 JOIN 分析应用——后续。
