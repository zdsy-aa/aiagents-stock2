# 六脉神剑选股 + 组合策略 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增六脉神剑选股（每日批量落库、前台只读+手动重算）、把选股板块重构为单策略/组合策略两组、并新增缠论×六脉组合策略（缠论买点±3交易日内六脉≥5红）。

**Architecture:** 纯函数引擎 `liumai_engine` 实现通达信六维指标；六脉与组合各自一套 db/batch/selector/ui（对齐现有 `chanlun_*` 模式）；组合只读 `chanlun_signals.db`。app.py 仅做导航分组 + 两个独立 `show_*` 路由。

**Tech Stack:** Python, pandas, numpy, Streamlit, SQLite(BaseDatabase), pytest(monkeypatch), Streamlit AppTest。

**Spec:** `docs/superpowers/specs/2026-05-30-liumai-and-combo-screening-design.md`

---

## File Structure

- Create `liumai_engine.py` — 六维指标纯函数引擎。
- Create `liumai_signal_db.py` — 六脉信号落库（BaseDatabase）。
- Create `liumai_batch.py` — 六脉批量扫描（全池→最新多头数≥5→落库）。
- Create `liumai_selector.py` — 六脉只读查询层。
- Create `liumai_ui.py` — 六脉页（只读表+🔄重算）。
- Create `combo_signal_db.py` — 组合信号落库。
- Create `combo_batch.py` — 组合扫描（缠论买点±3交易日内六脉≥5红）。
- Create `combo_selector.py` — 组合只读查询层。
- Create `combo_ui.py` — 组合页（只读表+🔄刷新）。
- Modify `app.py` — 选股板块分组 + 六脉/组合按钮 + 两个路由。
- Tests: `tests/test_liumai_engine.py`, `tests/test_liumai_signal_db.py`, `tests/test_liumai_batch.py`, `tests/test_liumai_selector.py`, `tests/test_combo_signal_db.py`, `tests/test_combo_batch.py`, `tests/test_combo_selector.py`, `tests/test_liumai_combo_ui_smoke.py`.

**Conventions:** tests run with `python3 -m pytest`（必须 python3）。`tests/conftest.py` 已把项目根加入 sys.path 并设 LOCAL_DB 环境变量，故可直接 `import liumai_engine`。`BaseDatabase` 裸文件名落到 `DATA_DIR`(默认 `data/`)；测试用临时目录 db_path 隔离。`chanlun_batch._load(symbol, kind, limit)` 返回标准 OHLCV(索引=日期)或 None。`chanlun_universe.list_universe()` 返回 `[(code,name,board), ...]`。

---

## Task 1: 六脉神剑引擎 `liumai_engine.py`

**Files:**
- Create: `liumai_engine.py`
- Test: `tests/test_liumai_engine.py`

- [ ] **Step 1: Write the failing test** — create `tests/test_liumai_engine.py`:

```python
# tests/test_liumai_engine.py
import numpy as np
import pandas as pd
from liumai_engine import (_tdx_sma, compute_flags, bull_count_series,
                           score_of, state_of, latest_snapshot, DIMS)


def _df(closes):
    """用收盘价序列构造 OHLC(High=close+0.5, Low=close-0.5)。索引为日期。"""
    closes = list(closes)
    idx = pd.date_range("2026-01-01", periods=len(closes), freq="D")
    return pd.DataFrame({
        "Open": closes, "High": [c + 0.5 for c in closes],
        "Low": [c - 0.5 for c in closes], "Close": closes,
        "Volume": [1] * len(closes),
    }, index=idx)


def test_tdx_sma_recursive():
    # SMA(X,2,1): y0=x0; y1=(1*x1+1*y0)/2; y2=(x2+y1)/2
    s = pd.Series([2.0, 4.0, 6.0])
    out = _tdx_sma(s, 2, 1)
    assert out.iloc[0] == 2.0
    assert out.iloc[1] == (4.0 + 2.0) / 2          # 3.0
    assert out.iloc[2] == (6.0 + 3.0) / 2          # 4.5


def test_strong_uptrend_all_bullish():
    df = _df([10 + i for i in range(60)])           # 持续上涨
    snap = latest_snapshot(df)
    assert snap is not None
    assert snap["bull_count"] == 6
    assert snap["score"] == 100
    assert snap["state"] == "强势"
    assert all(snap[d] == 1 for d in DIMS)


def test_downtrend_low_bull():
    df = _df([100 - i for i in range(60)])           # 持续下跌
    snap = latest_snapshot(df)
    assert snap is not None
    assert snap["bull_count"] <= 1
    assert snap["state"] == "偏空"


def test_insufficient_bars_returns_none():
    df = _df([10 + i for i in range(20)])            # <30 根
    assert latest_snapshot(df) is None
    assert bull_count_series(df).empty


def test_state_boundaries():
    assert state_of(100) == "强势"
    assert state_of(70) == "强势"
    assert state_of(40) == "偏多"
    assert state_of(21) == "震荡"
    assert state_of(20) == "偏空"
    assert state_of(0) == "偏空"


def test_bull_count_series_indexed_by_date():
    df = _df([10 + i for i in range(60)])
    bc = bull_count_series(df)
    assert len(bc) == 60
    assert (bc.index == df.index).all()
    assert bc.iloc[-1] == 6
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_liumai_engine.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'liumai_engine'`

- [ ] **Step 3: Write minimal implementation** — create `liumai_engine.py`:

```python
# liumai_engine.py
"""六脉神剑指标引擎(纯函数,零IO,零Streamlit)。按通达信公式实现
MACD/KDJ/RSI/LWR/BBI/MTM 六维多头判定 + 加权得分 + 四档状态。
输入日线 DataFrame(列 Open/High/Low/Close/Volume, 索引升序)。"""
from typing import Optional
import numpy as np
import pandas as pd

DIMS = ["MACD", "KDJ", "RSI", "LWR", "BBI", "MTM"]
_WEIGHTS = {"MACD": 20, "KDJ": 15, "RSI": 15, "LWR": 10, "BBI": 20, "MTM": 20}
_MIN_BARS = 30


def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def _tdx_sma(s: pd.Series, n: int, m: int) -> pd.Series:
    """通达信 SMA(X,N,M)=(M*X+(N-M)*前值)/N; 首个有效值取首个非 NaN 的 X。"""
    arr = s.to_numpy(dtype=float)
    out = np.full_like(arr, np.nan)
    prev = np.nan
    for i, x in enumerate(arr):
        if np.isnan(x):
            continue
        prev = x if np.isnan(prev) else (m * x + (n - m) * prev) / n
        out[i] = prev
    return pd.Series(out, index=s.index)


def compute_flags(df: pd.DataFrame) -> pd.DataFrame:
    """逐根六维多头布尔(列=DIMS, 索引=df.index)。NaN 预热期记 False。"""
    c = df["Close"].astype(float)
    h = df["High"].astype(float)
    l = df["Low"].astype(float)

    macd_fast = _ema(c, 8) - _ema(c, 13)
    macd = macd_fast > _ema(macd_fast, 5)

    llv8, hhv8 = l.rolling(8).min(), h.rolling(8).max()
    rsv = (c - llv8) / (hhv8 - llv8).replace(0, np.nan) * 100
    k = _tdx_sma(rsv, 3, 1)
    kdj = k > _tdx_sma(k, 3, 1)

    diff = c - c.shift(1)
    up, ab = diff.clip(lower=0), diff.abs()
    rsi_s = _tdx_sma(up, 5, 1) / _tdx_sma(ab, 5, 1).replace(0, np.nan) * 100
    rsi_l = _tdx_sma(up, 13, 1) / _tdx_sma(ab, 13, 1).replace(0, np.nan) * 100
    rsi = rsi_s > rsi_l

    hhv13, llv13 = h.rolling(13).max(), l.rolling(13).min()
    lwr_raw = (-(hhv13 - c)) / (hhv13 - llv13).replace(0, np.nan) * 100
    lwr_k = _tdx_sma(lwr_raw, 3, 1)
    lwr = lwr_k > _tdx_sma(lwr_k, 3, 1)

    bbi = (c.rolling(3).mean() + c.rolling(6).mean()
           + c.rolling(12).mean() + c.rolling(24).mean()) / 4
    bbi_bull = c > bbi

    chg = c - c.shift(1)
    mtm_s = 100 * _ema(_ema(chg, 5), 3) / _ema(_ema(chg.abs(), 5), 3).replace(0, np.nan)
    mtm_l = 100 * _ema(_ema(chg, 13), 8) / _ema(_ema(chg.abs(), 13), 8).replace(0, np.nan)
    mtm = mtm_s > mtm_l

    return pd.DataFrame({"MACD": macd, "KDJ": kdj, "RSI": rsi,
                         "LWR": lwr, "BBI": bbi_bull, "MTM": mtm}).fillna(False)


def bull_count_series(df: pd.DataFrame) -> pd.Series:
    """逐根多头数(0-6); df 过短(<30 根)返回空 Series。"""
    if df is None or len(df) < _MIN_BARS:
        return pd.Series(dtype=int)
    return compute_flags(df)[DIMS].sum(axis=1).astype(int)


def score_of(flags_row) -> int:
    """单根六维布尔 → 加权得分(0-100)。"""
    return int(sum(_WEIGHTS[d] for d in DIMS if bool(flags_row[d])))


def state_of(score: int) -> str:
    if score >= 70:
        return "强势"
    if score >= 40:
        return "偏多"
    if score > 20:
        return "震荡"
    return "偏空"


def latest_snapshot(df: pd.DataFrame) -> Optional[dict]:
    """最新一根快照; df 过短返回 None。"""
    if df is None or len(df) < _MIN_BARS:
        return None
    row = compute_flags(df).iloc[-1]
    score = score_of(row)
    snap = {
        "signal_date": pd.Timestamp(df.index[-1]).strftime("%Y-%m-%d"),
        "bull_count": int(sum(bool(row[d]) for d in DIMS)),
        "score": score, "state": state_of(score),
    }
    for d in DIMS:
        snap[d] = int(bool(row[d]))
    return snap
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_liumai_engine.py -v`
Expected: PASS（6 tests）。若 `test_strong_uptrend_all_bullish` 因纯线性序列某维边界未满足而非全多，可把上涨序列改成更陡（如 `10 + 1.5*i`）——这是测试夹具调参，不改实现。

- [ ] **Step 5: Commit**

```bash
git add liumai_engine.py tests/test_liumai_engine.py
git commit -m "feat(liumai): 六脉神剑六维指标引擎(纯函数)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: 六脉信号库 `liumai_signal_db.py`

**Files:**
- Create: `liumai_signal_db.py`
- Test: `tests/test_liumai_signal_db.py`

- [ ] **Step 1: Write the failing test** — create `tests/test_liumai_signal_db.py`:

```python
# tests/test_liumai_signal_db.py
import os, tempfile
from liumai_signal_db import LiumaiSignalDB


def _db():
    return LiumaiSignalDB(db_path=os.path.join(tempfile.mkdtemp(), "lm.db"))


def _row(code="600000", scan="2026-05-29", bull=6):
    return {"code": code, "name": "浦发", "board": "深主板",
            "signal_date": "2026-05-29", "bull_count": bull, "score": 100,
            "state": "强势", "macd": 1, "kdj": 1, "rsi": 1, "lwr": 1,
            "bbi": 1, "mtm": 1, "scan_date": scan}


def test_upsert_and_get_latest():
    db = _db()
    db.upsert_signals([_row(), _row(code="000001", bull=5)])
    df = db.get_latest_signals()
    assert len(df) == 2
    assert set(df["code"]) == {"600000", "000001"}


def test_get_latest_only_newest_batch():
    db = _db()
    db.upsert_signals([_row(scan="2026-05-28")])
    db.upsert_signals([_row(code="000001", scan="2026-05-29")])
    df = db.get_latest_signals()
    assert len(df) == 1 and df.iloc[0]["scan_date"] == "2026-05-29"


def test_upsert_conflict_updates():
    db = _db()
    db.upsert_signals([_row(bull=6)])
    db.upsert_signals([_row(bull=5)])          # 同 code+scan_date → 更新
    df = db.get_latest_signals()
    assert len(df) == 1 and int(df.iloc[0]["bull_count"]) == 5


def test_list_scan_dates_desc():
    db = _db()
    db.upsert_signals([_row(scan="2026-05-28")])
    db.upsert_signals([_row(code="000001", scan="2026-05-29")])
    assert db.list_scan_dates() == ["2026-05-29", "2026-05-28"]


def test_clear_scan():
    db = _db()
    db.upsert_signals([_row(scan="2026-05-29")])
    db.clear_scan("2026-05-29")
    assert db.get_latest_signals().empty
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_liumai_signal_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'liumai_signal_db'`

- [ ] **Step 3: Write minimal implementation** — create `liumai_signal_db.py`:

```python
# liumai_signal_db.py
"""六脉神剑选股信号落库(沿用 BaseDatabase.conn() 风格)。"""
import logging
import pandas as pd
from base_db import BaseDatabase

_COLS = ["code", "name", "board", "signal_date", "bull_count", "score", "state",
         "macd", "kdj", "rsi", "lwr", "bbi", "mtm", "scan_date"]


class LiumaiSignalDB(BaseDatabase):
    def __init__(self, db_path="liumai_signals.db"):
        self.logger = logging.getLogger(__name__)
        super().__init__(db_path)

    def init_tables(self):
        with self.conn() as conn:
            conn.execute("""
            CREATE TABLE IF NOT EXISTS liumai_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL, name TEXT, board TEXT,
                signal_date TEXT NOT NULL,
                bull_count INTEGER, score INTEGER, state TEXT,
                macd INTEGER, kdj INTEGER, rsi INTEGER, lwr INTEGER,
                bbi INTEGER, mtm INTEGER,
                scan_date TEXT NOT NULL,
                UNIQUE(code, scan_date)
            )""")

    def upsert_signals(self, rows):
        if not rows:
            return 0
        with self.conn() as conn:
            for r in rows:
                vals = [r.get(c) for c in _COLS]
                conn.execute(f"""
                    INSERT INTO liumai_signals ({','.join(_COLS)})
                    VALUES ({','.join(['?'] * len(_COLS))})
                    ON CONFLICT(code, scan_date) DO UPDATE SET
                        name=excluded.name, board=excluded.board,
                        signal_date=excluded.signal_date, bull_count=excluded.bull_count,
                        score=excluded.score, state=excluded.state,
                        macd=excluded.macd, kdj=excluded.kdj, rsi=excluded.rsi,
                        lwr=excluded.lwr, bbi=excluded.bbi, mtm=excluded.mtm
                """, vals)
        return len(rows)

    def get_latest_signals(self) -> pd.DataFrame:
        with self.conn() as conn:
            row = conn.execute("SELECT MAX(scan_date) FROM liumai_signals").fetchone()
            latest = row[0] if row else None
            if not latest:
                return pd.DataFrame(columns=_COLS)
            return pd.read_sql_query(
                "SELECT * FROM liumai_signals WHERE scan_date=? "
                "ORDER BY bull_count DESC, score DESC, code", conn, params=(latest,))

    def list_scan_dates(self) -> list:
        with self.conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT scan_date FROM liumai_signals ORDER BY scan_date DESC"
            ).fetchall()
        return [r[0] for r in rows]

    def get_signals_by_scan_date(self, scan_date: str) -> pd.DataFrame:
        with self.conn() as conn:
            return pd.read_sql_query(
                "SELECT * FROM liumai_signals WHERE scan_date=? "
                "ORDER BY bull_count DESC, score DESC, code", conn, params=(scan_date,))

    def clear_scan(self, scan_date: str):
        with self.conn() as conn:
            conn.execute("DELETE FROM liumai_signals WHERE scan_date=?", (scan_date,))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_liumai_signal_db.py -v`
Expected: PASS（5 tests）

- [ ] **Step 5: Commit**

```bash
git add liumai_signal_db.py tests/test_liumai_signal_db.py
git commit -m "feat(liumai): 六脉信号落库 LiumaiSignalDB

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: 六脉批量扫描 `liumai_batch.py`

**Files:**
- Create: `liumai_batch.py`
- Test: `tests/test_liumai_batch.py`

- [ ] **Step 1: Write the failing test** — create `tests/test_liumai_batch.py`:

```python
# tests/test_liumai_batch.py
import os, tempfile
import pandas as pd
import liumai_batch
from liumai_signal_db import LiumaiSignalDB


def _df(closes):
    idx = pd.date_range("2026-01-01", periods=len(closes), freq="D")
    return pd.DataFrame({"Open": closes, "High": [c + 0.5 for c in closes],
                         "Low": [c - 0.5 for c in closes], "Close": closes,
                         "Volume": [1] * len(closes)}, index=idx)


def _db():
    return LiumaiSignalDB(db_path=os.path.join(tempfile.mkdtemp(), "lm.db"))


def test_scan_writes_only_ge5_bull(monkeypatch):
    up = _df([10 + i for i in range(60)])       # 强多 → 多头数 6
    down = _df([100 - i for i in range(60)])    # 偏空 → 多头数低

    def fake_load(code, kind, limit):
        return up if code == "600000" else down

    monkeypatch.setattr(liumai_batch, "_load", fake_load)
    db = _db()
    n = liumai_batch.scan_codes(["600000", "000001"], db, scan_date="2026-05-29",
                                name_board={"600000": ("甲", "深主板"),
                                            "000001": ("乙", "深主板")})
    df = db.get_latest_signals()
    assert n == len(df)
    assert list(df["code"]) == ["600000"]        # 只有强多入库
    assert int(df.iloc[0]["bull_count"]) >= 5


def test_scan_skips_short_or_none(monkeypatch):
    monkeypatch.setattr(liumai_batch, "_load", lambda *a, **k: None)
    db = _db()
    n = liumai_batch.scan_codes(["600000"], db, scan_date="2026-05-29")
    assert n == 0 and db.get_latest_signals().empty
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_liumai_batch.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'liumai_batch'`

- [ ] **Step 3: Write minimal implementation** — create `liumai_batch.py`:

```python
# liumai_batch.py
"""六脉神剑批量扫描: 经 akshare_gw.local 取日线, 算最新多头数, ≥5 者落库。
手动: docker exec agentsstock1 python3 /app/liumai_batch.py"""
import logging
import time
from datetime import datetime

from chanlun_batch import _load                     # 复用本地源加载(标准 OHLCV)
from chanlun_universe import list_universe, board_of
from liumai_engine import latest_snapshot, DIMS
from liumai_signal_db import LiumaiSignalDB

logger = logging.getLogger(__name__)
_MIN_BULL = 5


def scan_codes(codes, db: LiumaiSignalDB, scan_date=None, name_board=None) -> int:
    """扫一批 code, 最新多头数≥5 者写库。返回写入条数。
    name_board: {code: (name, board)}; 缺省 board 用前缀推断、name 留空。"""
    scan_date = scan_date or datetime.now().strftime("%Y-%m-%d")
    name_board = name_board or {}
    rows = []
    for code in codes:
        try:
            df_day = _load(code, "day", 300)
            snap = latest_snapshot(df_day)
            if snap is None or snap["bull_count"] < _MIN_BULL:
                continue
            name, board = name_board.get(code, ("", board_of(code)))
            row = {"code": code, "name": name, "board": board,
                   "signal_date": snap["signal_date"], "bull_count": snap["bull_count"],
                   "score": snap["score"], "state": snap["state"], "scan_date": scan_date}
            for d in DIMS:
                row[d.lower()] = snap[d]
            rows.append(row)
        except Exception as e:
            logger.debug(f"[六脉批量] {code} 跳过: {type(e).__name__}: {str(e)[:80]}")
    db.upsert_signals(rows)
    return len(rows)


def main():
    logging.basicConfig(level=logging.INFO,
                        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s")
    scan_date = datetime.now().strftime("%Y-%m-%d")
    db = LiumaiSignalDB()
    db.clear_scan(scan_date)                          # 同日重跑先清
    universe = list_universe()
    name_board = {c: (n, b) for c, n, b in universe}
    codes = [c for c, _, _ in universe]
    logger.info(f"[六脉批量] 股票池 {len(codes)} 只, 开始扫描 scan_date={scan_date}")
    t0 = time.time()
    n = scan_codes(codes, db, scan_date=scan_date, name_board=name_board)
    logger.info(f"[六脉批量] 完成: 写入 {n} 条(多头数≥5), 耗时 {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_liumai_batch.py -v`
Expected: PASS（2 tests）

- [ ] **Step 5: Commit**

```bash
git add liumai_batch.py tests/test_liumai_batch.py
git commit -m "feat(liumai): 六脉批量扫描 liumai_batch(全池→多头数≥5→落库)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: 六脉查询层 `liumai_selector.py`

**Files:**
- Create: `liumai_selector.py`
- Test: `tests/test_liumai_selector.py`

- [ ] **Step 1: Write the failing test** — create `tests/test_liumai_selector.py`:

```python
# tests/test_liumai_selector.py
import os, tempfile
from liumai_signal_db import LiumaiSignalDB
from liumai_selector import LiumaiSelector, KEEP_COLS


def _seed():
    db = LiumaiSignalDB(db_path=os.path.join(tempfile.mkdtemp(), "lm.db"))
    db.upsert_signals([
        {"code": "600000", "name": "浦发", "board": "深主板", "signal_date": "2026-05-29",
         "bull_count": 6, "score": 100, "state": "强势", "macd": 1, "kdj": 1, "rsi": 1,
         "lwr": 1, "bbi": 1, "mtm": 1, "scan_date": "2026-05-29"},
        {"code": "000001", "name": "平安", "board": "深主板", "signal_date": "2026-05-29",
         "bull_count": 5, "score": 80, "state": "强势", "macd": 1, "kdj": 1, "rsi": 1,
         "lwr": 0, "bbi": 1, "mtm": 1, "scan_date": "2026-05-29"},
    ])
    return db


def test_get_picks_all_sorted():
    ok, df, msg = LiumaiSelector(db=_seed()).get_picks()
    assert ok and len(df) == 2
    assert list(df.columns) == KEEP_COLS
    assert int(df.iloc[0]["bull_count"]) == 6        # 多头数倒序


def test_get_picks_empty():
    db = LiumaiSignalDB(db_path=os.path.join(tempfile.mkdtemp(), "lm.db"))
    ok, df, msg = LiumaiSelector(db=db).get_picks()
    assert ok is False and "暂无" in msg


def test_list_dates():
    assert LiumaiSelector(db=_seed()).list_dates() == ["2026-05-29"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_liumai_selector.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'liumai_selector'`

- [ ] **Step 3: Write minimal implementation** — create `liumai_selector.py`:

```python
# liumai_selector.py
"""六脉神剑选股: 读 liumai_signals.db 最新批次, 返回 (ok, df, msg)。"""
import logging
from typing import Tuple, Optional, List
import pandas as pd
from liumai_signal_db import LiumaiSignalDB

KEEP_COLS = ["code", "name", "board", "signal_date", "bull_count", "score", "state",
             "macd", "kdj", "rsi", "lwr", "bbi", "mtm"]
DISPLAY_NAMES = {"code": "代码", "name": "名称", "board": "板块",
                 "signal_date": "信号日期", "bull_count": "多头数", "score": "得分",
                 "state": "状态", "macd": "MACD", "kdj": "KDJ", "rsi": "RSI",
                 "lwr": "LWR", "bbi": "BBI", "mtm": "MTM"}


class LiumaiSelector:
    def __init__(self, db: Optional[LiumaiSignalDB] = None):
        self.logger = logging.getLogger(__name__)
        self.db = db or LiumaiSignalDB()

    def get_picks(self, min_bull: int = 5, scan_date: Optional[str] = None
                  ) -> Tuple[bool, Optional[pd.DataFrame], str]:
        df = (self.db.get_signals_by_scan_date(scan_date) if scan_date
              else self.db.get_latest_signals())
        if df is None or df.empty:
            return False, None, "暂无六脉神剑信号(批量扫描尚未运行)"
        df = df[df["bull_count"] >= min_bull]
        if df.empty:
            return False, None, f"暂无多头数≥{min_bull}的信号"
        scan_date = df["scan_date"].iloc[0]
        view = df[KEEP_COLS].reset_index(drop=True)
        return True, view, f"扫描批次 {scan_date}, 共 {len(view)} 只(多头数≥{min_bull})"

    def list_dates(self) -> List[str]:
        return self.db.list_scan_dates()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_liumai_selector.py -v`
Expected: PASS（3 tests）

- [ ] **Step 5: Commit**

```bash
git add liumai_selector.py tests/test_liumai_selector.py
git commit -m "feat(liumai): 六脉查询层 LiumaiSelector

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: 六脉页 `liumai_ui.py`

**Files:**
- Create: `liumai_ui.py`
- Test: `tests/test_liumai_combo_ui_smoke.py`（本任务先建该文件并放六脉冒烟；Task 9 追加组合冒烟）

- [ ] **Step 1: Write the failing test** — create `tests/test_liumai_combo_ui_smoke.py`:

```python
# tests/test_liumai_combo_ui_smoke.py
"""六脉/组合页 AppTest 冒烟: 桩掉 selector 与 batch, 验证渲染与 🔄 按钮不抛异常。"""
import pandas as pd
from streamlit.testing.v1 import AppTest


_LIUMAI_SCRIPT = """
import pandas as pd
import liumai_selector, liumai_batch
from liumai_selector import KEEP_COLS

def _fake_get_picks(self, min_bull=5, scan_date=None):
    df = pd.DataFrame([{
        "code": "600000", "name": "浦发", "board": "深主板", "signal_date": "2026-05-29",
        "bull_count": 6, "score": 100, "state": "强势", "macd": 1, "kdj": 1, "rsi": 1,
        "lwr": 1, "bbi": 1, "mtm": 1,
    }], columns=KEEP_COLS)
    return True, df, "扫描批次 2026-05-29, 共 1 只(多头数≥5)"

liumai_selector.LiumaiSelector.get_picks = _fake_get_picks
liumai_batch.scan_codes = lambda *a, **k: 1
from liumai_ui import display_liumai_selector
display_liumai_selector()
"""


def test_liumai_renders():
    at = AppTest.from_string(_LIUMAI_SCRIPT).run()
    assert not at.exception
    assert any("共 1 只" in str(i.value) for i in at.info)
    assert len(at.button) >= 1       # 🔄 重算按钮存在
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_liumai_combo_ui_smoke.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'liumai_ui'`）

- [ ] **Step 3: Write minimal implementation** — create `liumai_ui.py`:

```python
# liumai_ui.py
"""六脉神剑选股页: 只读 liumai_signals.db 最新批次(多头数≥5), 含 🔄 立即重算。"""
import streamlit as st
from liumai_selector import LiumaiSelector, DISPLAY_NAMES


@st.cache_data(ttl=1800, show_spinner=False)
def _cached_picks():
    return LiumaiSelector().get_picks()


def _recompute():
    """同步对全池重算六脉并落当日批次。"""
    from datetime import datetime
    from chanlun_universe import list_universe
    from liumai_signal_db import LiumaiSignalDB
    import liumai_batch
    scan_date = datetime.now().strftime("%Y-%m-%d")
    db = LiumaiSignalDB()
    db.clear_scan(scan_date)
    universe = list_universe()
    name_board = {c: (n, b) for c, n, b in universe}
    codes = [c for c, _, _ in universe]
    return liumai_batch.scan_codes(codes, db, scan_date=scan_date, name_board=name_board)


def display_liumai_selector():
    st.markdown('<div class="ftc-section">🔱 六脉神剑选股</div>', unsafe_allow_html=True)
    st.caption("六维(MACD/KDJ/RSI/LWR/BBI/MTM)多头共振 · 选出最新交易日多头数≥5(5红以上)的股票。"
               "数据源：TDX 本地库。每日收盘后批量预计算，本页只读结果(初筛候选，请人工复核)。")

    if st.button("🔄 立即重算(全池, 较慢)", key="liumai_recompute"):
        try:
            with st.spinner("全池重算六脉中…"):
                n = _recompute()
            _cached_picks.clear()
            st.success(f"重算完成, 入库 {n} 只(多头数≥5)")
            st.rerun()
        except Exception as e:
            st.error(f"重算失败: {type(e).__name__}: {str(e)[:120]}")

    ok, df, msg = _cached_picks()
    st.info(msg)
    if not ok or df is None:
        return
    st.dataframe(df.rename(columns=DISPLAY_NAMES), width='stretch', height=460)
    st.caption("多头数=六维中多头维度个数(0-6)；得分=加权(MACD/BBI/MTM各20, KDJ/RSI各15, LWR10)；"
               "状态: ≥70强势/40-70偏多/20-40震荡/≤20偏空。各维列 1=多头 0=空头。")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_liumai_combo_ui_smoke.py -v`
Expected: PASS（1 test）

- [ ] **Step 5: Commit**

```bash
git add liumai_ui.py tests/test_liumai_combo_ui_smoke.py
git commit -m "feat(liumai): 六脉选股页 liumai_ui(只读表+🔄重算)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: 组合信号库 `combo_signal_db.py`

**Files:**
- Create: `combo_signal_db.py`
- Test: `tests/test_combo_signal_db.py`

- [ ] **Step 1: Write the failing test** — create `tests/test_combo_signal_db.py`:

```python
# tests/test_combo_signal_db.py
import os, tempfile
from combo_signal_db import ComboSignalDB


def _db():
    return ComboSignalDB(db_path=os.path.join(tempfile.mkdtemp(), "cb.db"))


def _row(code="600000", chan_date="2026-05-27", scan="2026-05-29"):
    return {"code": code, "name": "浦发", "board": "深主板",
            "chanlun_type": "1买", "chanlun_date": chan_date, "buy_reason": "背驰",
            "liumai_date": "2026-05-28", "liumai_bull_count": 6, "liumai_score": 100,
            "scan_date": scan}


def test_upsert_and_get_latest():
    db = _db()
    db.upsert_signals([_row(), _row(code="000001")])
    df = db.get_latest_signals()
    assert len(df) == 2


def test_get_latest_only_newest_batch():
    db = _db()
    db.upsert_signals([_row(scan="2026-05-28")])
    db.upsert_signals([_row(code="000001", scan="2026-05-29")])
    df = db.get_latest_signals()
    assert len(df) == 1 and df.iloc[0]["scan_date"] == "2026-05-29"


def test_conflict_updates():
    db = _db()
    db.upsert_signals([_row()])
    r = _row(); r["liumai_bull_count"] = 5
    db.upsert_signals([r])                       # 同 code+chanlun_date+scan_date → 更新
    df = db.get_latest_signals()
    assert len(df) == 1 and int(df.iloc[0]["liumai_bull_count"]) == 5


def test_list_dates_and_clear():
    db = _db()
    db.upsert_signals([_row(scan="2026-05-29")])
    assert db.list_scan_dates() == ["2026-05-29"]
    db.clear_scan("2026-05-29")
    assert db.get_latest_signals().empty
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_combo_signal_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'combo_signal_db'`

- [ ] **Step 3: Write minimal implementation** — create `combo_signal_db.py`:

```python
# combo_signal_db.py
"""缠论×六脉组合信号落库(沿用 BaseDatabase.conn() 风格)。"""
import logging
import pandas as pd
from base_db import BaseDatabase

_COLS = ["code", "name", "board", "chanlun_type", "chanlun_date", "buy_reason",
         "liumai_date", "liumai_bull_count", "liumai_score", "scan_date"]


class ComboSignalDB(BaseDatabase):
    def __init__(self, db_path="combo_signals.db"):
        self.logger = logging.getLogger(__name__)
        super().__init__(db_path)

    def init_tables(self):
        with self.conn() as conn:
            conn.execute("""
            CREATE TABLE IF NOT EXISTS combo_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL, name TEXT, board TEXT,
                chanlun_type TEXT, chanlun_date TEXT, buy_reason TEXT,
                liumai_date TEXT, liumai_bull_count INTEGER, liumai_score INTEGER,
                scan_date TEXT NOT NULL,
                UNIQUE(code, chanlun_date, scan_date)
            )""")

    def upsert_signals(self, rows):
        if not rows:
            return 0
        with self.conn() as conn:
            for r in rows:
                vals = [r.get(c) for c in _COLS]
                conn.execute(f"""
                    INSERT INTO combo_signals ({','.join(_COLS)})
                    VALUES ({','.join(['?'] * len(_COLS))})
                    ON CONFLICT(code, chanlun_date, scan_date) DO UPDATE SET
                        name=excluded.name, board=excluded.board,
                        chanlun_type=excluded.chanlun_type, buy_reason=excluded.buy_reason,
                        liumai_date=excluded.liumai_date,
                        liumai_bull_count=excluded.liumai_bull_count,
                        liumai_score=excluded.liumai_score
                """, vals)
        return len(rows)

    def get_latest_signals(self) -> pd.DataFrame:
        with self.conn() as conn:
            row = conn.execute("SELECT MAX(scan_date) FROM combo_signals").fetchone()
            latest = row[0] if row else None
            if not latest:
                return pd.DataFrame(columns=_COLS)
            return pd.read_sql_query(
                "SELECT * FROM combo_signals WHERE scan_date=? "
                "ORDER BY chanlun_date DESC, code", conn, params=(latest,))

    def list_scan_dates(self) -> list:
        with self.conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT scan_date FROM combo_signals ORDER BY scan_date DESC"
            ).fetchall()
        return [r[0] for r in rows]

    def get_signals_by_scan_date(self, scan_date: str) -> pd.DataFrame:
        with self.conn() as conn:
            return pd.read_sql_query(
                "SELECT * FROM combo_signals WHERE scan_date=? "
                "ORDER BY chanlun_date DESC, code", conn, params=(scan_date,))

    def clear_scan(self, scan_date: str):
        with self.conn() as conn:
            conn.execute("DELETE FROM combo_signals WHERE scan_date=?", (scan_date,))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_combo_signal_db.py -v`
Expected: PASS（4 tests）

- [ ] **Step 5: Commit**

```bash
git add combo_signal_db.py tests/test_combo_signal_db.py
git commit -m "feat(combo): 组合信号落库 ComboSignalDB

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: 组合扫描 `combo_batch.py`

**Files:**
- Create: `combo_batch.py`
- Test: `tests/test_combo_batch.py`

- [ ] **Step 1: Write the failing test** — create `tests/test_combo_batch.py`:

```python
# tests/test_combo_batch.py
import os, tempfile
import pandas as pd
import combo_batch
from combo_signal_db import ComboSignalDB


def _df(closes, start="2026-04-01"):
    idx = pd.date_range(start, periods=len(closes), freq="D")
    return pd.DataFrame({"Open": closes, "High": [c + 0.5 for c in closes],
                         "Low": [c - 0.5 for c in closes], "Close": closes,
                         "Volume": [1] * len(closes)}, index=idx)


class _FakeChanDB:
    def __init__(self, rows):
        self._df = pd.DataFrame(rows)

    def get_latest_signals(self):
        return self._df


def _combo_db():
    return ComboSignalDB(db_path=os.path.join(tempfile.mkdtemp(), "cb.db"))


def test_combo_hit_within_window(monkeypatch):
    # 60 根强多日线; 缠论买点定在某个交易日(在日线索引内), ±3 窗口内必有多头数≥5
    up = _df([10 + i for i in range(60)])
    hit_date = pd.Timestamp(up.index[50]).strftime("%Y-%m-%d")
    chan = _FakeChanDB([{"code": "600000", "name": "甲", "board": "深主板",
                         "signal_type": "1买", "signal_date": hit_date, "buy_reason": "背驰"}])
    monkeypatch.setattr(combo_batch, "_load", lambda *a, **k: up)
    db = _combo_db()
    n = combo_batch.scan(chan, db, scan_date="2026-05-29")
    assert n == 1
    row = db.get_latest_signals().iloc[0]
    assert row["code"] == "600000" and int(row["liumai_bull_count"]) >= 5


def test_combo_no_hit_when_bearish(monkeypatch):
    down = _df([100 - i for i in range(60)])
    d = pd.Timestamp(down.index[50]).strftime("%Y-%m-%d")
    chan = _FakeChanDB([{"code": "600000", "name": "甲", "board": "深主板",
                         "signal_type": "1买", "signal_date": d, "buy_reason": "背驰"}])
    monkeypatch.setattr(combo_batch, "_load", lambda *a, **k: down)
    n = combo_batch.scan(chan, _combo_db(), scan_date="2026-05-29")
    assert n == 0


def test_combo_empty_chanlun_returns_zero(monkeypatch):
    chan = _FakeChanDB([])
    monkeypatch.setattr(combo_batch, "_load", lambda *a, **k: _df([10 + i for i in range(60)]))
    n = combo_batch.scan(chan, _combo_db(), scan_date="2026-05-29")
    assert n == 0


def test_combo_signal_date_not_in_index_skipped(monkeypatch):
    up = _df([10 + i for i in range(60)])
    chan = _FakeChanDB([{"code": "600000", "name": "甲", "board": "深主板",
                         "signal_type": "1买", "signal_date": "1999-01-01", "buy_reason": "背驰"}])
    monkeypatch.setattr(combo_batch, "_load", lambda *a, **k: up)
    n = combo_batch.scan(chan, _combo_db(), scan_date="2026-05-29")
    assert n == 0
```

注：`test_combo_empty_chanlun_returns_zero` 里 `_FakeChanDB([])` 的 `get_latest_signals` 返回空 DataFrame（无 `signal_type` 列）——`scan` 必须在 `df.empty` 时早返回 0，不得触碰列。

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_combo_batch.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'combo_batch'`

- [ ] **Step 3: Write minimal implementation** — create `combo_batch.py`:

```python
# combo_batch.py
"""缠论×六脉组合扫描: 读 chanlun_signals.db 最新买点, 对每个买点检查其信号日
±3 交易日窗口内是否出现六脉多头数≥5, 命中落 combo_signals.db。
须在 chanlun_batch 之后跑。手动: docker exec agentsstock1 python3 /app/combo_batch.py"""
import logging
import time
from datetime import datetime
import pandas as pd

from chanlun_batch import _load                         # 复用本地源加载
from chanlun_signal_db import ChanlunSignalDB
from chanlun_universe import board_of
from liumai_engine import compute_flags, score_of, DIMS
from combo_signal_db import ComboSignalDB

logger = logging.getLogger(__name__)
_WINDOW = 3          # ±3 交易日
_MIN_BULL = 5        # 六脉≥5 红
_BUY = ("1买", "2买", "3买")
_MIN_BARS = 30


def scan(chanlun_db: ChanlunSignalDB, combo_db: ComboSignalDB, scan_date=None) -> int:
    """返回写入条数。chanlun_db 仅读, combo_db 写。"""
    scan_date = scan_date or datetime.now().strftime("%Y-%m-%d")
    chan = chanlun_db.get_latest_signals()
    if chan is None or chan.empty:
        return 0
    buys = chan[chan["signal_type"].isin(_BUY)]
    if buys.empty:
        combo_db.upsert_signals([])
        return 0
    rows = []
    for code, grp in buys.groupby("code"):
        try:
            df_day = _load(code, "day", 300)
            if df_day is None or len(df_day) < _MIN_BARS:
                continue
            flags = compute_flags(df_day)
            bc = flags[DIMS].sum(axis=1).astype(int)
            dates = [pd.Timestamp(x).strftime("%Y-%m-%d") for x in df_day.index]
            date_to_pos = {d: i for i, d in enumerate(dates)}
            for _, r in grp.iterrows():
                sig_date = str(r["signal_date"])
                pos = date_to_pos.get(sig_date)
                if pos is None:
                    continue
                lo, hi = max(0, pos - _WINDOW), min(len(bc) - 1, pos + _WINDOW)
                window = bc.iloc[lo:hi + 1]
                hit = window[window >= _MIN_BULL]
                if hit.empty:
                    continue
                first_label = hit.index[0]
                rows.append({
                    "code": code, "name": r.get("name", "") or "",
                    "board": r.get("board") or board_of(code),
                    "chanlun_type": r["signal_type"], "chanlun_date": sig_date,
                    "buy_reason": r.get("buy_reason", "") or "",
                    "liumai_date": pd.Timestamp(first_label).strftime("%Y-%m-%d"),
                    "liumai_bull_count": int(hit.iloc[0]),
                    "liumai_score": score_of(flags.loc[first_label]),
                    "scan_date": scan_date,
                })
        except Exception as e:
            logger.debug(f"[组合] {code} 跳过: {type(e).__name__}: {str(e)[:80]}")
    combo_db.upsert_signals(rows)
    return len(rows)


def main():
    logging.basicConfig(level=logging.INFO,
                        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s")
    scan_date = datetime.now().strftime("%Y-%m-%d")
    chanlun_db = ChanlunSignalDB()
    combo_db = ComboSignalDB()
    combo_db.clear_scan(scan_date)
    logger.info(f"[组合] 开始扫描 scan_date={scan_date}(读缠论最新买点)")
    t0 = time.time()
    n = scan(chanlun_db, combo_db, scan_date=scan_date)
    logger.info(f"[组合] 完成: 命中 {n} 条(缠论买点±3交易日内六脉≥5红), 耗时 {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_combo_batch.py -v`
Expected: PASS（4 tests）

- [ ] **Step 5: Commit**

```bash
git add combo_batch.py tests/test_combo_batch.py
git commit -m "feat(combo): 组合扫描 combo_batch(缠论买点±3交易日内六脉≥5红)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: 组合查询层 `combo_selector.py`

**Files:**
- Create: `combo_selector.py`
- Test: `tests/test_combo_selector.py`

- [ ] **Step 1: Write the failing test** — create `tests/test_combo_selector.py`:

```python
# tests/test_combo_selector.py
import os, tempfile
from combo_signal_db import ComboSignalDB
from combo_selector import ComboSelector, KEEP_COLS


def _seed():
    db = ComboSignalDB(db_path=os.path.join(tempfile.mkdtemp(), "cb.db"))
    db.upsert_signals([
        {"code": "600000", "name": "浦发", "board": "深主板", "chanlun_type": "1买",
         "chanlun_date": "2026-05-27", "buy_reason": "背驰", "liumai_date": "2026-05-28",
         "liumai_bull_count": 6, "liumai_score": 100, "scan_date": "2026-05-29"},
    ])
    return db


def test_get_picks():
    ok, df, msg = ComboSelector(db=_seed()).get_picks()
    assert ok and len(df) == 1 and list(df.columns) == KEEP_COLS


def test_get_picks_empty():
    db = ComboSignalDB(db_path=os.path.join(tempfile.mkdtemp(), "cb.db"))
    ok, df, msg = ComboSelector(db=db).get_picks()
    assert ok is False and "暂无" in msg


def test_list_dates():
    assert ComboSelector(db=_seed()).list_dates() == ["2026-05-29"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_combo_selector.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'combo_selector'`

- [ ] **Step 3: Write minimal implementation** — create `combo_selector.py`:

```python
# combo_selector.py
"""缠论×六脉组合选股: 读 combo_signals.db 最新批次, 返回 (ok, df, msg)。"""
import logging
from typing import Tuple, Optional, List
import pandas as pd
from combo_signal_db import ComboSignalDB

KEEP_COLS = ["code", "name", "board", "chanlun_type", "chanlun_date", "buy_reason",
             "liumai_date", "liumai_bull_count", "liumai_score"]
DISPLAY_NAMES = {"code": "代码", "name": "名称", "board": "板块",
                 "chanlun_type": "缠论买点", "chanlun_date": "缠论信号日",
                 "buy_reason": "缠论理由", "liumai_date": "六脉达标日",
                 "liumai_bull_count": "六脉多头数", "liumai_score": "六脉得分"}


class ComboSelector:
    def __init__(self, db: Optional[ComboSignalDB] = None):
        self.logger = logging.getLogger(__name__)
        self.db = db or ComboSignalDB()

    def get_picks(self, scan_date: Optional[str] = None
                  ) -> Tuple[bool, Optional[pd.DataFrame], str]:
        df = (self.db.get_signals_by_scan_date(scan_date) if scan_date
              else self.db.get_latest_signals())
        if df is None or df.empty:
            return False, None, "暂无组合信号(批量扫描尚未运行, 或当日无缠论买点±3日内六脉≥5红)"
        scan_date = df["scan_date"].iloc[0]
        view = df[KEEP_COLS].reset_index(drop=True)
        return True, view, f"扫描批次 {scan_date}, 共 {len(view)} 只(缠论买点×六脉≥5红)"

    def list_dates(self) -> List[str]:
        return self.db.list_scan_dates()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_combo_selector.py -v`
Expected: PASS（3 tests）

- [ ] **Step 5: Commit**

```bash
git add combo_selector.py tests/test_combo_selector.py
git commit -m "feat(combo): 组合查询层 ComboSelector

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 9: 组合页 `combo_ui.py`

**Files:**
- Create: `combo_ui.py`
- Test: `tests/test_liumai_combo_ui_smoke.py`（追加组合冒烟）

- [ ] **Step 1: Append the failing test** — 在 `tests/test_liumai_combo_ui_smoke.py` 末尾追加：

```python
_COMBO_SCRIPT = """
import pandas as pd
import combo_selector, combo_batch
from combo_selector import KEEP_COLS

def _fake_get_picks(self, scan_date=None):
    df = pd.DataFrame([{
        "code": "600000", "name": "浦发", "board": "深主板", "chanlun_type": "1买",
        "chanlun_date": "2026-05-27", "buy_reason": "背驰", "liumai_date": "2026-05-28",
        "liumai_bull_count": 6, "liumai_score": 100,
    }], columns=KEEP_COLS)
    return True, df, "扫描批次 2026-05-29, 共 1 只(缠论买点×六脉≥5红)"

combo_selector.ComboSelector.get_picks = _fake_get_picks
combo_batch.scan = lambda *a, **k: 1
from combo_ui import display_combo_selector
display_combo_selector()
"""


def test_combo_renders():
    at = AppTest.from_string(_COMBO_SCRIPT).run()
    assert not at.exception
    assert any("共 1 只" in str(i.value) for i in at.info)
    assert len(at.button) >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_liumai_combo_ui_smoke.py::test_combo_renders -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'combo_ui'`）

- [ ] **Step 3: Write minimal implementation** — create `combo_ui.py`:

```python
# combo_ui.py
"""缠论×六脉组合选股页: 只读 combo_signals.db 最新批次, 含 🔄 立即刷新。"""
import streamlit as st
from combo_selector import ComboSelector, DISPLAY_NAMES


@st.cache_data(ttl=1800, show_spinner=False)
def _cached_picks():
    return ComboSelector().get_picks()


def _recompute():
    """同步重跑组合扫描(读缠论最新买点)并落当日批次。"""
    from datetime import datetime
    from chanlun_signal_db import ChanlunSignalDB
    from combo_signal_db import ComboSignalDB
    import combo_batch
    scan_date = datetime.now().strftime("%Y-%m-%d")
    combo_db = ComboSignalDB()
    combo_db.clear_scan(scan_date)
    return combo_batch.scan(ChanlunSignalDB(), combo_db, scan_date=scan_date)


def display_combo_selector():
    st.markdown('<div class="ftc-section">🔗 缠论×六脉 组合策略</div>', unsafe_allow_html=True)
    st.caption("组合口径：出现缠论买入信号(1/2/3买)、且其信号日 ±3 交易日窗口内出现六脉神剑 5 红以上"
               "(六维多头数≥5)即选中。缠论买点取每日批量库最新批次。每日定时预计算，本页只读。")

    if st.button("🔄 立即刷新(读当日缠论买点重算)", key="combo_recompute"):
        try:
            with st.spinner("重算组合信号中…"):
                n = _recompute()
            _cached_picks.clear()
            st.success(f"刷新完成, 命中 {n} 只")
            st.rerun()
        except Exception as e:
            st.error(f"刷新失败: {type(e).__name__}: {str(e)[:120]}")

    ok, df, msg = _cached_picks()
    st.info(msg)
    if not ok or df is None:
        return
    st.dataframe(df.rename(columns=DISPLAY_NAMES), width='stretch', height=460)
    st.caption("缠论买点=最新批次内该股买入信号；六脉达标日=缠论信号日±3交易日窗口内首个六脉多头数≥5的交易日。"
               "初筛候选，请人工复核。")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_liumai_combo_ui_smoke.py -v`
Expected: PASS（2 tests：六脉 + 组合）

- [ ] **Step 5: Commit**

```bash
git add combo_ui.py tests/test_liumai_combo_ui_smoke.py
git commit -m "feat(combo): 组合策略页 combo_ui(只读表+🔄刷新)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 10: 导航重构与路由 `app.py`

**Files:**
- Modify: `app.py`（选股板块 expander 内分组 + 两个 show_* 路由）

- [ ] **Step 1: 在选股板块 expander 顶部加「单策略选股」小标题**

定位 `app.py:97` 的 `st.markdown("**根据不同策略筛选优质股票**")`，在其下一行插入：

```python
            st.markdown("**单策略选股**")
```

- [ ] **Step 2: 在缠论选股按钮(app.py:134-141)之后、expander 内追加 六脉神剑按钮 + 组合策略小标题 + 组合按钮**

在 `app.py` 缠论按钮的 `for key in [...]: del...` 块结束之后（仍在 `with st.expander("🎯 选股板块"...)` 缩进内，约 142 行处）插入：

```python
            if st.button("🔱 六脉神剑", width='stretch', key="nav_liumai", help="六维(MACD/KDJ/RSI/LWR/BBI/MTM)多头共振，选最新多头数≥5(5红以上)"):
                st.session_state.show_liumai = True
                for key in ['show_history', 'show_monitor', 'show_config', 'show_main_force',
                           'show_sector_strategy', 'show_longhubang', 'show_portfolio', 'show_low_price_bull',
                           'show_small_cap', 'show_profit_growth', 'show_value_stock', 'show_news_flow',
                           'show_macro_analysis', 'show_macro_cycle', 'show_smart_monitor', 'show_intraday',
                           'show_chanlun', 'show_combo']:
                    if key in st.session_state:
                        del st.session_state[key]

            st.markdown("**组合策略选股**")

            if st.button("🔗 缠论×六脉", width='stretch', key="nav_combo", help="缠论买点±3交易日内六脉神剑5红以上"):
                st.session_state.show_combo = True
                for key in ['show_history', 'show_monitor', 'show_config', 'show_main_force',
                           'show_sector_strategy', 'show_longhubang', 'show_portfolio', 'show_low_price_bull',
                           'show_small_cap', 'show_profit_growth', 'show_value_stock', 'show_news_flow',
                           'show_macro_analysis', 'show_macro_cycle', 'show_smart_monitor', 'show_intraday',
                           'show_chanlun', 'show_liumai']:
                    if key in st.session_state:
                        del st.session_state[key]
```

注意缩进须与同 expander 内其他 `if st.button(...)` 一致（12 空格）。

- [ ] **Step 3: 在缠论按钮把 show_liumai/show_combo 纳入其清理集**

定位 `app.py:135-141` 缠论按钮的 `for key in [...]` 列表，在其末尾(`'show_intraday'` 之后)追加 `, 'show_liumai', 'show_combo'`，使切到缠论时也清掉这两个标志。

- [ ] **Step 4: 在页面路由区(缠论分支 app.py:382-384 之后)加两个独立 if 块**

定位：

```python
    if 'show_chanlun' in st.session_state and st.session_state.show_chanlun:
        from chanlun_ui import display_chanlun_selector
        display_chanlun_selector()
```

在其后插入（顶层缩进 4 空格，与该 if 同级）：

```python
    if 'show_liumai' in st.session_state and st.session_state.show_liumai:
        from liumai_ui import display_liumai_selector
        display_liumai_selector()

    if 'show_combo' in st.session_state and st.session_state.show_combo:
        from combo_ui import display_combo_selector
        display_combo_selector()
```

- [ ] **Step 5: 语法与导入冒烟校验**

Run: `python3 -c "import ast; ast.parse(open('app.py').read()); print('app.py OK')"`
Expected: `app.py OK`

Run: `python3 -c "import liumai_ui, combo_ui, liumai_selector, combo_selector; print('imports OK')"`
Expected: `imports OK`

- [ ] **Step 6: 全量缠论/六脉/组合测试回归**

Run: `python3 -m pytest tests/test_liumai_engine.py tests/test_liumai_signal_db.py tests/test_liumai_batch.py tests/test_liumai_selector.py tests/test_combo_signal_db.py tests/test_combo_batch.py tests/test_combo_selector.py tests/test_liumai_combo_ui_smoke.py tests/test_chanlun_selector.py tests/test_chanlun_signal_db.py -q`
Expected: 全部 PASS（约 30+ passed），确认未破坏缠论既有链路。

- [ ] **Step 7: Commit**

```bash
git add app.py
git commit -m "feat(nav): 选股板块分单策略/组合策略, 接入六脉与缠论×六脉页

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## 调度说明（不在本仓库代码内，文档备查）

沿用缠论 chanlun-updater 日调度，每日收盘后**按序**追加执行：

```
docker exec agentsstock1 python3 /app/chanlun_batch.py
docker exec agentsstock1 python3 /app/liumai_batch.py
docker exec agentsstock1 python3 /app/combo_batch.py   # 须在 chanlun_batch 之后
```

前台六脉页 / 组合页的 🔄 按钮做即时同步重算当前批次。

---

## Self-Review Notes

- **Spec coverage**：①六脉引擎→Task1；②六脉 db/batch/selector/ui→Task2-5；③组合 db/batch/selector/ui→Task6-9；④导航重构+路由→Task10；⑤调度顺序→末节文档+各 batch 的 main()；⑥错误处理→batch 内 try 跳过、selector 空库提示、UI 重算 try/except；⑦测试策略→各任务 TDD + AppTest 冒烟。
- **Placeholder scan**：无 TBD/TODO；唯一"调参"提示在 Task1 Step4（测试夹具数值，非实现占位）。
- **Type consistency**：`latest_snapshot`/`compute_flags`/`bull_count_series`/`score_of`/`DIMS` 在 Task1 定义，Task3/Task7 引用一致；`scan_codes`(六脉,Task3) vs `scan`(组合,Task7) 命名区分明确；各 DB 的 `_COLS`/`get_latest_signals`/`list_scan_dates`/`clear_scan` 接口一致；selector `get_picks`/`KEEP_COLS`/`DISPLAY_NAMES` 两组同构；UI `_cached_picks.clear()` 与缓存定义匹配。
```
