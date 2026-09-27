# -*- coding: utf-8 -*-
"""信号生命周期追踪(Phase5 Task5.3)。

业务闭环「运行策略 → 产生信号 → 记录结果 → 统计 → 迭代」的信号结果侧:

- record_signals(combo_name, df, mask, reason="市场环境") -> int:
  对全部 mask 命中行落信号追踪表 signals(新库 data/backtest_signals.db);
  对未盈利行复用 backtest.failure_db.record_failures 落六分类失败库
  (data/backtest_failures.db,Phase3 Task3.4)。返回追踪表新插入行数。
- signal_stats(combo_name=None, days=(1,3,5,10)) -> pd.DataFrame:
  各 N 天后成功率/平均收益/最大回撤。匹配语义复用 Phase 4 comparison
  (ai_trace.comparison_table):对每条信号按 (代码, 信号日期+N天) 先查
  买点面板 load_panel、未命中再查确认面板 load_confirm_panel,取该行
  是否盈利 与 区间涨跌幅 作为 N 天结果;N 天收益近似口径沿用 Phase 4 裁决
  ——以匹配行(date+N 当日)的 20 日区间涨跌幅近似 N 天收益(面板不提供
  逐 N 收益,20 日口径与 backtest.engine.HOLD_DAYS 一致)。
  匹配不到的行不计入该 N 的统计;某 N 零匹配时对应列为 NaN。
- failure_breakdown(combo_name) -> dict:六分类计数,包装
  failure_db.failure_stats,补全六分类键(未出现按 0)。

表方案(报告 task-5.3-report.md):新库新表——data/backtest_signals.db 建
signals 表,不扩 failure_db。理由:信号追踪(全部命中,含盈利行,收益生命周期)
与失败策略库(仅未盈利,六分类复盘)生命周期/消费方不同,合库会让 failure_db
的表结构与其测试隔离语义(patch failure_db.DB_PATH)互相牵制;追踪表幂等去重键
与失败库一致 (combo, code, date),同口径「同一信号一条,重跑不翻倍」。

真实库 data/backtest_signals.db(.gitignore 覆盖 data/*.db);测试一律
monkeypatch DB_PATH 到 tmp_path,绝不写真实库。
"""
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

import backtest.failure_db as failure_db
from backtest.dataio import LABEL_COL, RET_COL, load_confirm_panel, load_panel

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "data", "backtest_signals.db")

CODE_COL = "股票代码"
DATE_COL = "信号日期"
YEAR_COL = "年"
REQUIRED_COLS = (CODE_COL, DATE_COL, YEAR_COL, LABEL_COL, RET_COL)

# 面板 区间涨跌幅 的持仓周期(20 个交易日,口径同 backtest.engine.HOLD_DAYS)
HOLD_DAYS = 20

_INSERT_SQL = """
INSERT OR IGNORE INTO signals
    (combo, code, date, win, ret, days, recorded_at)
VALUES (?, ?, ?, ?, ?, ?, ?)
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
        CREATE TABLE IF NOT EXISTS signals (
            signal_id INTEGER PRIMARY KEY AUTOINCREMENT,
            combo TEXT NOT NULL,
            code TEXT NOT NULL,
            date TEXT NOT NULL,
            win INTEGER,
            ret REAL,
            days INTEGER NOT NULL,
            recorded_at TEXT NOT NULL,
            UNIQUE(combo, code, date)
        )""")


def _as_mask(df, mask):
    """mask -> 与 df 等长的 bool 数组(口径同 failure_db._as_mask)。"""
    m = mask.to_numpy() if isinstance(mask, pd.Series) else np.asarray(mask)
    m = np.ravel(m)
    if len(m) != len(df):
        raise ValueError(f"mask 长度 {len(m)} 与面板行数 {len(df)} 不一致")
    if m.dtype.kind == "f":
        m = np.nan_to_num(m)
    return m.astype(bool)


def _s(x):
    """标量转字符串(口径同 failure_db._s):NaN/None -> "";整数值不留小数尾巴。"""
    if x is None or (isinstance(x, float) and np.isnan(x)) or x is pd.NaT:
        return ""
    if isinstance(x, (float, np.floating)):
        return str(int(x)) if float(x).is_integer() else str(float(x))
    if isinstance(x, (int, np.integer)):
        return str(int(x))
    return str(x)


def _win(x):
    """是否盈利 标签 -> 0/1(口径同 failure_db:数值 == 1 计盈利,其余计 0)。"""
    try:
        return 1 if float(x) == 1 else 0
    except (TypeError, ValueError):
        return 0


def _ret(x):
    """区间涨跌幅 -> float;非数值/NaN -> None(口径同 failure_db._ret)。"""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if np.isfinite(v) else None


def record_signals(combo_name, df, mask, reason="市场环境"):
    """对全部 mask 命中行落信号追踪表;未盈利行复用 failure_db.record_failures
    落六分类失败库。返回追踪表新插入行数(重跑幂等,被唯一键忽略的不计)。

    - 追踪表去重键 (combo, code, date),与失败库同口径:同一信号一条,重跑不翻倍。
    - signals.days 记录 win/ret 的评估持有期 = HOLD_DAYS(20 交易日,面板
      区间涨跌幅 的固定口径)。
    - df 需含 股票代码/信号日期/年/是否盈利/区间涨跌幅 列(failure_db 同款要求)。
    - reason 六分类枚举由 failure_db.record_failures 校验,非法抛 ValueError;
      命中行的 股票代码/信号日期 为空同样拒绝落库(空串会污染去重键)。
    """
    combo = str(combo_name)
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"面板缺列: {missing}(需要 {REQUIRED_COLS})")
    sel = np.flatnonzero(_as_mask(df, mask))
    codes = df[CODE_COL].to_numpy()
    dates = df[DATE_COL].to_numpy()
    for i in sel:
        if not _s(codes[i]) or not _s(dates[i]):
            raise ValueError(
                "存在 股票代码/信号日期 为空的行,拒绝落库(会污染去重键)")
    # 未盈利行落失败库(六分类校验+幂等;先于追踪表写入,失败则追踪表不落)
    failure_db.record_failures(combo, df, mask, reason)
    if len(sel) == 0:
        return 0
    wins = pd.to_numeric(df[LABEL_COL], errors="coerce").to_numpy()
    rets = pd.to_numeric(df[RET_COL], errors="coerce").to_numpy()
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = [(combo, _s(codes[i]), _s(dates[i]), _win(wins[i]), _ret(rets[i]),
             HOLD_DAYS, ts) for i in sel]
    init_db()
    with closing(_connect()) as conn, conn:
        before = conn.total_changes
        conn.executemany(_INSERT_SQL, rows)
        return conn.total_changes - before


# ---------- signal_stats(Phase 4 comparison 匹配语义) ----------

def _norm_code(x):
    """股票代码归一:纯数字去前导零(语义同 ai_trace._norm_code)。"""
    s = str(x).strip()
    if s.isdigit():
        s = s.lstrip("0") or "0"
    return s


def _norm_date(x):
    """日期 -> 'YYYY-MM-DD'(语义同 ai_trace._norm_date);无法解析返回 None。"""
    if x is None:
        return None
    s = str(x).strip()
    head = s[:10] if len(s) >= 10 else s
    try:
        return datetime.strptime(head, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        pass
    if len(s) >= 8:
        try:
            return datetime.strptime(s[:8], "%Y%m%d").strftime("%Y-%m-%d")
        except ValueError:
            pass
    try:
        return pd.to_datetime(s).strftime("%Y-%m-%d")
    except Exception:
        return None


def _buy_index_pair(df):
    """买点面板 -> {(norm_code, 'YYYY-MM-DD'): (label, ret)};NaN 标签不建键。"""
    idx = {}
    if df is None or len(df) == 0:
        return idx
    codes = df[CODE_COL].astype(str).map(_norm_code).to_numpy()
    dates = df[DATE_COL].map(_norm_date).to_numpy()
    labels = pd.to_numeric(df[LABEL_COL], errors="coerce").to_numpy()
    rets = pd.to_numeric(df[RET_COL], errors="coerce").to_numpy()
    for code, date, lab, ret in zip(codes, dates, labels, rets):
        if code and date and pd.notna(lab):
            idx[(code, date)] = (int(lab), _ret(ret))
    return idx


def _norm_code_series(codes):
    """面板代码列 -> 归一字符串列(语义同 ai_trace._norm_code_series)。"""
    if isinstance(codes.dtype, pd.CategoricalDtype):
        return codes.map(
            {c: _norm_code(c) for c in codes.cat.categories}).astype(str)
    return codes.astype(str).map(_norm_code)


def _lookup_confirm_pair(confirm_df, pending):
    """确认面板兜底:{(norm_code, YYYYMMDD int): (label, ret)}
    (语义同 ai_trace._lookup_confirm,多取区间涨跌幅)。"""
    found = {}
    if not pending or confirm_df is None or len(confirm_df) == 0:
        return found
    needed_codes = {c for _, c, _ in pending}
    needed_dates = {int(t.replace("-", "")) for _, _, t in pending}
    norm = _norm_code_series(confirm_df[CODE_COL])
    mask = norm.isin(needed_codes) & confirm_df[DATE_COL].isin(needed_dates)
    if not mask.any():
        return found
    sub = confirm_df.loc[mask, [CODE_COL, DATE_COL, LABEL_COL, RET_COL]].copy()
    sub[CODE_COL] = norm[mask].to_numpy()
    labels = pd.to_numeric(sub[LABEL_COL], errors="coerce").to_numpy()
    rets = pd.to_numeric(sub[RET_COL], errors="coerce").to_numpy()
    for code, date, lab, ret in zip(sub[CODE_COL].to_numpy(),
                                    sub[DATE_COL].to_numpy(), labels, rets):
        if pd.notna(lab):
            found[(str(code), int(date))] = (int(lab), _ret(ret))
    return found


def _max_drawdown(rets):
    """(1+ret).cumprod 净值曲线最大回撤(对数空间,口径同 backtest.engine)。"""
    rets = pd.to_numeric(pd.Series(rets), errors="coerce").dropna()
    if len(rets) == 0:
        return np.nan
    log_ret = np.log1p(rets.to_numpy(dtype=np.float64))
    log_ret[~np.isfinite(log_ret)] = -1e3  # ret <= -1:净值归零(近似)
    log_eq = log_ret.cumsum()
    log_peak = np.maximum.accumulate(log_eq)
    dd = 1.0 - np.exp(np.clip(log_eq - log_peak, -700.0, 0.0))
    return float(np.max(dd))


def _load_signal_rows(combo_name):
    """读追踪表 -> [(combo, code, date)];combo_name=None 时全库。"""
    sql = "SELECT combo, code, date FROM signals"
    params = ()
    if combo_name is not None:
        sql += " WHERE combo = ?"
        params = (str(combo_name),)
    init_db()
    with closing(_connect()) as conn:
        return [(combo, code, date)
                for combo, code, date in conn.execute(sql, params)]


def signal_stats(combo_name=None, days=(1, 3, 5, 10)):
    """信号追踪表统计:各 N 天后成功率/平均收益/最大回撤。

    Args:
        combo_name: 只统计该组合(None = 全库聚合,组合列记「全部」)。
        days: 信号后 N 天元组,默认 (1, 3, 5, 10);非正整数抛 ValueError。

    Returns:
        DataFrame,列 = 组合/{N}天后成功率/{N}天后平均收益/{N}天后最大回撤
        (按 days 顺序)。库为空或组合无记录时返回仅含表头的空表,不抛错。
        每条信号按 (代码, 信号日期+N天) 先查买点面板、未命中再查确认面板,
        取匹配行 是否盈利 与 区间涨跌幅(N 天收益近似口径,见模块 docstring);
        匹配不到的行不计入该 N 统计;某 N 零匹配时对应列为 NaN。
    """
    if isinstance(days, (int, float)):
        days = (int(days),)
    days = tuple(int(d) for d in days)
    if any(d <= 0 for d in days):
        raise ValueError(f"days 必须为正整数:{days}")
    columns = ["组合"] + [f"{d}天后{stat}" for d in days
                          for stat in ("成功率", "平均收益", "最大回撤")]
    rows = _load_signal_rows(combo_name)
    if not rows:
        return pd.DataFrame(columns=columns)

    buy_idx = _buy_index_pair(load_panel())
    # 每条信号 × 每个 N:目标日期 = 信号日期 + N 天;先查买点面板,未命中留待确认面板
    outcomes = {}   # (i, d) -> (label, ret);未匹配不建键
    pending = []
    for i, (_, code, date) in enumerate(rows):
        base = _norm_date(date)
        norm_code = _norm_code(code)
        for d in days:
            key = (i, d)
            if not base or not norm_code:
                continue
            try:
                target = (datetime.strptime(base, "%Y-%m-%d")
                          + timedelta(days=d)).strftime("%Y-%m-%d")
            except ValueError:
                continue
            pair = buy_idx.get((norm_code, target))
            if pair is None:
                pending.append((key, norm_code, target))
            else:
                outcomes[key] = pair
    if pending:
        found = _lookup_confirm_pair(load_confirm_panel(), pending)
        for key, norm_code, target in pending:
            pair = found.get((norm_code, int(target.replace("-", ""))))
            if pair is not None:
                outcomes[key] = pair

    row = {"组合": str(combo_name) if combo_name is not None else "全部"}
    for d in days:
        matched = [(i, lab, ret) for (i, day), (lab, ret) in outcomes.items()
                   if day == d]
        if not matched:
            row[f"{d}天后成功率"] = np.nan
            row[f"{d}天后平均收益"] = np.nan
            row[f"{d}天后最大回撤"] = np.nan
            continue
        labels = pd.to_numeric(pd.Series([lab for _, lab, _ in matched]),
                               errors="coerce").fillna(0)
        rets = pd.to_numeric(pd.Series([ret for _, _, ret in matched]),
                             errors="coerce").dropna()
        row[f"{d}天后成功率"] = float((labels == 1).mean())
        row[f"{d}天后平均收益"] = (float(rets.mean()) if len(rets) else np.nan)
        # 最大回撤:匹配行按 (信号日期归一, 行序) 升序的累计收益曲线(口径同引擎)
        dated = sorted(((i, rows[i][2], ret) for i, _, ret in matched),
                       key=lambda t: (_norm_date(t[1]) or "", t[0]))
        row[f"{d}天后最大回撤"] = _max_drawdown([ret for _, _, ret in dated])
    return pd.DataFrame([row], columns=columns)


def failure_breakdown(combo_name=None):
    """失败原因六分类计数(包装 failure_db.failure_stats,补全六分类键)。

    combo_name=None 时全库聚合;未出现的分类按 0 计,返回 dict 恒含六分类键。
    """
    stats = failure_db.failure_stats(combo_name)
    return {cat: int(stats.get(cat, 0)) for cat in failure_db.CATEGORIES}
