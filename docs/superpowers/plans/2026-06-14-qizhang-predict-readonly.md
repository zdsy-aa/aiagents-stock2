# 起涨预测 只读展示 + 日调度（方案A）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把回测 v2 的 C4 策略变成每天自动更新、前台只读、自我验证战绩的观察页（纯 paper-tracking，不下单/不发邮件）。

**Architecture:** 仿 chanlun-updater sidecar：新容器 `qizhang-updater` 每日 20:30 跑 `qizhang_batch.py`（重训 GBDT 扩展窗 → 今日 top-10 候选 → realized 回填 C4 退出收益 → 写 `data/qizhang_picks.db`）；前台新建只读页 `qizhang_predict_ui.py`，经 `views/sidebar.py` 按钮 + `views/page_router.py` 路由接入。

**Tech Stack:** Python（numpy/pandas/lightgbm）、sqlite（BaseDatabase）、Streamlit、Docker sidecar、GNU sh 调度。

**关键工程约束（务必遵守）：**
- `qizhang_batch.py` 的**纯逻辑 helper 只依赖 numpy/pandas**（可在 host pytest 单测）；lightgbm / `build_panel` / `_load_kline` / `setup_modeling` 等重依赖**只在 `run_daily()` 内部 import**，不在模块顶层。
- `compute_realized` 通过参数注入 `simulate_fn`（=`setup_backtest.simulate_trade`），保证与 C4 回测同口径且单测可控。
- develop on `main`；脚本根目录运行；复用容器 `agentsstock1`（主镜像）；sidecar 复用同一镜像。
- 复用函数真实签名（已核对，勿改）：
  - `setup_modeling.build_panel(limit=0)` 保存 `PANEL=/app/data/profit_mining/setup_panel.npz`（`X[n,21] f32, Y[n,4] f32, dates int64, codes object, cols, label_names`）；`LABELS[1]=("fwd_10_10",...)`。
  - `setup_modeling.col_median(X)` / `fill_na(X, med)` / `fit_gbdt(X, y, scale_pos_weight=1.0)`（lazy import lightgbm，返回 booster，`bst.predict(X)`）/ `_subsample_train(Xtr, ytr, ratio=5, seed=0)`。
  - `setup_backtest.simulate_trade(o,h,l,c, entry_idx, mode="fixed", tp=0.10, sl=-0.05, maxhold=10, cost=0.002, trail=0.08, ma=None) -> (exit_idx, gross, net, reason) | None`；`select_topn(day_codes, day_scores, held, topn=10)`；`_riskoff_days() -> set[datetime64[D]]`（上证收盘<MA20）。
  - `mine_commonality._load_kline(code) -> DataFrame`（index=DatetimeIndex，列含 Open/High/Low/Close）/ `_universe() -> sorted list[str]`。
  - `base_db.BaseDatabase`：`__init__(db_path)`（裸文件名落 DATA_DIR），`conn()` 上下文管理器（自动 commit/rollback，WAL）。

---

## File Structure

| 文件 | 责任 |
|------|------|
| `qizhang_picks_db.py`（新，根目录） | `QizhangPicksDatabase(BaseDatabase)`：daily_picks / realized / run_meta 三表 + CRUD |
| `qizhang_batch.py`（新，根目录） | 纯 helper（numpy/pandas）+ `run_daily()` 重活编排 |
| `qizhang_predict_ui.py`（新，根目录） | `display_qizhang_predict()` 只读页（免责+回测结论+今日候选+战绩表） |
| `qizhang_schedule.sh`（新，根目录） | 每日定时 + 交易日门控 + flock（仿 chanlun_schedule.sh） |
| `docker-compose.yml`（改） | 加 `qizhang-updater` sidecar 服务 |
| `views/sidebar.py`（改） | 「选股板块」加「📈 起涨预测(观察中)」按钮 |
| `views/page_router.py`（改） | 加 `show_qizhang` 分派 |
| `tests/test_qizhang_picks_db.py`（新） | DB round-trip |
| `tests/test_qizhang_batch_logic.py`（新） | 纯 helper 单测（含 realized 用真实 simulate_trade） |
| `tests/test_ui_pages_smoke.py`（改） | 参数化加 `show_qizhang` |

---

## Task 1: qizhang_picks_db.py — 落库层

**Files:**
- Create: `qizhang_picks_db.py`
- Test: `tests/test_qizhang_picks_db.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_qizhang_picks_db.py
"""QizhangPicksDatabase round-trip：daily_picks / realized / run_meta。"""
import tempfile, os
import pytest
from qizhang_picks_db import QizhangPicksDatabase


def _db():
    d = tempfile.mkdtemp()
    return QizhangPicksDatabase(db_path=os.path.join(d, "qz.db"))


def test_save_and_get_daily_picks():
    db = _db()
    picks = [
        {"code": "600000", "name": "浦发", "score": 0.9, "rank": 1, "entry_ref_price": 10.0},
        {"code": "000001", "name": "平安", "score": 0.8, "rank": 2, "entry_ref_price": 12.0},
    ]
    db.save_daily_picks("2026-06-14", picks, riskoff=False)
    df = db.get_picks_by_date("2026-06-14")
    assert len(df) == 2
    assert set(df["code"]) == {"600000", "000001"}
    assert int(df[df["code"] == "600000"]["rank"].iloc[0]) == 1
    assert int(df[df["code"] == "600000"]["riskoff"].iloc[0]) == 0


def test_riskoff_day_saves_no_picks_but_flag():
    db = _db()
    db.save_daily_picks("2026-06-14", [], riskoff=True)
    assert db.get_picks_by_date("2026-06-14").empty
    # run_meta 单独记 gate(见 save_run_meta)；daily_picks 空属正常


def test_latest_pick_date():
    db = _db()
    db.save_daily_picks("2026-06-12", [{"code": "600000", "name": "x", "score": 1.0, "rank": 1, "entry_ref_price": 1.0}], riskoff=False)
    db.save_daily_picks("2026-06-14", [{"code": "000001", "name": "y", "score": 1.0, "rank": 1, "entry_ref_price": 1.0}], riskoff=False)
    assert db.get_latest_pick_date() == "2026-06-14"


def test_get_latest_pick_date_empty_is_none():
    assert _db().get_latest_pick_date() is None


def test_unrealized_picks_excludes_riskoff_and_realized():
    db = _db()
    db.save_daily_picks("2026-06-12", [
        {"code": "600000", "name": "x", "score": 1.0, "rank": 1, "entry_ref_price": 1.0},
        {"code": "000001", "name": "y", "score": 0.9, "rank": 2, "entry_ref_price": 1.0},
    ], riskoff=False)
    db.save_realized([{"scan_date": "2026-06-12", "code": "600000", "exit_date": "2026-06-20",
                       "holding_days": 6, "realized_return": 0.05, "hit_10pct": False,
                       "exit_reason": "到期", "bench_return": 0.01}])
    pending = db.get_unrealized_picks()
    assert ("2026-06-12", "000001") in pending
    assert ("2026-06-12", "600000") not in pending  # 已回填


def test_save_and_get_realized_stats():
    db = _db()
    db.save_realized([
        {"scan_date": "2026-06-12", "code": "600000", "exit_date": "2026-06-20",
         "holding_days": 6, "realized_return": 0.05, "hit_10pct": True,
         "exit_reason": "移动止盈", "bench_return": 0.01},
        {"scan_date": "2026-06-12", "code": "000001", "exit_date": "2026-06-19",
         "holding_days": 5, "realized_return": -0.05, "hit_10pct": False,
         "exit_reason": "止损", "bench_return": 0.02},
    ])
    df = db.get_realized_df()
    assert len(df) == 2
    assert abs(df["realized_return"].mean() - 0.0) < 1e-9


def test_save_and_get_run_meta():
    db = _db()
    db.save_run_meta("2026-06-14", model_train_rows=12345, train_end_date="2026-05-30",
                     sh_ma20_gate=False, status="ok")
    m = db.get_latest_run_meta()
    assert m["scan_date"] == "2026-06-14"
    assert m["status"] == "ok"
    assert int(m["sh_ma20_gate"]) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_qizhang_picks_db.py -q`
Expected: FAIL（`ModuleNotFoundError: qizhang_picks_db`）

- [ ] **Step 3: Implement qizhang_picks_db.py**

```python
# qizhang_picks_db.py
"""起涨预测 paper-tracking 落库（沿用 BaseDatabase.conn() 风格）。

三表：
- daily_picks：每日 top-N 候选(scan_date 当日)。riskoff 日不写候选,只在 run_meta 记 gate。
- realized   ：候选到期后回填的 C4(移动止盈)退出结果。
- run_meta   ：每次批跑一行,可观测。
"""
import logging

import pandas as pd

from base_db import BaseDatabase

_PICK_COLS = ["scan_date", "code", "name", "score", "rank", "entry_ref_price", "riskoff"]
_REAL_COLS = ["scan_date", "code", "exit_date", "holding_days", "realized_return",
              "hit_10pct", "exit_reason", "bench_return"]


class QizhangPicksDatabase(BaseDatabase):
    def __init__(self, db_path="qizhang_picks.db"):
        self.logger = logging.getLogger(__name__)
        super().__init__(db_path)

    def init_tables(self):
        with self.conn() as conn:
            conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_picks (
                scan_date TEXT NOT NULL,
                code TEXT NOT NULL,
                name TEXT,
                score REAL,
                rank INTEGER,
                entry_ref_price REAL,
                riskoff INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(scan_date, code)
            )""")
            conn.execute("""
            CREATE TABLE IF NOT EXISTS realized (
                scan_date TEXT NOT NULL,
                code TEXT NOT NULL,
                exit_date TEXT,
                holding_days INTEGER,
                realized_return REAL,
                hit_10pct INTEGER,
                exit_reason TEXT,
                bench_return REAL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(scan_date, code)
            )""")
            conn.execute("""
            CREATE TABLE IF NOT EXISTS run_meta (
                scan_date TEXT PRIMARY KEY,
                model_train_rows INTEGER,
                train_end_date TEXT,
                sh_ma20_gate INTEGER,
                status TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )""")

    def save_daily_picks(self, scan_date, picks, riskoff=False):
        """picks: list[dict(code,name,score,rank,entry_ref_price)]。riskoff 日通常传 []。"""
        with self.conn() as conn:
            conn.execute("DELETE FROM daily_picks WHERE scan_date=?", (scan_date,))
            for p in picks:
                conn.execute(
                    f"INSERT INTO daily_picks ({','.join(_PICK_COLS)}) "
                    f"VALUES ({','.join(['?'] * len(_PICK_COLS))})",
                    (scan_date, p["code"], p.get("name"), p.get("score"),
                     p.get("rank"), p.get("entry_ref_price"), 1 if riskoff else 0))
        return len(picks)

    def get_picks_by_date(self, scan_date) -> pd.DataFrame:
        with self.conn() as conn:
            return pd.read_sql_query(
                "SELECT * FROM daily_picks WHERE scan_date=? ORDER BY rank", conn,
                params=(scan_date,))

    def get_latest_pick_date(self):
        with self.conn() as conn:
            row = conn.execute("SELECT MAX(scan_date) FROM daily_picks").fetchone()
        return row[0] if row and row[0] else None

    def get_unrealized_picks(self):
        """返回尚未回填 realized 的 (scan_date, code) 列表（仅非 riskoff 候选）。"""
        with self.conn() as conn:
            rows = conn.execute("""
                SELECT d.scan_date, d.code FROM daily_picks d
                LEFT JOIN realized r ON d.scan_date=r.scan_date AND d.code=r.code
                WHERE d.riskoff=0 AND r.code IS NULL
            """).fetchall()
        return [(r[0], r[1]) for r in rows]

    def save_realized(self, rows):
        """rows: list[dict(_REAL_COLS)]。"""
        if not rows:
            return 0
        with self.conn() as conn:
            for r in rows:
                conn.execute(
                    f"INSERT OR REPLACE INTO realized ({','.join(_REAL_COLS)}) "
                    f"VALUES ({','.join(['?'] * len(_REAL_COLS))})",
                    (r["scan_date"], r["code"], r.get("exit_date"), r.get("holding_days"),
                     r.get("realized_return"), 1 if r.get("hit_10pct") else 0,
                     r.get("exit_reason"), r.get("bench_return")))
        return len(rows)

    def get_realized_df(self) -> pd.DataFrame:
        with self.conn() as conn:
            return pd.read_sql_query("SELECT * FROM realized ORDER BY scan_date, code", conn)

    def save_run_meta(self, scan_date, model_train_rows, train_end_date, sh_ma20_gate, status):
        with self.conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO run_meta
                (scan_date, model_train_rows, train_end_date, sh_ma20_gate, status)
                VALUES (?, ?, ?, ?, ?)
            """, (scan_date, int(model_train_rows), train_end_date,
                  1 if sh_ma20_gate else 0, status))

    def get_latest_run_meta(self):
        with self.conn() as conn:
            conn.row_factory = None
            row = conn.execute(
                "SELECT scan_date, model_train_rows, train_end_date, sh_ma20_gate, status "
                "FROM run_meta ORDER BY scan_date DESC LIMIT 1").fetchone()
        if not row:
            return None
        return {"scan_date": row[0], "model_train_rows": row[1], "train_end_date": row[2],
                "sh_ma20_gate": row[3], "status": row[4]}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_qizhang_picks_db.py -q`
Expected: PASS（8 passed）

- [ ] **Step 5: Commit**

```bash
git add qizhang_picks_db.py tests/test_qizhang_picks_db.py
git commit -m "feat(qizhang): paper-tracking 落库层 QizhangPicksDatabase(3表)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: qizhang_batch.py — 纯逻辑 helper

**Files:**
- Create: `qizhang_batch.py`（仅 helper 部分；`run_daily` 在 Task 3）
- Test: `tests/test_qizhang_batch_logic.py`

**注意：** 本文件顶层**只 import numpy/pandas**。`compute_realized` 通过 `simulate_fn` 注入退出模拟函数。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_qizhang_batch_logic.py
"""qizhang_batch 纯逻辑：今日行选取 / 候选排名 / 择时 gate / realized 回填(真实 simulate_trade)。"""
import os, sys

import numpy as np
import pandas as pd
import pytest

import qizhang_batch as QB

# realized 用真实 C4 退出口径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "data", "profit_mining"))
from setup_backtest import simulate_trade  # noqa: E402


def test_label_index():
    names = np.array(["fwd_6_20", "fwd_10_10", "fwd_10_20", "excess_10_20"])
    assert QB.label_index(names, "fwd_10_10") == 1


def test_latest_date_mask():
    dates = np.array(["2026-06-10", "2026-06-12", "2026-06-12"], dtype="datetime64[D]")
    m = QB.latest_date_mask(dates)
    assert list(m) == [False, True, True]


def test_build_ranked_picks_sorts_desc_and_caps_topn():
    codes = np.array(["a", "b", "c"], dtype=object)
    scores = np.array([0.2, 0.9, 0.5])
    picks = QB.build_ranked_picks(codes, scores, topn=2)
    assert [p["code"] for p in picks] == ["b", "c"]
    assert [p["rank"] for p in picks] == [1, 2]
    assert picks[0]["score"] == pytest.approx(0.9)


def test_is_riskoff():
    ro = {np.datetime64("2026-06-12")}
    assert QB.is_riskoff(np.datetime64("2026-06-12"), ro) is True
    assert QB.is_riskoff(np.datetime64("2026-06-11"), ro) is False


def _kline(opens, highs, lows, closes, start="2026-01-01"):
    idx = pd.bdate_range(start, periods=len(opens))
    return pd.DataFrame({"Open": opens, "High": highs, "Low": lows, "Close": closes}, index=idx)


def test_compute_realized_trailing_take_profit():
    # 入场=次日开盘10;涨到峰值12后回撤破 12*0.92=11.04 → 移动止盈
    o = [10, 10, 10, 10, 10, 10]
    h = [10, 10, 12, 12, 11, 11]
    l = [10, 10, 10, 11, 10, 10]
    c = [10, 10, 11, 11, 10, 10]
    df = _kline(o, h, l, c)
    scan_date = df.index[0].strftime("%Y-%m-%d")  # entry=次日(index1)开盘
    idx_close = pd.Series([3000.0] * len(df), index=df.index)
    r = QB.compute_realized(df, scan_date, idx_close, simulate_trade, maxhold=30)
    assert r is not None
    assert r["exit_reason"] == "移动止盈"
    assert r["hit_10pct"] is True          # 峰值12 ≥ 入场10×1.1
    assert r["realized_return"] < 0.12      # 扣成本后约 11.04/10-1-0.002


def test_compute_realized_not_mature_returns_none():
    df = _kline([10, 10], [10, 10], [10, 10], [10, 10])
    scan_date = df.index[0].strftime("%Y-%m-%d")
    idx_close = pd.Series([3000.0, 3000.0], index=df.index)
    # 仅 2 根 bar,入场后不足 maxhold → 未到期
    assert QB.compute_realized(df, scan_date, idx_close, simulate_trade, maxhold=30) is None


def test_compute_realized_scan_date_not_in_kline_returns_none():
    df = _kline([10, 10, 10], [10, 10, 10], [10, 10, 10], [10, 10, 10])
    idx_close = pd.Series([3000.0] * 3, index=df.index)
    assert QB.compute_realized(df, "1990-01-01", idx_close, simulate_trade, maxhold=30) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_qizhang_batch_logic.py -q`
Expected: FAIL（`ModuleNotFoundError: qizhang_batch`）

- [ ] **Step 3: Implement qizhang_batch.py helper 段**

```python
# qizhang_batch.py
"""起涨预测 paper-tracking 日批：纯 helper(numpy/pandas) + run_daily(重活)。

纯 helper 段不 import lightgbm / setup_modeling / _load_kline,可在 host 单测。
run_daily 段把重依赖关进函数内部,仅由 sidecar(容器,主镜像)调用。
"""
import numpy as np
import pandas as pd

TOPN = 10
MAXHOLD = 30      # C4: trailing maxhold
TRAIL = 0.08      # C4: 8% 回撤移动止盈
SL = -0.05        # C4: 硬止损
COST = 0.002
LABEL = "fwd_10_10"


def label_index(label_names, label=LABEL):
    """panel label_names 数组中目标标签的列下标。"""
    return list(label_names).index(label)


def latest_date_mask(dates):
    """dates(datetime64[D]) -> 最新日期的布尔掩码。"""
    dates = np.asarray(dates, dtype="datetime64[D]")
    return dates == dates.max()


def build_ranked_picks(codes, scores, topn=TOPN):
    """按分降序取前 topn -> list[dict(code,score,rank)]。"""
    order = np.argsort(np.asarray(scores, float))[::-1][:topn]
    return [{"code": codes[j], "score": float(scores[j]), "rank": i + 1}
            for i, j in enumerate(order)]


def is_riskoff(date, riskoff_set):
    """该交易日上证是否 risk-off(<MA20)。date/riskoff_set 元素均 datetime64[D]。"""
    return np.datetime64(date, "D") in riskoff_set


def compute_realized(df, scan_date, idx_close, simulate_fn, maxhold=MAXHOLD,
                     trail=TRAIL, sl=SL, cost=COST):
    """对某候选(scan_date 当日的 code 的 kline df)算 C4(移动止盈)退出结果。

    入场=scan_date 次一根开盘;未到期(不足完整 maxhold 窗)或 scan_date 不在 df → None。
    返回 dict(exit_date, holding_days, realized_return, hit_10pct, exit_reason, bench_return)。
    """
    ts = pd.Timestamp(scan_date)
    if ts not in df.index:
        return None
    scan_idx = df.index.get_loc(ts)
    entry_idx = scan_idx + 1
    if entry_idx + maxhold > len(df):     # 完整持有窗未走完 → 未到期
        return None
    o = df["Open"].to_numpy(float); h = df["High"].to_numpy(float)
    lo = df["Low"].to_numpy(float); c = df["Close"].to_numpy(float)
    res = simulate_fn(o, h, lo, c, entry_idx, mode="trailing",
                      maxhold=maxhold, trail=trail, sl=sl, cost=cost)
    if res is None:
        return None
    exit_idx, gross, net, reason = res
    entry = o[entry_idx]
    hit_10pct = bool(h[entry_idx:exit_idx + 1].max() >= entry * 1.10)
    entry_date = df.index[entry_idx]; exit_date = df.index[exit_idx]
    bench_return = None
    if idx_close is not None and entry_date in idx_close.index and exit_date in idx_close.index:
        bench_return = float(idx_close.loc[exit_date] / idx_close.loc[entry_date] - 1.0)
    return {"exit_date": exit_date.strftime("%Y-%m-%d"),
            "holding_days": int(exit_idx - entry_idx + 1),
            "realized_return": float(net), "hit_10pct": hit_10pct,
            "exit_reason": reason, "bench_return": bench_return}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_qizhang_batch_logic.py -q`
Expected: PASS（7 passed）。若 `from setup_backtest import simulate_trade` 在 host 因传递依赖失败，记录实际报错并改为容器内跑该测试文件（`docker exec -w /app agentsstock1 python3 -m pytest tests/test_qizhang_batch_logic.py -q`），并在提交信息注明。

- [ ] **Step 5: Commit**

```bash
git add qizhang_batch.py tests/test_qizhang_batch_logic.py
git commit -m "feat(qizhang): 日批纯逻辑 helper(今日行/排名/择时gate/realized回填)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: qizhang_batch.py — run_daily 重活编排

**Files:**
- Modify: `qizhang_batch.py`（追加 `run_daily` + `__main__`）

无 pytest（依赖 lightgbm + 全市场 panel）；由 Task 7 容器端到端验证。本任务只写代码 + 语法检查。

- [ ] **Step 1: 追加 run_daily 与入口到 qizhang_batch.py**

```python
# ── 以下追加到 qizhang_batch.py 末尾 ──
import os
import sys
import time
import logging

PROFIT_DIR = "/app/data/profit_mining"

logger = logging.getLogger(__name__)


def _today_str():
    return time.strftime("%Y-%m-%d")


def run_daily(db, limit=0):
    """每日批：重建 panel → 训练 GBDT(扩展窗) → 今日 top-N → 落库 → realized 回填。

    db: QizhangPicksDatabase。limit>0 仅用于 smoke(限票池)。重依赖在此函数内 import。
    """
    if PROFIT_DIR not in sys.path:
        sys.path.insert(0, PROFIT_DIR)
    import setup_modeling as SM
    import setup_backtest as BT
    from mine_commonality import _load_kline

    scan_date = _today_str()
    try:
        # 1. 重建全市场 panel(最新本地K线)
        SM.build_panel(limit=limit)
        d = np.load(SM.PANEL, allow_pickle=True)
        X = d["X"]; Y = d["Y"]; dates = d["dates"].astype("datetime64[D]")
        codes = d["codes"]; label_names = d["label_names"]

        # 2. 训练 GBDT：全部有效标签行(扩展窗)
        j = label_index(label_names, LABEL)
        y = Y[:, j].astype(float)
        valid = ~np.isnan(y)
        med = SM.col_median(X[valid])
        Xtr = SM.fill_na(X[valid], med); ytr = y[valid]
        Xsub, ysub = SM._subsample_train(Xtr, ytr, ratio=5)
        bst = SM.fit_gbdt(Xsub, ysub)
        train_end = str(dates[valid].max())

        # 3. 给今日 bar 打分
        today_m = latest_date_mask(dates)
        Xtoday = SM.fill_na(X[today_m], med)
        sc = bst.predict(Xtoday)
        today_codes = codes[today_m]
        latest_date = dates.max()

        # 4. C4 大盘择时 gate
        riskoff_set = BT._riskoff_days()
        gate = is_riskoff(latest_date, riskoff_set)

        # 5. 候选落库（riskoff 日不产候选）
        if gate:
            db.save_daily_picks(scan_date, [], riskoff=True)
            logger.info("[起涨] %s risk-off(上证<MA20),今日不开新仓", scan_date)
        else:
            picks = build_ranked_picks(today_codes, sc, topn=TOPN)
            for p in picks:
                p["name"] = ""  # 名称非必需,留空(前台可后补);避免额外依赖
                df = _load_kline(p["code"])
                p["entry_ref_price"] = (float(df["Close"].iloc[-1])
                                        if df is not None and len(df) else None)
            db.save_daily_picks(scan_date, picks, riskoff=False)
            logger.info("[起涨] %s 产候选 %d 只", scan_date, len(picks))

        # 6. realized 回填到期候选
        new_real = []
        idx_close = SM._load_index_close()
        for sd, code in db.get_unrealized_picks():
            df = _load_kline(code)
            if df is None:
                continue
            r = compute_realized(df, sd, idx_close, BT.simulate_trade)
            if r is not None:
                r.update(scan_date=sd, code=code)
                new_real.append(r)
        db.save_realized(new_real)
        logger.info("[起涨] realized 回填 %d 条", len(new_real))

        db.save_run_meta(scan_date, model_train_rows=int(valid.sum()),
                         train_end_date=train_end, sh_ma20_gate=gate, status="ok")
        return True
    except Exception:
        logger.exception("[起涨] 日批失败")
        db.save_run_meta(scan_date, model_train_rows=0, train_end_date="",
                         sh_ma20_gate=False, status="failed")
        return False


def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    from qizhang_picks_db import QizhangPicksDatabase
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    db = QizhangPicksDatabase()
    ok = run_daily(db, limit=limit)
    print("[起涨日批] 完成" if ok else "[起涨日批] 失败", flush=True)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 语法检查**

Run: `python3 -c "import ast; ast.parse(open('qizhang_batch.py').read()); print('syntax OK')"`
Expected: `syntax OK`

- [ ] **Step 3: 确认纯逻辑测试仍通过（顶层未引入重依赖）**

Run: `python3 -m pytest tests/test_qizhang_batch_logic.py -q`
Expected: PASS（导入 qizhang_batch 不应触发 lightgbm；run_daily 内的 import 仅在调用时执行）

- [ ] **Step 4: Commit**

```bash
git add qizhang_batch.py
git commit -m "feat(qizhang): run_daily 编排(重训扩展窗→今日topN→C4择时→realized回填)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: qizhang_predict_ui.py — 只读页

**Files:**
- Create: `qizhang_predict_ui.py`
- Test: 经 Task 5 的 `test_ui_pages_smoke` 覆盖

页面读 `QizhangPicksDatabase`，空库不崩。回测结论用固化常量（不运行期依赖离线 md）。

- [ ] **Step 1: Implement qizhang_predict_ui.py**

```python
# qizhang_predict_ui.py
"""起涨预测(观察中) 只读页：免责+诚实局限 / C4 回测结论 / 今日候选 / 实盘外战绩表。

纯展示,读 data/qizhang_picks.db。不下单/不发邮件。
"""
import logging

import pandas as pd
import streamlit as st

from qizhang_picks_db import QizhangPicksDatabase

logger = logging.getLogger(__name__)

# C4 回测结论(固化常量,来源:report/起涨回测v2_20260614_*,OOS 2024-01~2025-10)
_BACKTEST = {
    "累计": "+39.8%", "年化": "+21.0%", "Sharpe": "3.27",
    "最大回撤": "-3.1%", "超额(vs上证)": "+6.3%", "上证同期": "+33.5%",
}


@st.cache_data(ttl=1800, show_spinner=False)
def _load():
    db = QizhangPicksDatabase()
    latest = db.get_latest_pick_date()
    picks = db.get_picks_by_date(latest) if latest else pd.DataFrame()
    realized = db.get_realized_df()
    meta = db.get_latest_run_meta()
    return latest, picks, realized, meta


def display_qizhang_predict():
    st.header("📈 起涨预测（观察中）")

    # 1. 免责 + 诚实局限
    st.warning(
        "⚠️ **paper-tracking 观察，非投资建议。** 这是「起涨模型 C4 策略」的实盘外跟踪，"
        "不下单、不构成任何买卖建议。\n\n"
        "**诚实局限**：① Sharpe 受回测「槽位法」净值影响偏高，累计/超额比 Sharpe 量级更可信；"
        "② 回测仅单一 OOS 期(2024-2025 牛市)，非跨牛熊 walk-forward，换震荡/熊市表现会变；"
        "③ 未建模涨跌停/停牌不可成交，滑点仅按固定 0.2% 估算。")

    try:
        latest, picks, realized, meta = _load()
    except Exception as e:
        logger.exception("起涨预测页加载失败")
        st.info("尚无数据（日批未跑或库未生成）。")
        return

    # 2. C4 回测结论(静态)
    st.subheader("📊 C4 策略回测结论（OOS 2024-01~2025-10）")
    cols = st.columns(len(_BACKTEST))
    for col, (k, v) in zip(cols, _BACKTEST.items()):
        col.metric(k, v)
    st.caption("C4 = 移动止盈(8%回撤) + 大盘择时(上证<MA20 停开仓)；每日 top10 等权、t+1 开盘买、扣 0.2% 成本。")

    # 3. 今日候选
    st.subheader("🎯 今日候选")
    if meta and meta.get("status") == "failed":
        st.error("今日批跑失败，未产候选。")
    elif meta and int(meta.get("sh_ma20_gate") or 0) == 1:
        st.info("🛡️ 今日大盘择时＝避险（上证收盘<MA20），按 C4 规则**不开新仓**。")
    elif latest and not picks.empty:
        st.caption(f"扫描日：{latest}（共 {len(picks)} 只）")
        show = picks[["rank", "code", "name", "score", "entry_ref_price"]].copy()
        show.columns = ["排名", "代码", "名称", "模型分", "参考价(最新收盘)"]
        st.dataframe(show, hide_index=True, width="stretch")
    else:
        st.info("尚无今日候选（日批未跑）。")

    # 4. 实盘外战绩表
    st.subheader("📈 实盘外战绩（随时间生长）")
    if realized is None or realized.empty:
        st.info("样本积累中（候选需 ≥1 个完整持有窗到期后才计入战绩）。")
    else:
        n = len(realized)
        win = float((realized["realized_return"] > 0).mean())
        hit = float((realized["hit_10pct"] == 1).mean())
        avg = float(realized["realized_return"].mean())
        cum = float((1.0 + realized["realized_return"]).prod() - 1.0)
        bench = realized["bench_return"].dropna()
        bench_cum = float((1.0 + bench).prod() - 1.0) if len(bench) else 0.0
        c = st.columns(5)
        c[0].metric("已到期候选", n)
        c[1].metric("胜率", f"{win:.1%}")
        c[2].metric("命中+10%率", f"{hit:.1%}")
        c[3].metric("平均净收益", f"{avg:+.2%}")
        c[4].metric("累计 vs 上证", f"{cum:+.1%} / {bench_cum:+.1%}")
        st.caption("退出原因分布：" + "，".join(
            f"{k} {v}" for k, v in realized["exit_reason"].value_counts().items()))
```

- [ ] **Step 2: 语法检查**

Run: `python3 -c "import ast; ast.parse(open('qizhang_predict_ui.py').read()); print('syntax OK')"`
Expected: `syntax OK`

- [ ] **Step 3: Commit**

```bash
git add qizhang_predict_ui.py
git commit -m "feat(qizhang): 起涨预测只读页(免责+回测结论+今日候选+战绩表)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: 导航接线 + 冒烟

**Files:**
- Modify: `views/sidebar.py`（「选股板块」加按钮）
- Modify: `views/page_router.py`（加 `show_qizhang` 分派）
- Modify: `tests/test_ui_pages_smoke.py`（参数化加 `show_qizhang`）

- [ ] **Step 1: views/sidebar.py 在「🛡️ 稳定选股」按钮块之后加「📈 起涨预测」按钮**

定位 `views/sidebar.py` 中 `nav_stable`（🛡️ 稳定选股）按钮块（其 `for key in [...]` 清单结尾），在该 `if st.button(... key="nav_stable" ...): ...` 整块**之后**插入：

```python
            if st.button("📈 起涨预测(观察中)", width='stretch', key="nav_qizhang", help="起涨模型 C4 策略 paper-tracking 观察页(只读,不下单)"):
                st.session_state.show_qizhang = True
                for key in ['show_history', 'show_monitor', 'show_config', 'show_main_force',
                           'show_sector_strategy', 'show_longhubang', 'show_portfolio', 'show_low_price_bull',
                           'show_small_cap', 'show_profit_growth', 'show_value_stock', 'show_news_flow',
                           'show_macro_analysis', 'show_macro_cycle', 'show_smart_monitor', 'show_intraday',
                           'show_chanlun', 'show_liumai', 'show_combo', 'show_stable']:
                    if key in st.session_state:
                        del st.session_state[key]
```

- [ ] **Step 2: views/page_router.py 加分派（放在 `show_stable` 分派之后、`show_current_strategy` 之前或之后均可）**

在 `views/page_router.py` 的 `route_page()` 内，与其它 `if st.session_state.get(...): ...; return True` 同风格加：

```python
    if st.session_state.get('show_qizhang'):
        from qizhang_predict_ui import display_qizhang_predict
        display_qizhang_predict()
        return True
```

- [ ] **Step 3: tests/test_ui_pages_smoke.py 参数化加 show_qizhang**

定位 `test_page_renders_without_exception` 上方的 flag 列表（含 `"show_chanlun"`, `"show_current_strategy"` 等），在列表中追加 `"show_qizhang"`：

```python
    "show_chanlun",
    "show_current_strategy",
    "show_qizhang",
```

- [ ] **Step 4: 跑 UI 冒烟（空库下渲染不崩）**

Run: `python3 -m pytest tests/test_ui_pages_smoke.py -q`
Expected: PASS（页数 +1 全过；起涨预测页空库走「样本积累中/尚无今日候选」分支）

- [ ] **Step 5: Commit**

```bash
git add views/sidebar.py views/page_router.py tests/test_ui_pages_smoke.py
git commit -m "feat(qizhang): 侧栏按钮+路由接线+UI冒烟标志 show_qizhang

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: qizhang_schedule.sh — 调度壳

**Files:**
- Create: `qizhang_schedule.sh`

仿 `chanlun_schedule.sh`：GNU date 定时、交易日门控（跳过周末）、flock 防叠跑、写日志。

- [ ] **Step 1: 先读现有 chanlun_schedule.sh 全文以对齐风格**

Run: `cat chanlun_schedule.sh`
（按其 RUN_AT 计算/循环/flock/log 结构改写为起涨版；下面给出完整内容）

- [ ] **Step 2: Implement qizhang_schedule.sh**

```sh
#!/bin/sh
# qizhang_schedule.sh —— 起涨预测 paper-tracking 日批调度（sidecar qizhang-updater 用）。
# 复用主应用镜像；每天 20:30（CST，在 kline-updater 18:00、chanlun-updater 20:00 之后）跑
# qizhang_batch.py：重训 GBDT(扩展窗)→今日 top10 候选→realized 回填→写 data/qizhang_picks.db，
# 供「📈 起涨预测」页只读。busybox/GNU sh 兼容；时间用 GNU date（Debian 基础镜像）。
# 手动跑一次： docker exec qizhang-updater python3 /app/qizhang_batch.py
set -u
RUN_AT="${QIZHANG_RUN_AT:-20:30}"
LOG="/app/data/qizhang_update.log"
LOCK="/app/data/qizhang_update.lock"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') [$1] $2" | tee -a "$LOG"; }

log INFO "qizhang-updater 启动：每日 ${RUN_AT} 重训打分并产候选（依赖最新本地K线）"
while true; do
    now=$(date +%s)
    target=$(date -d "today ${RUN_AT}" +%s 2>/dev/null)
    if [ "$now" -ge "$target" ]; then
        target=$(date -d "tomorrow ${RUN_AT}" +%s)
    fi
    log INFO "下次重算：$(date -d "@${target}" '+%Y-%m-%d %H:%M') CST（约 $(( (target - now) / 60 )) 分钟后）"
    sleep "$(( target - now ))"

    dow=$(date +%u)   # 1=周一 .. 7=周日
    if [ "$dow" -ge 6 ]; then
        log INFO "周末（dow=${dow}），跳过本次"
        continue
    fi
    log INFO "开始起涨日批 ..."
    if flock -n "$LOCK" python3 /app/qizhang_batch.py >>"$LOG" 2>&1; then
        log INFO "起涨日批完成"
    else
        log WARN "起涨日批失败或已有实例在跑（flock）"
    fi
done
```

- [ ] **Step 3: 校验 sh 语法**

Run: `sh -n qizhang_schedule.sh && echo "sh syntax OK"`
Expected: `sh syntax OK`

- [ ] **Step 4: Commit**

```bash
git add qizhang_schedule.sh
git commit -m "feat(qizhang): 日批调度壳 qizhang_schedule.sh(20:30,交易日门控,flock)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: docker-compose qizhang-updater 服务 + 端到端验证

**Files:**
- Modify: `docker-compose.yml`（加 `qizhang-updater` 服务）

- [ ] **Step 1: 读现有 chanlun-updater 服务块以对齐挂载/环境**

Run: `sed -n '108,140p' docker-compose.yml`
（对齐 image/volumes/healthcheck/restart/depends_on）

- [ ] **Step 2: 在 docker-compose.yml 的 chanlun-updater 服务块之后加 qizhang-updater**

```yaml
  # 起涨预测 paper-tracking 每日 sidecar：复用主应用镜像，每天 20:30
  # （kline 18:00 / chanlun 20:00 之后）跑 qizhang_batch，写 data/qizhang_picks.db，
  # 供「📈 起涨预测」页只读。纯观察,不下单/不发邮件。
  qizhang-updater:
    image: aiagents-stock-app
    container_name: qizhang-updater
    logging: *default-logging
    command: ["sh", "/app/qizhang_schedule.sh"]
    environment:
      - TZ=Asia/Shanghai
      - LOCAL_DB_DIR=/app/tdx-data/database/kline
      - QIZHANG_RUN_AT=20:30
    volumes:
      - ./data:/app/data                 # 写 qizhang_picks.db / qizhang_update.log
      - ./.env:/app/.env
      - ./tdx-data:/app/tdx-data:ro      # 只读本地K线（route B）
      - ./qizhang_schedule.sh:/app/qizhang_schedule.sh:ro
    healthcheck:
      disable: true
    restart: unless-stopped
    depends_on:
      tdx-stock-web:
        condition: service_healthy
```

（`depends_on` 与 chanlun-updater 对齐；若现有 chanlun-updater 的 depends_on 写法不同，照其样式改。）

- [ ] **Step 3: 校验 compose 文件**

Run: `docker compose config >/dev/null && echo "compose OK"`
Expected: `compose OK`

- [ ] **Step 4: 重建主镜像（让 sidecar 拿到新 .py）**

Run: `docker compose build agentsstock1`
Expected: 构建成功（含新增根目录 .py）

- [ ] **Step 5: 端到端 smoke——容器内手动小票池跑一次**

Run:
```bash
docker compose up -d qizhang-updater
docker exec -w /app qizhang-updater sh -c 'NPROC=4 python3 /app/qizhang_batch.py 60'
```
Expected: 末行 `[起涨日批] 完成`；日志含「产候选 N 只」或「risk-off」；`data/qizhang_picks.db` 生成。
（`60` = 限 60 票池 smoke；正式每日跑无参数=全市场。）

- [ ] **Step 6: 验证落库 + 页面渲染**

Run:
```bash
docker exec -w /app qizhang-updater python3 -c "
from qizhang_picks_db import QizhangPicksDatabase
db=QizhangPicksDatabase()
print('latest', db.get_latest_pick_date())
print('meta', db.get_latest_run_meta())
print('picks', len(db.get_picks_by_date(db.get_latest_pick_date() or '')))
"
docker exec -w /app agentsstock1 python3 -m pytest tests/test_ui_pages_smoke.py -k qizhang -q
```
Expected: 打印出 latest 日期/meta(status ok)/候选数；冒烟 PASS（此时库非空，走候选/战绩分支）。

- [ ] **Step 7: Commit**

```bash
git add docker-compose.yml
git commit -m "feat(qizhang): docker-compose 加 qizhang-updater sidecar(每日20:30)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: 全量回归 + DATA_FILES 登记

**Files:**
- Modify: `data/profit_mining/DATA_FILES.md`（登记 qizhang_picks.db 产物，按「保留勿删」准则）

- [ ] **Step 1: 全量回归**

Run: `python3 -m pytest tests/ -q`
Expected: 全绿（在 #2 基线 251 passed 上新增 qizhang DB/逻辑/冒烟若干，0 failed/已知 1 skipped）

- [ ] **Step 2: DATA_FILES.md 登记新产物**

在 `data/profit_mining/DATA_FILES.md` 末尾「保留」区追加一行：

```markdown
> - qizhang_batch.py(根目录) → `data/qizhang_picks.db`(起涨预测 paper-tracking:daily_picks/realized/run_meta;每日 sidecar 写,前台只读) + `data/qizhang_update.log`。保留勿删(可重跑覆盖)。
```

- [ ] **Step 3: Commit**

```bash
git add data/profit_mining/DATA_FILES.md
git commit -m "docs(qizhang): DATA_FILES 登记 qizhang_picks.db 产物

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review（已执行，结论记录于此）

**1. Spec 覆盖**
- 每日重训扩展窗 → Task 3 run_daily（valid 全行训练 + 今日 bar 打分）✅
- 完整战绩表（realized C4 退出）→ Task 2 compute_realized + Task 3 回填 + Task 4 战绩段 ✅
- 新建独立导航页 → Task 4 + Task 5 ✅
- risk-off 不产候选不进战绩 → Task 3 gate 分支 + DB get_unrealized_picks(riskoff=0) ✅
- N=10 → TOPN 常量 ✅
- 三表 DB → Task 1 ✅
- sidecar 20:30 调度 → Task 6 + Task 7 ✅
- 免责/诚实局限上页 → Task 4 ✅
- 不下单/不发邮件/不进选股邮件/不碰 miniqmt → 全程无相关代码 ✅
- 测试（DB round-trip / 纯逻辑 / 页面冒烟）→ Task 1/2/5 ✅

**2. Placeholder 扫描**：无 TBD/TODO；run_daily 内 picks["name"]="" 为有意留空（已注释说明），非占位。

**3. 类型/签名一致性**：
- `compute_realized(df, scan_date, idx_close, simulate_fn, maxhold, trail, sl, cost)` 在 Task 2 定义、Task 3 调用一致（Task 3 用默认 trail/sl/cost）。
- `build_ranked_picks` 返回 dict 含 code/score/rank；Task 3 再补 name/entry_ref_price 后交 `save_daily_picks`（_PICK_COLS 对齐）✅。
- `QizhangPicksDatabase` 方法名（save_daily_picks/get_picks_by_date/get_latest_pick_date/get_unrealized_picks/save_realized/get_realized_df/save_run_meta/get_latest_run_meta）在 Task 1 定义、Task 3/4 调用一致 ✅。

**已知风险**：Task 2 host 单测依赖 `setup_backtest` 可在 host import；若失败，回退容器内跑该测试（Step 4 已写明）。
