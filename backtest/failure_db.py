# backtest/failure_db.py
"""失败策略库:失败原因六分类落库(Phase3 Task3.4,R3-C)。

- 库不做自动分类:分类由调用方传入,`classify_failure` 只做六分类枚举校验
  (指标/参数/市场环境/数据/组合/执行),非法分类直接 ValueError(防笔误静默入库)。
- 表 `failures(id, combo, code, date, year, win, ret, reason, classified_at)`,
  唯一键 (combo, code, date);写入用 INSERT OR IGNORE,重跑同一批信号天然幂等
  (失败策略库按「信号日期+代码+组合」为一条,同一条不因重跑翻倍)。
- `record_failures` 只落 mask 命中且未盈利(是否盈利 == 0)的行;盈利行不属失败,
  永不入库。
- 真实库 `data/backtest_failures.db`(.gitignore 覆盖 data/*.db);测试一律
  monkeypatch `DB_PATH` 到 tmp_path,绝不写真实库。
"""
import os
import sqlite3
from collections import defaultdict
from contextlib import closing
from datetime import datetime

import numpy as np
import pandas as pd

from backtest.dataio import LABEL_COL, RET_COL

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "data", "backtest_failures.db")

CODE_COL = "股票代码"
DATE_COL = "信号日期"
YEAR_COL = "年"
REQUIRED_COLS = (CODE_COL, DATE_COL, YEAR_COL, LABEL_COL, RET_COL)

# 六分类枚举(R3-C 裁决):库不自动分类,调用方传入,库只校验
CATEGORIES = ("指标", "参数", "市场环境", "数据", "组合", "执行")

_INSERT_SQL = """
INSERT OR IGNORE INTO failures
    (combo, code, date, year, win, ret, reason, classified_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
"""


def _connect():
    """按模块级 DB_PATH 现取现连(测试 monkeypatch DB_PATH 后即生效)。"""
    return sqlite3.connect(DB_PATH)


def init_db():
    """建表(IF NOT EXISTS,幂等;目录不存在则创建)。"""
    parent = os.path.dirname(DB_PATH)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with closing(_connect()) as conn, conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS failures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            combo TEXT NOT NULL,
            code TEXT NOT NULL,
            date TEXT NOT NULL,
            year TEXT,
            win INTEGER,
            ret REAL,
            reason TEXT NOT NULL,
            classified_at TEXT NOT NULL,
            UNIQUE(combo, code, date)
        )""")


def classify_failure(combo, reason):
    """校验失败原因属于六分类枚举,返回该分类;非法分类 -> ValueError。

    分类由调用方判定(库不做自动分类)。combo 仅用于错误信息定位。
    """
    if reason not in CATEGORIES:
        raise ValueError(
            f"组合 {combo} 的失败原因 {reason!r} 不在六分类枚举内: {CATEGORIES}")
    return reason


def _as_mask(df, mask):
    """mask -> 与 df 等长的 bool 数组(位置对齐;浮点 NaN 视为未命中)。"""
    m = mask.to_numpy() if isinstance(mask, pd.Series) else np.asarray(mask)
    m = np.ravel(m)
    if len(m) != len(df):
        raise ValueError(f"mask 长度 {len(m)} 与面板行数 {len(df)} 不一致")
    if m.dtype.kind == "f":
        m = np.nan_to_num(m)
    return m.astype(bool)


def _s(x):
    """标量转字符串:NaN/None -> "";20240101.0 这类整数值不留小数尾巴。"""
    if x is None or (isinstance(x, float) and np.isnan(x)) or x is pd.NaT:
        return ""
    if isinstance(x, (float, np.floating)):
        return str(int(x)) if float(x).is_integer() else str(float(x))
    if isinstance(x, (int, np.integer)):
        return str(int(x))
    return str(x)


def _ret(x):
    """区间涨跌幅 -> float;非数值/NaN -> None。"""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if np.isfinite(v) else None


def record_failures(combo_name, df, mask, reason):
    """把 mask 命中且未盈利的行落库,返回真正新插入的行数(被唯一键忽略的不计)。

    - 去重键 (combo, code, date):同组合同代码同信号日期只留一条,重跑幂等。
    - reason 必须是六分类之一(调用方判定),否则 ValueError。
    - df 需含 dataio.LABEL_COL/RET_COL 与 股票代码/信号日期/年 列。
    """
    reason = classify_failure(combo_name, reason)
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"面板缺列: {missing}(需要 {REQUIRED_COLS})")
    sel = np.flatnonzero(
        _as_mask(df, mask)
        & (pd.to_numeric(df[LABEL_COL], errors="coerce").fillna(0).to_numpy() == 0))
    if len(sel) == 0:
        return 0

    codes = df[CODE_COL].to_numpy()
    dates = df[DATE_COL].to_numpy()
    years = df[YEAR_COL].to_numpy()
    rets = pd.to_numeric(df[RET_COL], errors="coerce").to_numpy()
    combo = str(combo_name)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = [(combo, _s(codes[i]), _s(dates[i]), _s(years[i]), 0, _ret(rets[i]), reason, ts)
            for i in sel]
    blank = sum(1 for r in rows if not r[1] or not r[2])
    if blank:
        raise ValueError(f"{blank} 行 股票代码/信号日期 为空,拒绝落库(会污染去重键)")

    init_db()
    with closing(_connect()) as conn, conn:
        before = conn.total_changes
        conn.executemany(_INSERT_SQL, rows)
        return conn.total_changes - before


def failure_stats(combo_name=None):
    """按失败分类聚合计数 -> dict{分类: 计数};combo_name=None 时全库聚合。

    只含出现过的分类;未出现的分类按 0 计(defaultdict(int),取值不 KeyError)。
    """
    sql = "SELECT reason, COUNT(*) FROM failures"
    params = ()
    if combo_name is not None:
        sql += " WHERE combo = ?"
        params = (str(combo_name),)
    sql += " GROUP BY reason"
    stats = defaultdict(int)
    init_db()
    with closing(_connect()) as conn:
        for reason, n in conn.execute(sql, params):
            stats[reason] = int(n)
    return stats
