# PostgreSQL 静态数据仓库 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增一个独立的 PostgreSQL 数据仓库，把项目内「行情基础数据 + 15 个信号库」一次性导入并存档，之后每日 21:00 增量同步。

**Architecture:** docker-compose 加一个 `postgres:16` 服务 + 一个复用主应用镜像的 `pg-sync-updater` sidecar；`pg_warehouse/` 目录承载 schema.sql、类型/值转换纯函数、全量导入、增量同步、调度循环。现有生产代码零改动，只新增 `psycopg2-binary` 依赖。

**Tech Stack:** PostgreSQL 16、psycopg2-binary、Python 3（pandas、pytz 已有）、docker-compose。

**Spec:** `docs/superpowers/specs/2026-08-20-postgres-warehouse-design.md`

## Global Constraints

- PostgreSQL 16（`postgres:16` 镜像），数据卷 `./pgdata:/var/lib/postgresql/data` 持久化，端口 5432。
- Schema 分层：`market`（行情基础数据）、`signals`（信号/分析数据）。
- 所有表、所有字段都必须有中文 `COMMENT`。
- K 线：源 `Date` 为 Unix 秒（UTC+8）→ `TIMESTAMPTZ`；`Open/High/Low/Close` 为 ×1000 整数 → `NUMERIC(12,3)`（单位元）；`Volume`→`BIGINT`；`Amount`→`NUMERIC(20,2)`（单位元）。
- 信号库：`BOOLEAN` 字段（源 0/1）→ `BOOLEAN`；`TIMESTAMP` 字段 → `TIMESTAMPTZ`；其余 REAL/INTEGER/TEXT 照搬（REAL→`DOUBLE PRECISION`，INTEGER→`BIGINT`，TEXT→`TEXT`）。
- 现有生产代码（streamlit 页面、kline 更新、盘中选股、各策略写库）**一律不改**。
- 连接配置统一从 `.env` 读 `PG_HOST/PG_PORT/PG_USER/PG_PASSWORD/PG_DB`。
- 增量同步必须幂等：连跑两次，第二次 0 新增。
- 中文注释面向用户输出一律中文。

---

### Task 1: 基础设施配置（.env / requirements / .gitignore / docker-compose postgres 服务）

**Files:**
- Modify: `.env`（末尾追加 5 个 PG_* 变量）
- Modify: `.env.example`（末尾追加同样 5 个示例变量）
- Modify: `requirements.txt`（追加 psycopg2-binary）
- Modify: `.gitignore`（追加 pgdata/）
- Modify: `docker-compose.yml`（services 下加 postgres 服务）

**Interfaces:**
- Produces: `.env` 提供 `PG_HOST=localhost`、`PG_PORT=5432`、`PG_USER`、`PG_PASSWORD`、`PG_DB=stock_warehouse`（后续所有脚本 `os.getenv` 读取）。docker 网络内 sidecar 用 `PG_HOST=postgres`（容器服务名），宿主机脚本用 `localhost`——用环境变量覆盖解决，默认值写 `localhost`。

- [ ] **Step 1: .env / .env.example 追加 PG 配置**

`.env` 末尾追加（生成一个强密码替换 `<生成强密码>`）：

```bash
# ===== PostgreSQL 静态数据仓库 =====
PG_HOST=localhost
PG_PORT=5432
PG_USER=stock
PG_PASSWORD=<生成强密码>
PG_DB=stock_warehouse
```

`.env.example` 末尾追加同样内容但密码写占位 `PG_PASSWORD=change_me`。

- [ ] **Step 2: requirements.txt 追加 psycopg2-binary**

文件末尾追加一行：

```
psycopg2-binary==2.9.10
```

- [ ] **Step 3: .gitignore 追加 pgdata/**

在 `# 运行期数据库（bind-mount，不入库）` 附近追加一行：

```
# PostgreSQL 数据卷（不入库）
pgdata/
```

- [ ] **Step 4: docker-compose.yml 加 postgres 服务**

在 `services:` 块末尾、`networks:` 之前插入：

```yaml
  # PostgreSQL 静态数据仓库：行情 K 线（日线/5分钟/30分钟）+ 各信号库的统一归档与查询库。
  # 由 pg-sync-updater 每天 21:00 增量同步；宿主机 5432 端口可 psql 直连。
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
      - ./pgdata:/var/lib/postgresql/data
    ports:
      - "5432:5432"
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

- [ ] **Step 5: 校验 compose 配置**

Run: `docker compose config -q`
Expected: 无输出（退出码 0）。

- [ ] **Step 6: 启动 postgres 并验证健康**

Run: `docker compose up -d postgres && sleep 8 && docker ps --filter name=pg-warehouse --format '{{.Status}}'`
Expected: 状态含 `(healthy)` 或 `(starting)`；再跑 `docker exec pg-warehouse pg_isready -U stock -d stock_warehouse` 输出 `... accepting connections`。

- [ ] **Step 7: Commit**

```bash
git add .env.example requirements.txt .gitignore docker-compose.yml
git commit -m "feat(pg-warehouse): 新增 postgres 服务与连接配置"
```

> 注：`.env` 不入库（.gitignore 已忽略），只提交 `.env.example`。

---

### Task 2: schema.sql（market 5 表完整 DDL + 注释 + 索引）与 convert.py（转换纯函数）

**Files:**
- Create: `pg_warehouse/schema.sql`
- Create: `pg_warehouse/convert.py`
- Test: `pg_warehouse/tests/test_convert.py`

**Interfaces:**
- Produces `convert.py` 纯函数（Task 3/4 依赖，签名固定）：
  - `to_ts(unix_sec: int) -> datetime`：Unix 秒 → aware datetime（`Asia/Shanghai`）。None/空 → None。
  - `to_price(v: int | None) -> float | None`：×1000 整数 → 元（`v / 1000.0`）。
  - `to_bool(v) -> bool`：源 0/1 → `False/True`；None → None。
  - `sqlite_to_pg_type(col_type: str) -> str`：`'INTEGER'`→`'BIGINT'`、`'REAL'`→`'DOUBLE PRECISION'`、`'TEXT'`→`'TEXT'`、`'BOOLEAN'`→`'BOOLEAN'`、`'TIMESTAMP'`→`'TIMESTAMPTZ'`、含 `'VARCHAR'/'CHAR'`→`'TEXT'`；未知→`'TEXT'`。
  - `TABLE_COMMENTS: dict[str, str]`、`COLUMN_COMMENTS: dict[str, str]`（Task 3 signals 建表用）。
- Produces `schema.sql`：market 5 表 `stock_codes/trade_calendar/kline_day/kline_5min/kline_30min` 完整 DDL。

- [ ] **Step 1: 写 convert.py 的失败测试**

`pg_warehouse/tests/test_convert.py`：

```python
import datetime
from zoneinfo import ZoneInfo
from convert import to_ts, to_price, to_bool, sqlite_to_pg_type

def test_to_ts():
    # 2024-05-13 21:35:00 UTC = 1715650500
    out = to_ts(1715650500)
    assert out == datetime.datetime(2024, 5, 13, 21, 35, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert to_ts(None) is None

def test_to_price():
    assert to_price(11390) == 11.39
    assert to_price(0) == 0.0
    assert to_price(None) is None

def test_to_bool():
    assert to_bool(1) is True
    assert to_bool(0) is False
    assert to_bool(None) is None

def test_sqlite_to_pg_type():
    assert sqlite_to_pg_type("INTEGER") == "BIGINT"
    assert sqlite_to_pg_type("REAL") == "DOUBLE PRECISION"
    assert sqlite_to_pg_type("TEXT") == "TEXT"
    assert sqlite_to_pg_type("BOOLEAN") == "BOOLEAN"
    assert sqlite_to_pg_type("TIMESTAMP") == "TIMESTAMPTZ"
    assert sqlite_to_pg_type("VARCHAR(20)") == "TEXT"
    assert sqlite_to_pg_type("SOMETHING_WEIRD") == "TEXT"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd pg_warehouse && python -m pytest tests/test_convert.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'convert'`（或函数未定义）。

- [ ] **Step 3: 实现 convert.py**

```python
"""类型/值转换纯函数 + 表/列中文注释字典。供 import_all.py / sync_daily.py 复用。"""
import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")

def to_ts(unix_sec):
    if unix_sec is None or unix_sec == "":
        return None
    return datetime.datetime.fromtimestamp(int(unix_sec), tz=TZ)

def to_price(v):
    if v is None or v == "":
        return None
    return float(v) / 1000.0

def to_bool(v):
    if v is None or v == "":
        return None
    return bool(int(v))

def sqlite_to_pg_type(col_type):
    t = (col_type or "").upper()
    if t.startswith("INT") or t == "INTEGER":
        return "BIGINT"
    if t in ("REAL", "FLOAT", "DOUBLE", "NUMERIC", "DECIMAL"):
        return "DOUBLE PRECISION"
    if t == "BOOLEAN" or t == "BOOL":
        return "BOOLEAN"
    if t in ("TIMESTAMP", "DATETIME"):
        return "TIMESTAMPTZ"
    return "TEXT"
```

`TABLE_COMMENTS` 与 `COLUMN_COMMENTS` 在 Step 5 一并写入（本 Step 先留两个空 dict 占位以通过导入，Step 5 填全）。

- [ ] **Step 4: 运行测试验证通过**

Run: `cd pg_warehouse && python -m pytest tests/test_convert.py -v`
Expected: 4 个测试 PASS。

- [ ] **Step 5: 写 schema.sql（market 5 表）**

`pg_warehouse/schema.sql`：

```sql
-- PostgreSQL 静态数据仓库 DDL（market schema：行情基础数据）
-- 执行：psql "$PG_DB" -f schema.sql（首次空库；重复执行用 import_all.py 的幂等重建）

-- ============ stock_codes：股票代码表（源 codes.db 的 codes 表） ============
CREATE TABLE IF NOT EXISTS market.stock_codes (
    id             BIGINT,
    name           TEXT,      -- 证券名称
    code           TEXT,      -- 代码（注意：codes.db 中 000001 可能是上证指数 sh，与 kline 目录的 000001.db 深市平安银行非同一标识体系，二者独立不 JOIN）
    exchange       TEXT,      -- 交易所：sh/sz/bj
    multiple       INTEGER,   -- 价格倍数（100=价格÷100）
    decimal_places INTEGER,   -- 小数位数
    last_price     DOUBLE PRECISION, -- 最新价（元）
    edit_date      TIMESTAMPTZ,      -- 编辑时间（源 Unix 秒）
    in_date        TIMESTAMPTZ       -- 入库时间（源 Unix 秒）
);
COMMENT ON TABLE  market.stock_codes IS '股票代码表（源 tdx-data/database/codes.db，约 5.4 万行，含指数与证券）。';
COMMENT ON COLUMN market.stock_codes.code        IS '证券代码';
COMMENT ON COLUMN market.stock_codes.name        IS '证券名称';
COMMENT ON COLUMN market.stock_codes.exchange    IS '交易所标识：sh=上交所，sz=深交所，bj=北交所';
COMMENT ON COLUMN market.stock_codes.multiple    IS '价格倍数（如 100 表示实际价=存储价/100）';
COMMENT ON COLUMN market.stock_codes.decimal_places IS '价格小数位数';
COMMENT ON COLUMN market.stock_codes.last_price  IS '最新价（元）';
COMMENT ON COLUMN market.stock_codes.edit_date   IS '最后编辑时间（源为 Unix 秒，UTC+8）';
COMMENT ON COLUMN market.stock_codes.in_date     IS '入库时间（源为 Unix 秒，UTC+8）';

-- ============ trade_calendar：交易日历（源 workday.db 的 workday 表） ============
CREATE TABLE IF NOT EXISTS market.trade_calendar (
    id   BIGINT,
    ts   TIMESTAMPTZ,  -- 交易日（源 Unix 秒）
    date DATE          -- 交易日日期（源 TEXT 'YYYYMMDD' 或 'YYYY-MM-DD'）
);
COMMENT ON TABLE  market.trade_calendar IS '交易日历（源 tdx-data/database/workday.db）。';
COMMENT ON COLUMN market.trade_calendar.ts   IS '交易日时间戳（源为 Unix 秒，UTC+8）';
COMMENT ON COLUMN market.trade_calendar.date IS '交易日日期';

-- ============ kline_day：日线（5579 个 kline/*.db 的 DayKline 合并，加 code 列） ============
CREATE TABLE IF NOT EXISTS market.kline_day (
    code     TEXT,          -- 股票代码（源文件名前缀，如 000001/600519/bj920000）
    ts       TIMESTAMPTZ,   -- bar 时间戳（源 Date，Unix 秒，UTC+8）
    open     NUMERIC(12,3), -- 开盘价（元；源存储为 ×1000 整数）
    high     NUMERIC(12,3), -- 最高价（元）
    low      NUMERIC(12,3), -- 最低价（元）
    close    NUMERIC(12,3), -- 收盘价（元）
    volume   BIGINT,        -- 成交量
    amount   NUMERIC(20,2), -- 成交额（元）
    in_date  TIMESTAMPTZ    -- 入库时间（源 InDate，Unix 秒）
);
COMMENT ON TABLE  market.kline_day IS 'A股日线（源 tdx-data/database/kline/*.db 的 DayKline，按 code 合并）。';
COMMENT ON COLUMN market.kline_day.code    IS '股票代码';
COMMENT ON COLUMN market.kline_day.ts      IS 'bar 时间戳（源 Date，Unix 秒，UTC+8）';
COMMENT ON COLUMN market.kline_day.open    IS '开盘价（元；源存储为 ×1000 整数）';
COMMENT ON COLUMN market.kline_day.high    IS '最高价（元）';
COMMENT ON COLUMN market.kline_day.low     IS '最低价（元）';
COMMENT ON COLUMN market.kline_day.close   IS '收盘价（元）';
COMMENT ON COLUMN market.kline_day.volume  IS '成交量';
COMMENT ON COLUMN market.kline_day.amount  IS '成交额（元）';
COMMENT ON COLUMN market.kline_day.in_date IS '入库时间（源 InDate，Unix 秒）';
CREATE UNIQUE INDEX IF NOT EXISTS kline_day_code_ts ON market.kline_day (code, ts);

-- ============ kline_5min：5分钟线 ============
CREATE TABLE IF NOT EXISTS market.kline_5min (
    code     TEXT,
    ts       TIMESTAMPTZ,
    open     NUMERIC(12,3),
    high     NUMERIC(12,3),
    low      NUMERIC(12,3),
    close    NUMERIC(12,3),
    volume   BIGINT,
    amount   NUMERIC(20,2),
    in_date  TIMESTAMPTZ
);
COMMENT ON TABLE  market.kline_5min IS 'A股5分钟线（源 kline/*.db 的 Minute5Kline，按 code 合并）。';
COMMENT ON COLUMN market.kline_5min.code    IS '股票代码';
COMMENT ON COLUMN market.kline_5min.ts      IS 'bar 时间戳（源 Date，Unix 秒，UTC+8）';
COMMENT ON COLUMN market.kline_5min.open    IS '开盘价（元；源存储为 ×1000 整数）';
COMMENT ON COLUMN market.kline_5min.high    IS '最高价（元）';
COMMENT ON COLUMN market.kline_5min.low     IS '最低价（元）';
COMMENT ON COLUMN market.kline_5min.close   IS '收盘价（元）';
COMMENT ON COLUMN market.kline_5min.volume  IS '成交量';
COMMENT ON COLUMN market.kline_5min.amount  IS '成交额（元）';
COMMENT ON COLUMN market.kline_5min.in_date IS '入库时间（源 InDate，Unix 秒）';
CREATE UNIQUE INDEX IF NOT EXISTS kline_5min_code_ts ON market.kline_5min (code, ts);

-- ============ kline_30min：30分钟线 ============
CREATE TABLE IF NOT EXISTS market.kline_30min (
    code     TEXT,
    ts       TIMESTAMPTZ,
    open     NUMERIC(12,3),
    high     NUMERIC(12,3),
    low      NUMERIC(12,3),
    close    NUMERIC(12,3),
    volume   BIGINT,
    amount   NUMERIC(20,2),
    in_date  TIMESTAMPTZ
);
COMMENT ON TABLE  market.kline_30min IS 'A股30分钟线（源 kline/*.db 的 Minute30Kline，按 code 合并）。';
COMMENT ON COLUMN market.kline_30min.code    IS '股票代码';
COMMENT ON COLUMN market.kline_30min.ts      IS 'bar 时间戳（源 Date，Unix 秒，UTC+8）';
COMMENT ON COLUMN market.kline_30min.open    IS '开盘价（元；源存储为 ×1000 整数）';
COMMENT ON COLUMN market.kline_30min.high    IS '最高价（元）';
COMMENT ON COLUMN market.kline_30min.low     IS '最低价（元）';
COMMENT ON COLUMN market.kline_30min.close   IS '收盘价（元）';
COMMENT ON COLUMN market.kline_30min.volume  IS '成交量';
COMMENT ON COLUMN market.kline_30min.amount  IS '成交额（元）';
COMMENT ON COLUMN market.kline_30min.in_date IS '入库时间（源 InDate，Unix 秒）';
CREATE UNIQUE INDEX IF NOT EXISTS kline_30min_code_ts ON market.kline_30min (code, ts);
```

- [ ] **Step 6: 填全 convert.py 的 TABLE_COMMENTS / COLUMN_COMMENTS**

在 `convert.py` 末尾追加（供 Task 3 signals 自动建表 + 加注释用）：

```python
# 信号库表名 -> 中文注释（源 data/*.db 的各表，加来源前缀后的 PG 表名见 import_all.SIGNAL_DBS）
TABLE_COMMENTS = {
    "chanlun_signals": "缠论买点信号（源 data/chanlun_signals.db 的 signals 表）",
    "chanlun_signals_intraday": "缠论盘中买点信号（源 data/chanlun_signals_intraday.db 的 signals 表）",
    "combo_signals": "缠论+六脉组合信号（源 data/combo_signals.db 的 combo_signals 表）",
    "liumai_signals": "六脉神剑信号（源 data/liumai_signals.db 的 liumai_signals 表）",
    "longhubang_records": "龙虎榜明细（源 data/longhubang.db）",
    "longhubang_analysis": "龙虎榜分析结论",
    "stock_tracking": "龙虎榜推荐股票跟踪",
    "low_price_bull_monitored_stocks": "低价牛股监控股票池（源 low_price_bull_monitor.db 的 monitored_stocks）",
    "low_price_bull_sell_alerts": "低价牛股卖出告警（源 low_price_bull_monitor.db 的 sell_alerts）",
    "main_force_batch_analysis_history": "主力批量分析历史（源 main_force_batch.db）",
    "news_flow_snapshots": "新闻流抓取快照（源 news_flow.db）",
    "news_flow_platform_news": "平台新闻",
    "news_flow_stock_related_news": "个股关联新闻",
    "news_flow_hot_topics": "热点话题",
    "news_flow_statistics": "新闻流统计",
    "news_flow_sentiment_records": "情绪记录",
    "news_flow_alerts": "新闻流告警",
    "news_flow_ai_analysis": "AI 分析结论",
    "news_flow_scheduler_logs": "新闻流调度日志",
    "news_flow_alert_config": "告警配置",
    "news_flow_keyword_rankings": "关键词排行",
    "news_flow_keyword_history": "关键词历史",
    "portfolio_stocks": "自选组合股票（源 portfolio_stocks.db）",
    "portfolio_analysis_history": "自选组合分析历史",
    "profit_growth_monitored_stocks": "利润增长监控股票池（源 profit_growth_monitor.db）",
    "profit_growth_sell_alerts": "利润增长卖出告警",
    "qizhang_daily_picks": "起涨预测每日选股（源 qizhang_picks.db 的 daily_picks）",
    "qizhang_realized": "起涨预测已兑现记录",
    "qizhang_run_meta": "起涨预测运行元信息",
    "sector_raw_data": "板块行情原始数据（源 sector_strategy.db）",
    "sector_news_data": "板块新闻数据",
    "sector_analysis_reports": "板块分析报告",
    "sector_tracking": "板块推荐跟踪",
    "sector_data_versions": "板块数据版本",
    "smart_monitor_tasks": "智能监控任务（源 smart_monitor.db 的 monitor_tasks）",
    "smart_monitor_ai_decisions": "智能监控 AI 决策",
    "smart_monitor_trade_records": "智能监控交易记录",
    "smart_monitor_position_monitor": "智能监控持仓",
    "smart_monitor_notifications": "智能监控通知",
    "smart_monitor_system_logs": "智能监控系统日志",
    "stock_analysis_records": "个股分析记录（源 stock_analysis.db 的 analysis_records）",
    "stock_monitor_monitored_stocks": "个股监控池（源 stock_monitor.db 的 monitored_stocks）",
    "stock_monitor_price_history": "个股监控价格历史",
    "stock_monitor_notifications": "个股监控通知",
}

# 通用列名 -> 中文注释（跨表复用；未命中的列名兜底注释为列名本身）
COLUMN_COMMENTS = {
    "id": "自增主键", "code": "股票代码", "name": "名称", "symbol": "股票代码",
    "board": "板块", "level": "级别", "scan_date": "扫描日期", "signal_type": "信号类型",
    "signal_date": "信号日期", "buy_price": "买入价", "buy_reason": "买入理由",
    "stop_loss": "止损价", "sell_type": "卖出类型", "sell_date": "卖出日期",
    "sell_reason": "卖出理由", "chanlun_type": "缠论买点类型", "chanlun_date": "缠论买点日期",
    "liumai_date": "六脉信号日期", "liumai_bull_count": "六脉看多计数", "liumai_score": "六脉得分",
    "bull_count": "看多计数", "score": "得分", "state": "状态", "macd": "MACD 信号",
    "kdj": "KDJ 信号", "rsi": "RSI 信号", "lwr": "LWR 信号", "bbi": "BBI 信号", "mtm": "MTM 信号",
    "date": "日期", "stock_code": "股票代码", "stock_name": "股票名称", "youzi_name": "游资名称",
    "yingye_bu": "营业部", "list_type": "上榜类型", "buy_amount": "买入额", "sell_amount": "卖出额",
    "net_inflow": "净流入", "concepts": "概念", "created_at": "创建时间", "analysis_date": "分析日期",
    "data_date_range": "数据日期范围", "analysis_content": "分析内容", "recommended_stocks": "推荐股票",
    "summary": "摘要", "analysis_id": "分析记录ID", "recommended_date": "推荐日期",
    "recommended_price": "推荐价", "target_price": "目标价", "stop_loss_price": "止损价",
    "current_price": "现价", "profit_loss_pct": "盈亏百分比", "status": "状态", "notes": "备注",
    "updated_at": "更新时间", "buy_date": "买入日期", "holding_days": "持有天数", "add_time": "加入时间",
    "remove_time": "移除时间", "remove_reason": "移除原因", "alert_type": "告警类型",
    "alert_reason": "告警原因", "ma5": "5日均线", "ma20": "20日均线", "alert_time": "告警时间",
    "is_sent": "是否已发送", "kdj_k": "KDJ K值", "kdj_d": "KDJ D值", "kdj_j": "KDJ J值",
    "is_processed": "是否已处理", "batch_count": "批量数量", "analysis_mode": "分析模式",
    "success_count": "成功数量", "failed_count": "失败数量", "total_time": "总耗时", "results_json": "结果JSON",
    "fetch_time": "抓取时间", "total_platforms": "平台总数", "total_score": "总分",
    "flow_level": "流量级别", "social_score": "社媒得分", "news_score": "新闻得分",
    "finance_score": "财经得分", "tech_score": "科技得分", "analysis": "分析",
    "snapshot_id": "快照ID", "platform": "平台", "platform_name": "平台名称", "category": "分类",
    "weight": "权重", "title": "标题", "content": "内容", "url": "链接", "source": "来源",
    "publish_time": "发布时间", "rank": "排名", "matched_keywords": "匹配关键词",
    "keyword_count": "关键词数量", "topic": "话题", "count": "数量", "heat": "热度",
    "cross_platform": "是否跨平台", "sources": "来源列表", "avg_score": "平均得分", "max_score": "最高得分",
    "min_score": "最低得分", "snapshot_count": "快照数", "top_topics": "热门话题",
    "sentiment_index": "情绪指数", "sentiment_class": "情绪分类", "flow_stage": "流量阶段",
    "momentum": "动量", "viral_k": "病毒系数", "flow_type": "流量类型", "stage_analysis": "阶段分析",
    "alert_level": "告警级别", "related_topics": "相关话题", "trigger_value": "触发值",
    "threshold_value": "阈值", "is_notified": "是否已通知", "affected_sectors": "受影响板块",
    "risk_level": "风险等级", "risk_factors": "风险因素", "advice": "建议", "confidence": "置信度",
    "raw_response": "原始响应", "model_used": "使用模型", "analysis_time": "分析耗时",
    "task_name": "任务名", "task_type": "任务类型", "message": "消息", "duration": "耗时",
    "executed_at": "执行时间", "config_key": "配置键", "config_value": "配置值", "description": "描述",
    "keyword": "关键词", "current_rank": "当前排名", "previous_rank": "上一排名",
    "rank_change": "排名变化", "heat_score": "热度得分", "mention_count": "提及次数",
    "platforms": "平台列表", "cost_price": "成本价", "quantity": "数量", "note": "备注",
    "auto_monitor": "是否自动监控", "portfolio_stock_id": "组合股票ID", "rating": "评级",
    "entry_min": "入场区间下限", "entry_max": "入场区间上限", "take_profit": "止盈价",
    "entry_range": "入场区间", "realized_return": "已实现收益", "hit_10pct": "是否触及10%",
    "exit_reason": "退出原因", "bench_return": "基准收益", "exit_date": "退出日期",
    "model_train_rows": "模型训练行数", "train_end_date": "训练截止日期", "sh_ma20_gate": "上证MA20择时",
    "data_date": "数据日期", "sector_code": "板块代码", "sector_name": "板块名称", "price": "价格",
    "change_pct": "涨跌幅", "volume": "成交量", "turnover": "换手率", "market_cap": "市值",
    "pe_ratio": "市盈率", "pb_ratio": "市净率", "data_type": "数据类型", "data_version": "数据版本",
    "news_date": "新闻日期", "related_sectors": "相关板块", "sentiment_score": "情绪得分",
    "importance_score": "重要度得分", "investment_horizon": "投资周期", "market_outlook": "市场展望",
    "version": "版本", "error_message": "错误信息", "record_count": "记录数",
    "enabled": "是否启用", "check_interval": "检查间隔", "auto_trade": "是否自动交易",
    "position_size_pct": "仓位比例", "stop_loss_pct": "止损比例", "take_profit_pct": "止盈比例",
    "qmt_account_id": "QMT账户ID", "notify_email": "通知邮箱", "notify_webhook": "通知webhook",
    "has_position": "是否持仓", "position_cost": "持仓成本", "position_quantity": "持仓数量",
    "position_date": "建仓日期", "trading_hours_only": "仅交易时段", "decision_time": "决策时间",
    "trading_session": "交易时段", "action": "动作", "reasoning": "推理", "key_price_levels": "关键价位",
    "market_data": "行情数据", "account_info": "账户信息", "executed": "是否已执行",
    "execution_result": "执行结果", "trade_type": "交易类型", "amount": "金额", "order_id": "订单ID",
    "order_status": "订单状态", "ai_decision_id": "AI决策ID", "trade_time": "交易时间",
    "commission": "佣金", "tax": "税费", "profit_loss": "盈亏", "last_check_time": "最近检查时间",
    "notify_type": "通知类型", "notify_target": "通知目标", "subject": "主题", "error_msg": "错误信息",
    "sent_at": "发送时间", "log_level": "日志级别", "module": "模块", "details": "详情",
    "period": "周期", "stock_info": "股票信息", "agents_results": "Agent结果",
    "discussion_result": "讨论结果", "final_decision": "最终决策", "last_checked": "最近检查时间",
    "quant_enabled": "是否启用量化", "quant_config": "量化配置", "stock_id": "股票ID",
    "type": "类型", "triggered_at": "触发时间", "sent": "是否已发送", "timestamp": "时间戳",
    "multiple": "倍数", "decimal": "小数位", "last_price": "最新价", "edit_date": "编辑时间",
    "in_date": "入库时间", "exchange": "交易所", "open": "开盘价", "high": "最高价",
    "low": "最低价", "close": "收盘价", "ts": "时间戳",
}
```

- [ ] **Step 7: 校验 schema.sql 可执行（在 postgres 容器内试跑后回滚）**

Run:
```bash
docker exec -i pg-warehouse psql -U stock -d stock_warehouse <<'SQL'
CREATE SCHEMA IF NOT EXISTS market;
SQL
cat pg_warehouse/schema.sql | docker exec -i pg-warehouse psql -U stock -d stock_warehouse
docker exec pg-warehouse psql -U stock -d stock_warehouse -c "\d+ market.kline_day"
```
Expected: 无报错；`\d+` 输出含中文 `Comment` 与列注释。

- [ ] **Step 8: Commit**

```bash
git add pg_warehouse/schema.sql pg_warehouse/convert.py pg_warehouse/tests/test_convert.py
git commit -m "feat(pg-warehouse): market schema DDL + 类型转换纯函数"
```

---

### Task 3: import_all.py（全量导入：market + signals 自动建表）

**Files:**
- Create: `pg_warehouse/db.py`
- Create: `pg_warehouse/import_all.py`
- Create: `pg_warehouse/tests/test_import_unit.py`（对 `build_create_table` / 行转换做纯单测）

**Interfaces:**
- Consumes: `convert.py`（`to_ts/to_price/to_bool/sqlite_to_pg_type/TABLE_COMMENTS/COLUMN_COMMENTS`）。
- Produces `db.py`：
  - `get_pg_conn()`：`psycopg2.connect(host=PG_HOST, port=PG_PORT, user=PG_USER, password=PG_PASSWORD, dbname=PG_DB)`（从环境变量读，默认 host=localhost）。
  - `ro_sqlite(path)`：`sqlite3.connect(f"file:{path}?mode=ro", uri=True)`（只读，不阻塞生产写）。
- Produces `import_all.py`：
  - `SIGNAL_DBS: list[tuple[源db路径, 表名, PG表名]]`（Task 4 复用同一定义）。
  - `build_create_table(pg_table, cols: list[tuple[name, sqlite_type]]) -> str`：生成 `CREATE TABLE signals.<pg_table> ("col" TYPE, ...)`。
  - `build_comments(pg_table, cols) -> list[str]`：生成 `COMMENT ON` 语句列表。
  - `import_market_kline()`、`import_codes_calendar()`、`import_signals()`、`main()`。

- [ ] **Step 1: 写 import 单元测试**

`pg_warehouse/tests/test_import_unit.py`：

```python
from import_all import build_create_table, build_comments, SIGNAL_DBS

def test_build_create_table():
    sql = build_create_table("chanlun_signals", [("id", "INTEGER"), ("code", "TEXT"), ("buy_price", "REAL")])
    assert sql.startswith("CREATE TABLE signals.chanlun_signals (")
    assert '"id" BIGINT PRIMARY KEY' in sql
    assert '"code" TEXT' in sql
    assert '"buy_price" DOUBLE PRECISION' in sql

def test_build_comments_has_table_and_columns():
    stmts = build_comments("chanlun_signals", [("id", "INTEGER"), ("code", "TEXT")])
    joined = "\n".join(stmts)
    assert "COMMENT ON TABLE signals.chanlun_signals" in joined
    assert "COMMENT ON COLUMN signals.chanlun_signals.code" in joined

def test_signal_dbs_nonempty():
    assert len(SIGNAL_DBS) >= 40
    # 所有 PG 表名都在 signals schema 下唯一
    names = [pg for _, _, pg in SIGNAL_DBS]
    assert len(names) == len(set(names))
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd pg_warehouse && python -m pytest tests/test_import_unit.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'import_all'`。

- [ ] **Step 3: 实现 db.py**

```python
"""PG 连接与 SQLite 只读连接。"""
import os
import sqlite3
import psycopg2

def get_pg_conn():
    return psycopg2.connect(
        host=os.getenv("PG_HOST", "localhost"),
        port=int(os.getenv("PG_PORT", "5432")),
        user=os.getenv("PG_USER", "stock"),
        password=os.getenv("PG_PASSWORD", ""),
        dbname=os.getenv("PG_DB", "stock_warehouse"),
    )

def ro_sqlite(path):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)
```

- [ ] **Step 4: 实现 import_all.py**

```python
"""全量导入：market（codes/calendar/kline）+ signals（自动建表+导入）。幂等：表先 DROP 重建。"""
import csv, io, os, sys
import sqlite3
from db import get_pg_conn, ro_sqlite
from convert import (
    to_ts, to_price, to_bool, sqlite_to_pg_type, TABLE_COMMENTS, COLUMN_COMMENTS,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # aiagents-stock/
KLINE_DIR = os.path.join(ROOT, "tdx-data", "database", "kline")
CODES_DB = os.path.join(ROOT, "tdx-data", "database", "codes.db")
WORKDAY_DB = os.path.join(ROOT, "tdx-data", "database", "workday.db")
DATA_DIR = os.path.join(ROOT, "data")

# 每个信号库的表： (源db路径, 源表名, PG表名)。来源前缀规则见 spec 5.2。
SIGNAL_DBS = [
    ("data/chanlun_signals.db", "signals", "chanlun_signals"),
    ("data/chanlun_signals_intraday.db", "signals", "chanlun_signals_intraday"),
    ("data/combo_signals.db", "combo_signals", "combo_signals"),
    ("data/liumai_signals.db", "liumai_signals", "liumai_signals"),
    ("data/longhubang.db", "longhubang_records", "longhubang_records"),
    ("data/longhubang.db", "longhubang_analysis", "longhubang_analysis"),
    ("data/longhubang.db", "stock_tracking", "stock_tracking"),
    ("data/low_price_bull_monitor.db", "monitored_stocks", "low_price_bull_monitored_stocks"),
    ("data/low_price_bull_monitor.db", "sell_alerts", "low_price_bull_sell_alerts"),
    ("data/main_force_batch.db", "batch_analysis_history", "main_force_batch_analysis_history"),
    ("data/news_flow.db", "flow_snapshots", "news_flow_snapshots"),
    ("data/news_flow.db", "platform_news", "news_flow_platform_news"),
    ("data/news_flow.db", "stock_related_news", "news_flow_stock_related_news"),
    ("data/news_flow.db", "hot_topics", "news_flow_hot_topics"),
    ("data/news_flow.db", "flow_statistics", "news_flow_statistics"),
    ("data/news_flow.db", "sentiment_records", "news_flow_sentiment_records"),
    ("data/news_flow.db", "flow_alerts", "news_flow_alerts"),
    ("data/news_flow.db", "ai_analysis", "news_flow_ai_analysis"),
    ("data/news_flow.db", "scheduler_logs", "news_flow_scheduler_logs"),
    ("data/news_flow.db", "alert_config", "news_flow_alert_config"),
    ("data/news_flow.db", "keyword_rankings", "news_flow_keyword_rankings"),
    ("data/news_flow.db", "keyword_history", "news_flow_keyword_history"),
    ("data/portfolio_stocks.db", "portfolio_stocks", "portfolio_stocks"),
    ("data/portfolio_stocks.db", "portfolio_analysis_history", "portfolio_analysis_history"),
    ("data/profit_growth_monitor.db", "monitored_stocks", "profit_growth_monitored_stocks"),
    ("data/profit_growth_monitor.db", "sell_alerts", "profit_growth_sell_alerts"),
    ("data/qizhang_picks.db", "daily_picks", "qizhang_daily_picks"),
    ("data/qizhang_picks.db", "realized", "qizhang_realized"),
    ("data/qizhang_picks.db", "run_meta", "qizhang_run_meta"),
    ("data/sector_strategy.db", "sector_raw_data", "sector_raw_data"),
    ("data/sector_strategy.db", "sector_news_data", "sector_news_data"),
    ("data/sector_strategy.db", "sector_analysis_reports", "sector_analysis_reports"),
    ("data/sector_strategy.db", "sector_tracking", "sector_tracking"),
    ("data/sector_strategy.db", "data_versions", "sector_data_versions"),
    ("data/smart_monitor.db", "monitor_tasks", "smart_monitor_tasks"),
    ("data/smart_monitor.db", "ai_decisions", "smart_monitor_ai_decisions"),
    ("data/smart_monitor.db", "trade_records", "smart_monitor_trade_records"),
    ("data/smart_monitor.db", "position_monitor", "smart_monitor_position_monitor"),
    ("data/smart_monitor.db", "notifications", "smart_monitor_notifications"),
    ("data/smart_monitor.db", "system_logs", "smart_monitor_system_logs"),
    ("data/stock_analysis.db", "analysis_records", "stock_analysis_records"),
    ("data/stock_monitor.db", "monitored_stocks", "stock_monitor_monitored_stocks"),
    ("data/stock_monitor.db", "price_history", "stock_monitor_price_history"),
    ("data/stock_monitor.db", "notifications", "stock_monitor_notifications"),
]


def build_create_table(pg_table, cols):
    defs = []
    for i, (n, t) in enumerate(cols):
        col = f'"{n}" {sqlite_to_pg_type(t)}'
        if i == 0 and n == "id":
            col += " PRIMARY KEY"   # 首列名为 id 时建为主键，供增量同步 ON CONFLICT 去重
        defs.append(col)
    return f'CREATE TABLE signals.{pg_table} ({", ".join(defs)});'


def build_comments(pg_table, cols):
    stmts = [f"COMMENT ON TABLE signals.{pg_table} IS '{TABLE_COMMENTS.get(pg_table, pg_table)}';"]
    for n, _t in cols:
        c = COLUMN_COMMENTS.get(n, n)
        stmts.append(f"COMMENT ON COLUMN signals.{pg_table}.{n} IS '{c}';")
    return stmts


def copy_csv(conn, table, rows):
    """rows: iterable of str tuples；用 COPY ... FROM STDIN CSV 批量写入。"""
    buf = io.StringIO()
    w = csv.writer(buf)
    for r in rows:
        w.writerow(r)
    buf.seek(0)
    cur = conn.cursor()
    cur.copy_expert(f"COPY {table} FROM STDIN WITH CSV", buf)
    conn.commit()


def import_codes_calendar(conn):
    c = ro_sqlite(CODES_DB)
    rows = c.execute("SELECT ID,Name,Code,Exchange,Multiple,Decimal,LastPrice,EditDate,InDate FROM codes")
    out = ((r[0], r[1], r[2], r[3], r[4], r[5], r[6], to_ts(r[7]), to_ts(r[8])) for r in rows)
    copy_csv(conn, "market.stock_codes", out)
    w = ro_sqlite(WORKDAY_DB)
    rows = w.execute("SELECT ID,Unix,Date FROM workday")
    # Date 可能是 'YYYYMMDD' 或 'YYYY-MM-DD'，统一转 DATE
    def conv_date(d):
        if not d:
            return None
        d = str(d)
        if "-" not in d and len(d) == 8:
            d = f"{d[:4]}-{d[4:6]}-{d[6:]}"
        return d
    out = ((r[0], to_ts(r[1]), conv_date(r[2])) for r in rows)
    copy_csv(conn, "market.trade_calendar", out)


def import_market_kline(conn):
    files = sorted(os.listdir(KLINE_DIR))
    files = [f for f in files if f.endswith(".db")]
    tables = [("DayKline", "market.kline_day"), ("Minute5Kline", "market.kline_5min"), ("Minute30Kline", "market.kline_30min")]
    for i, fn in enumerate(files):
        code = fn[:-3]  # 去掉 .db
        path = os.path.join(KLINE_DIR, fn)
        try:
            c = ro_sqlite(path)
        except sqlite3.Error as e:
            print(f"[跳过] {fn}: {e}", flush=True); continue
        for src_tbl, pg_tbl in tables:
            rows = c.execute(f"SELECT Date,Open,High,Low,Close,Volume,Amount,InDate FROM {src_tbl}")
            out = ((code, to_ts(r[0]), to_price(r[1]), to_price(r[2]), to_price(r[3]),
                    to_price(r[4]), r[5], r[6], to_ts(r[7])) for r in rows)
            copy_csv(conn, pg_tbl, out)
        c.close()
        if (i + 1) % 500 == 0:
            print(f"  进度 {i+1}/{len(files)}", flush=True)
    print(f"K线导入完成：{len(files)} 只", flush=True)


def import_signals(conn):
    cur = conn.cursor()
    for rel, src_tbl, pg_tbl in SIGNAL_DBS:
        path = os.path.join(ROOT, rel)
        c = ro_sqlite(path)
        cols = [(r[1], r[2]) for r in c.execute(f"PRAGMA table_info({src_tbl})")]
        cur.execute(f"DROP TABLE IF EXISTS signals.{pg_tbl} CASCADE")
        cur.execute(build_create_table(pg_tbl, cols))
        for s in build_comments(pg_tbl, cols):
            cur.execute(s)
        conn.commit()
        rows = c.execute(f"SELECT {','.join(f'\"{n}\"' for n,_ in cols)} FROM {src_tbl}")
        # 逐列类型转换：BOOLEAN→to_bool，TIMESTAMP→to_ts，其余原样
        convs = [to_bool if t.upper() in ("BOOLEAN","BOOL") else (to_ts if t.upper() in ("TIMESTAMP","DATETIME") else (lambda x: x))
                 for _n, t in cols]
        out = (tuple(cv(v) for cv, v in zip(convs, r)) for r in rows)
        copy_csv(conn, f"signals.{pg_tbl}", out)
        c.close()
        print(f"  {pg_tbl}: 导入完成", flush=True)


def main():
    import shutil
    total, _used, free = shutil.disk_usage(ROOT)
    free_gb = free // 1024**3
    print(f"[磁盘] 剩余 {free_gb}GB（建议 30GB 以上）", flush=True)
    if free < 30 * 1024**3:
        print(f"[警告] 剩余磁盘不足 30GB，PG 数据约需 15-25GB，建议先清理", flush=True)
    conn = get_pg_conn()
    cur = conn.cursor()
    cur.execute("CREATE SCHEMA IF NOT EXISTS market")
    cur.execute("CREATE SCHEMA IF NOT EXISTS signals")
    conn.commit()
    print("导入 codes / workday …", flush=True)
    import_codes_calendar(conn)
    print("导入 K线（约 2 亿行，需 10-30 分钟）…", flush=True)
    import_market_kline(conn)
    print("导入信号库 …", flush=True)
    import_signals(conn)
    conn.close()
    print("全部完成", flush=True)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: 运行单元测试通过**

Run: `cd pg_warehouse && python -m pytest tests/test_import_unit.py -v`
Expected: 3 个测试 PASS。

- [ ] **Step 6: 小规模冒烟（先用一只票验证 market K 线导入正确性）**

Run:
```bash
cd /home/tdxback/aiagents-stock/pg_warehouse && python - <<'PY'
from import_all import import_market_kline
from db import get_pg_conn
# 只导一只票验证：临时把 KLINE_DIR 指到单票——此处直接手测转换
import sqlite3
c = sqlite3.connect('file:/home/tdxback/aiagents-stock/tdx-data/database/kline/000001.db?mode=ro', uri=True)
r = c.execute("SELECT Date,Open,High,Low,Close,Volume,Amount FROM DayKline ORDER BY Date DESC LIMIT 1").fetchone()
print("源最后一行:", r)
from convert import to_ts, to_price
print("转换后 ts:", to_ts(r[0]), " close(元):", to_price(r[4]))
PY
```
Expected: 输出源最后一行 + 转换后的时间戳（UTC+8）和收盘价（元，如 `11.39`）。

- [ ] **Step 7: Commit**

```bash
git add pg_warehouse/db.py pg_warehouse/import_all.py pg_warehouse/tests/test_import_unit.py
git commit -m "feat(pg-warehouse): 全量导入脚本（market + signals 自动建表）"
```

---

### Task 4: sync_daily.py（每日增量同步，幂等）

**Files:**
- Create: `pg_warehouse/sync_daily.py`
- Test: `pg_warehouse/tests/test_sync_unit.py`

**Interfaces:**
- Consumes: `db.py`（`get_pg_conn/ro_sqlite`）、`convert.py`、`import_all.py`（`SIGNAL_DBS`、`build_create_table/build_comments`、`copy_csv`）。
- Produces: `sync_daily.py` 的 `run_sync() -> dict`（返回每表新增行数汇总，Task 5 调度调用）。

- [ ] **Step 1: 写增量同步纯函数单元测试**

`pg_warehouse/tests/test_sync_unit.py`：

```python
import datetime
from zoneinfo import ZoneInfo
from sync_daily import pg_ts_to_unix
from import_all import SIGNAL_DBS
from convert import TABLE_COMMENTS

def test_pg_ts_to_unix():
    dt = datetime.datetime(2024, 5, 13, 21, 35, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert pg_ts_to_unix(dt) == 1715650500   # 精确还原源 Unix 秒，供 WHERE Date > ? 过滤
    assert pg_ts_to_unix(None) is None

def test_all_signal_tables_have_comment():
    missing = [pg for _, _, pg in SIGNAL_DBS if pg not in TABLE_COMMENTS]
    assert missing == []   # 每张信号表都有中文表注释
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd pg_warehouse && python -m pytest tests/test_sync_unit.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'sync_daily'`。

- [ ] **Step 3: 实现 sync_daily.py**

```python
"""每日增量同步：只追加源库中 > PG 最新值的行，天然幂等（第二次 0 新增）。"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db import get_pg_conn, ro_sqlite
from convert import to_ts, to_price, to_bool
from import_all import (
    ROOT, KLINE_DIR, CODES_DB, WORKDAY_DB, SIGNAL_DBS,
    build_create_table, build_comments, copy_csv,
)


def pg_ts_to_unix(dt):
    """PG timestamptz -> 源 Unix 秒（整数，用于 WHERE Date > ? 增量过滤，精确还原无浮点误差）。"""
    return int(dt.timestamp()) if dt is not None else None


def run_sync():
    conn = get_pg_conn()
    cur = conn.cursor()
    stats = {}

    # 1) K线：按 code 各自对比 max(ts)，只追加 Date > 该值的 bar
    for src_tbl, pg_tbl in [("DayKline", "kline_day"), ("Minute5Kline", "kline_5min"), ("Minute30Kline", "kline_30min")]:
        added = 0
        files = sorted(f for f in os.listdir(KLINE_DIR) if f.endswith(".db"))
        for fn in files:
            code = fn[:-3]
            c = ro_sqlite(os.path.join(KLINE_DIR, fn))
            cur.execute(f"SELECT MAX(ts) FROM market.{pg_tbl} WHERE code=%s", (code,))
            unix = pg_ts_to_unix(cur.fetchone()[0])
            if unix is None:
                rows = c.execute(f"SELECT Date,Open,High,Low,Close,Volume,Amount,InDate FROM {src_tbl}")
            else:
                rows = c.execute(f"SELECT Date,Open,High,Low,Close,Volume,Amount,InDate FROM {src_tbl} WHERE Date > ?", (unix,))
            buf = []
            for r in rows:
                buf.append((code, to_ts(r[0]), to_price(r[1]), to_price(r[2]), to_price(r[3]), to_price(r[4]), r[5], r[6], to_ts(r[7])))
            if buf:
                copy_csv(conn, f"market.{pg_tbl}", buf)
                added += len(buf)
            c.close()
        stats[pg_tbl] = added
        print(f"  {pg_tbl}: +{added}", flush=True)

    # 2) codes / workday：按主键 id 增量
    for name, path, pg_tbl in [("codes", CODES_DB, "market.stock_codes"),
                                ("workday", WORKDAY_DB, "market.trade_calendar")]:
        c = ro_sqlite(path)
        cur.execute(f"SELECT COALESCE(MAX(id), -1) FROM {pg_tbl}")
        mx = cur.fetchone()[0]
        if name == "codes":
            rows = c.execute("SELECT ID,Name,Code,Exchange,Multiple,Decimal,LastPrice,EditDate,InDate FROM codes WHERE ID > ?", (mx,))
            out = [(r[0], r[1], r[2], r[3], r[4], r[5], r[6], to_ts(r[7]), to_ts(r[8])) for r in rows]
        else:
            rows = c.execute("SELECT ID,Unix,Date FROM workday WHERE ID > ?", (mx,))
            out = [(r[0], to_ts(r[1]), r[2]) for r in rows]
        if out:
            copy_csv(conn, pg_tbl, out)
        c.close()
        stats[pg_tbl] = len(out)
        print(f"  {pg_tbl}: +{len(out)}", flush=True)

    # 3) 信号库：按主键 id 增量；无 id 主键的表用全量覆盖（数据量小）
    for rel, src_tbl, pg_tbl in SIGNAL_DBS:
        path = os.path.join(ROOT, rel)
        c = ro_sqlite(path)
        cols = [(r[1], r[2]) for r in c.execute(f"PRAGMA table_info({src_tbl})")]
        has_id = cols[0][0] == "id"
        # 表不存在则先建（首次运行）
        cur.execute("SELECT to_regclass(%s)", (f"signals.{pg_tbl}",))
        if cur.fetchone()[0] is None:
            cur.execute(build_create_table(pg_tbl, cols))
            for s in build_comments(pg_tbl, cols):
                cur.execute(s)
            conn.commit()
        if has_id:
            cur.execute(f"SELECT COALESCE(MAX(id), -1) FROM signals.{pg_tbl}")
            mx = cur.fetchone()[0]
            rows = c.execute(f"SELECT * FROM {src_tbl} WHERE id > ?", (mx,))
        else:
            rows = c.execute(f"SELECT * FROM {src_tbl}")
        convs = [to_bool if t.upper() in ("BOOLEAN", "BOOL") else (to_ts if t.upper() in ("TIMESTAMP", "DATETIME") else (lambda x: x)) for _n, t in cols]
        out = [tuple(cv(v) for cv, v in zip(convs, r)) for r in rows]
        if out:
            copy_csv(conn, f"signals.{pg_tbl}", out)
        c.close()
        stats[pg_tbl] = len(out)
        print(f"  {pg_tbl}: +{len(out)}", flush=True)

    conn.close()
    return stats


if __name__ == "__main__":
    run_sync()
```

- [ ] **Step 4: 运行单元测试通过**

Run: `cd pg_warehouse && python -m pytest tests/test_sync_unit.py -v`
Expected: 2 个测试 PASS。

- [ ] **Step 5: 幂等验证（连跑两次）**

Run:
```bash
cd /home/tdxback/aiagents-stock/pg_warehouse && \
PG_HOST=localhost python sync_daily.py && echo "--- 第二次 ---" && \
PG_HOST=localhost python sync_daily.py
```
Expected: 第二次每表新增数全为 0（或仅停牌股极小增量），证明幂等。

- [ ] **Step 6: Commit**

```bash
git add pg_warehouse/sync_daily.py pg_warehouse/tests/test_sync_unit.py
git commit -m "feat(pg-warehouse): 每日增量同步（幂等）"
```

---

### Task 5: sidecar 容器 pg-sync-updater + 调度循环

**Files:**
- Create: `pg_warehouse/sync_loop.py`
- Modify: `docker-compose.yml`（加 pg-sync-updater 服务）

**Interfaces:**
- Consumes: `sync_daily.run_sync()`（Task 4）。
- Produces: `sync_loop.py`（进程内 schedule 每天 21:00 调 `run_sync`，日志 stdout）。

- [ ] **Step 1: 写 sync_loop.py**

```python
"""pg-sync-updater 调度循环：每天 21:00 调 run_sync（容器 TZ=Asia/Shanghai）。"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import schedule
from sync_daily import run_sync

SYNC_AT = os.getenv("PG_SYNC_AT", "21:00")

def job():
    print(f"[pg-sync] 开始增量同步 @ {time.strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
    try:
        stats = run_sync()
        total = sum(stats.values())
        print(f"[pg-sync] 完成，新增 {total} 行", flush=True)
    except Exception as e:
        print(f"[pg-sync] 失败: {e}", flush=True)

schedule.every().day.at(SYNC_AT).do(job)
print(f"[pg-sync] 调度已就绪，每天 {SYNC_AT} 运行", flush=True)
while True:
    schedule.run_pending()
    time.sleep(60)
```

- [ ] **Step 2: docker-compose.yml 加 pg-sync-updater 服务**

在 `postgres` 服务之后插入：

```yaml
  # 每日增量同步 PG 仓库：复用主应用镜像（含 python/schedule/psycopg2），
  # 每天 21:00（kline 18:00 / chanlun 20:00 / qizhang 20:30 之后）跑 sync_daily。
  pg-sync-updater:
    image: aiagents-stock-app
    container_name: pg-sync-updater
    logging: *default-logging
    command: ["python", "/app/pg_warehouse/sync_loop.py"]
    environment:
      - TZ=Asia/Shanghai
      - PG_HOST=postgres
      - PG_PORT=5432
      - PG_USER=${PG_USER}
      - PG_PASSWORD=${PG_PASSWORD}
      - PG_DB=${PG_DB}
    volumes:
      - ./pg_warehouse:/app/pg_warehouse:ro
      - ./tdx-data:/app/tdx-data:ro
      - ./data:/app/data:ro
    healthcheck:
      disable: true
    restart: unless-stopped
    depends_on:
      postgres:
        condition: service_healthy
    networks:
      - agentsstock-network
```

- [ ] **Step 3: 重新构建主应用镜像（加入 psycopg2-binary 依赖）**

Run: `docker compose build agentsstock`
Expected: 构建成功（`psycopg2-binary` 安装无报错）。

- [ ] **Step 4: 启动 sidecar 并验证调度就绪**

Run: `docker compose up -d pg-sync-updater && sleep 10 && docker logs pg-sync-updater --tail 20`
Expected: 日志含 `[pg-sync] 调度已就绪，每天 21:00 运行`。

- [ ] **Step 5: 手动触发一次验证端到端连通**

Run: `docker exec pg-sync-updater sh -c "cd /app/pg_warehouse && python -c 'from sync_daily import run_sync; print(run_sync())'"`
Expected: 输出各表新增行数（增量，应为 0 或极小），证明容器内能连 postgres + 读源库。

- [ ] **Step 6: Commit**

```bash
git add pg_warehouse/sync_loop.py docker-compose.yml
git commit -m "feat(pg-warehouse): pg-sync-updater sidecar 每日调度"
```

---

### Task 6: README + 端到端验收

**Files:**
- Create: `pg_warehouse/README.md`

- [ ] **Step 1: 写 README.md**

内容包含：数据仓库用途、Schema 分层（market/signals）、表清单、字段注释查看方法（`psql \d+`）、全量导入命令（`python import_all.py`）、增量同步命令（`python sync_daily.py`）、调度说明（每天 21:00）、连接方式（宿主机 `psql -h localhost -U stock -d stock_warehouse`）、数据类型口径（价格×1000 已转元、Unix 秒已转时间戳）。

- [ ] **Step 2: 端到端验收清单逐项核对**

Run 以下命令，逐项确认：
```bash
# 1. postgres 健康
docker exec pg-warehouse pg_isready -U stock -d stock_warehouse
# 2. K线总行数与源核对（任选一票）
docker exec pg-warehouse psql -U stock -d stock_warehouse -tAc \
  "SELECT count(*) FROM market.kline_day WHERE code='000001';"
python3 -c "import sqlite3;print(sqlite3.connect('file:tdx-data/database/kline/000001.db?mode=ro',uri=True).execute('SELECT count(*) FROM DayKline').fetchone()[0])"
# 3. 注释可见
docker exec pg-warehouse psql -U stock -d stock_warehouse -c "\d+ market.kline_day"
# 4. 价格正确（应输出 11.390）
docker exec pg-warehouse psql -U stock -d stock_warehouse -tAc \
  "SELECT close FROM market.kline_day WHERE code='000001' ORDER BY ts DESC LIMIT 1;"
# 5. 幂等：连跑两次 sync_daily，第二次全 0
```
Expected: 全部符合预期。

- [ ] **Step 3: 提交剩余改动**

```bash
git add pg_warehouse/README.md
git commit -m "docs(pg-warehouse): README 使用说明"
```

---

## 执行顺序与依赖

Task 1 → 2 → 3 → 4 → 5 → 6 顺序执行（每步依赖前一步）。Task 3 的全量导入是耗时步骤（10–30 分钟），执行时需耐心等待并观察进度日志。
