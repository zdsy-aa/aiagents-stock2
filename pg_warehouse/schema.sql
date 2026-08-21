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
