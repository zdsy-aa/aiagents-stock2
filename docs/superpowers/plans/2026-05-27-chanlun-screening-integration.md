# 缠论选股集成 实现计划（计划② / 共②）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **前置依赖：计划①缠论引擎（`chanlun_engine.py`，含 `analyze(df_day, df_30m)` 与 `buy_point_with_exit`）必须已完成并测试通过。**

**Goal:** 在缠论引擎之上做选股：股票池过滤 → 每日批量扫全市场本地数据算买点落库 → 选股页只读库展示（含买点/止损/缠论卖点离场条件）→ 调度串在 kline 更新之后。

**Architecture:** `chanlun_universe.py`(股票池过滤,纯函数) + `chanlun_signal_db.py`(`BaseDatabase` 落库 `data/chanlun_signals.db`) + `chanlun_batch.py`(批量扫描入口,经 `akshare_gw.local` 只读 TDX 本地库) + `chanlun_selector.py`(读库返回三元组) + `chanlun_ui.py`(选股页,套现有 `*_ui` 模式) + `app.py`(侧栏按钮+路由) + 新 compose 服务 `chanlun-scanner`(复用 app 镜像,每日 18:30 跑批量)。

**Tech Stack:** Python 3.12、pandas、sqlite3(经 BaseDatabase)、Streamlit `AppTest`、Docker Compose；测试在容器 `agentsstock1` 内跑。

---

## 执行约定（重要）

- 测试在容器 `agentsstock1` 内：`docker exec agentsstock1 sh -c "cd /app && python3 -m pytest <file> -v"`；pytest 非烤入需先 `docker exec agentsstock1 python3 -m pip install -q pytest`。改完源文件先 `docker cp` 进 `/app` 再测。
- 本地数据访问**只用** `akshare_gw.local`（`LocalDBClient`，只读 `/app/tdx-data/database/kline/<code>.db`，无网络）：`akshare_gw.local.get_kline(symbol, kline_type='day'|'30min', limit=...)` 返回中文列 DataFrame（`日期/开盘/收盘/最高/最低/成交量/成交额`，价格已 /1000、时间已转北京日期）。`akshare_gw.local.base_dir` 为 kline 目录、`akshare_gw.local.available` 为可用标志。
- 股票名 / ST 判定用 `tdx-api/web/data/database/codes.db`（表 `codes`，列含 `Code`/`Name`）。
- signals 库经 `BaseDatabase`，裸文件名自动落到 `DATA_DIR`（默认 `data/` → 容器 `/app/data`，bind-mount 持久化）。
- commit 在宿主仓库；message 结尾加 `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`。
- 沿用项目 `*_selector.py` 返回 `(success: bool, df: DataFrame|None, message: str)` 约定；选股页套 `display_X()` → 按钮触发 selector → `st.session_state` 缓存 → 表格展示。

## 文件结构

| 文件 | 职责 |
|------|------|
| `chanlun_universe.py`（新） | `is_eligible(code, name) -> bool`、`list_universe() -> List[(code,name,board)]`：排除科创/北交/ST，标注板块 |
| `chanlun_signal_db.py`（新） | `ChanlunSignalDB(BaseDatabase)`：建表 + `upsert_signals/get_latest_signals/clear_scan` |
| `chanlun_batch.py`（新） | `scan(codes=None, scan_date=None) -> int`：枚举股票池→读本地日线+30分→引擎→近7交易日买点→落库；`__main__` 跑全市场 |
| `chanlun_selector.py`（新） | `get_chanlun_picks(types=None) -> (ok, df, msg)`：读库最新批次 |
| `chanlun_ui.py`（新） | `display_chanlun_selector()`：列表+买点/止损/离场条件 |
| `app.py`（改） | 侧栏「🌀 缠论选股」按钮 + `show_chanlun` 路由 |
| `chanlun_scan_loop.sh`（新） | 每日 18:30 跑 `python3 chanlun_batch.py` 的轮询脚本 |
| `docker-compose.yml`（改） | 新增 `chanlun-scanner` 服务（复用 app 镜像 + 上述 loop） |

---

### Task 1: 股票池过滤 `chanlun_universe.py`

**Files:**
- Create: `chanlun_universe.py`
- Test: `tests/test_chanlun_universe.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_chanlun_universe.py
from chanlun_universe import is_eligible, board_of


def test_board_of_prefixes():
    assert board_of("600000") == "沪主板"
    assert board_of("000001") == "深主板"
    assert board_of("002594") == "中小板"
    assert board_of("300750") == "创业板"
    assert board_of("688981") == "科创板"
    assert board_of("830799") == "北交所"
    assert board_of("920819") == "北交所"


def test_is_eligible_excludes_kechuang_beijiao_st():
    assert is_eligible("600000", "浦发银行") is True
    assert is_eligible("300750", "宁德时代") is True
    assert is_eligible("688981", "中芯国际") is False   # 科创排除
    assert is_eligible("830799", "艾融软件") is False   # 北交排除
    assert is_eligible("000001", "ST平安") is False      # ST 排除
    assert is_eligible("000001", "*ST深发") is False     # *ST 排除
```

- [ ] **Step 2: 跑测试确认失败**

Run: `docker cp tests/test_chanlun_universe.py agentsstock1:/app/tests/ && docker exec agentsstock1 sh -c "cd /app && python3 -m pytest tests/test_chanlun_universe.py -v"`
Expected: FAIL — `ModuleNotFoundError: No module named 'chanlun_universe'`

- [ ] **Step 3: 实现**

```python
# chanlun_universe.py
"""缠论选股股票池：排除科创板/北交所/ST，标注板块。仅依赖本地 codes.db。"""
import os
import sqlite3
import glob
from typing import List, Tuple, Optional

CODES_DB = os.getenv("CODES_DB", "/app/tdx-api/web/data/database/codes.db")


def board_of(code: str) -> str:
    if code.startswith(("688", "689")):
        return "科创板"
    if code.startswith(("8", "4", "920")):
        return "北交所"
    if code.startswith(("300", "301")):
        return "创业板"
    if code.startswith("002"):
        return "中小板"
    if code.startswith(("000", "001", "003")):
        return "深主板"
    if code.startswith(("600", "601", "603", "605")):
        return "沪主板"
    return "其他"


def is_eligible(code: str, name: Optional[str]) -> bool:
    """排除科创/北交/ST/*ST；其余沪深主板/中小/创业保留。"""
    if board_of(code) in ("科创板", "北交所", "其他"):
        return False
    if name and "ST" in name.upper():
        return False
    return True


def _name_map() -> dict:
    """从 codes.db 取 code->name；失败返回空 dict（名字仅用于 ST 判定）。"""
    m = {}
    if not os.path.exists(CODES_DB):
        return m
    try:
        conn = sqlite3.connect(f"file:{CODES_DB}?mode=ro", uri=True)
        try:
            for code, name in conn.execute("SELECT Code, Name FROM codes"):
                m[str(code)] = name
        finally:
            conn.close()
    except Exception:
        pass
    return m


def list_universe(kline_dir: Optional[str] = None) -> List[Tuple[str, str, str]]:
    """枚举本地 kline 库中合格股票，返回 [(code, name, board)]。"""
    from akshare_gateway import akshare_gw
    kline_dir = kline_dir or akshare_gw.local.base_dir
    names = _name_map()
    out: List[Tuple[str, str, str]] = []
    for path in glob.glob(os.path.join(kline_dir, "*.db")):
        code = os.path.splitext(os.path.basename(path))[0]
        name = names.get(code, "")
        if is_eligible(code, name):
            out.append((code, name, board_of(code)))
    return sorted(out)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `docker cp chanlun_universe.py agentsstock1:/app/ && docker exec agentsstock1 sh -c "cd /app && python3 -m pytest tests/test_chanlun_universe.py -v"`
Expected: PASS（2 passed）

- [ ] **Step 5: Commit**

```bash
git add chanlun_universe.py tests/test_chanlun_universe.py
git commit -m "feat(chanlun): 股票池过滤 chanlun_universe（排除科创/北交/ST）

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 2: 信号落库 `chanlun_signal_db.py`

**Files:**
- Create: `chanlun_signal_db.py`
- Test: `tests/test_chanlun_signal_db.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_chanlun_signal_db.py
import os, tempfile
from chanlun_signal_db import ChanlunSignalDB


def _db():
    d = tempfile.mkdtemp()
    return ChanlunSignalDB(db_path=os.path.join(d, "chanlun_signals.db"))


def test_upsert_and_get_latest():
    db = _db()
    rows = [
        {"code": "600000", "name": "浦发银行", "board": "沪主板", "signal_type": "1买",
         "signal_date": "2026-05-26", "buy_price": 10.0, "stop_loss": 9.8,
         "exit_rule": "出现一卖离场", "level": "日线", "scan_date": "2026-05-27"},
        {"code": "300750", "name": "宁德时代", "board": "创业板", "signal_type": "2买",
         "signal_date": "2026-05-27", "buy_price": 200.0, "stop_loss": 196.0,
         "exit_rule": "出现一卖离场", "level": "日线", "scan_date": "2026-05-27"},
    ]
    db.upsert_signals(rows)
    df = db.get_latest_signals()
    assert len(df) == 2
    assert set(df["signal_type"]) == {"1买", "2买"}


def test_upsert_idempotent_on_unique_key():
    db = _db()
    row = {"code": "600000", "name": "浦发", "board": "沪主板", "signal_type": "1买",
           "signal_date": "2026-05-26", "buy_price": 10.0, "stop_loss": 9.8,
           "exit_rule": "x", "level": "日线", "scan_date": "2026-05-27"}
    db.upsert_signals([row, dict(row, buy_price=11.0)])  # 同 code+type+date
    df = db.get_latest_signals()
    assert len(df) == 1
    assert df.iloc[0]["buy_price"] == 11.0   # 后者覆盖


def test_clear_scan():
    db = _db()
    db.upsert_signals([{"code": "600000", "name": "x", "board": "沪主板", "signal_type": "1买",
                        "signal_date": "2026-05-26", "buy_price": 10.0, "stop_loss": 9.8,
                        "exit_rule": "x", "level": "日线", "scan_date": "2026-05-27"}])
    db.clear_scan("2026-05-27")
    assert len(db.get_latest_signals()) == 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `docker cp tests/test_chanlun_signal_db.py agentsstock1:/app/tests/ && docker exec agentsstock1 sh -c "cd /app && python3 -m pytest tests/test_chanlun_signal_db.py -v"`
Expected: FAIL — `ModuleNotFoundError: No module named 'chanlun_signal_db'`

- [ ] **Step 3: 实现**

```python
# chanlun_signal_db.py
"""缠论选股信号落库（沿用 BaseDatabase.conn() 风格）。"""
import logging
import pandas as pd
from base_db import BaseDatabase

_COLS = ["code", "name", "board", "signal_type", "signal_date",
         "buy_price", "stop_loss", "exit_rule", "level", "scan_date"]


class ChanlunSignalDB(BaseDatabase):
    def __init__(self, db_path="chanlun_signals.db"):
        self.logger = logging.getLogger(__name__)
        super().__init__(db_path)

    def init_tables(self):
        with self.conn() as conn:
            conn.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL,
                name TEXT,
                board TEXT,
                signal_type TEXT NOT NULL,
                signal_date TEXT NOT NULL,
                buy_price REAL,
                stop_loss REAL,
                exit_rule TEXT,
                level TEXT,
                scan_date TEXT NOT NULL,
                UNIQUE(code, signal_type, signal_date)
            )""")

    def upsert_signals(self, rows):
        if not rows:
            return 0
        with self.conn() as conn:
            for r in rows:
                vals = [r.get(c) for c in _COLS]
                conn.execute(f"""
                    INSERT INTO signals ({','.join(_COLS)})
                    VALUES ({','.join(['?'] * len(_COLS))})
                    ON CONFLICT(code, signal_type, signal_date) DO UPDATE SET
                        name=excluded.name, board=excluded.board,
                        buy_price=excluded.buy_price, stop_loss=excluded.stop_loss,
                        exit_rule=excluded.exit_rule, level=excluded.level,
                        scan_date=excluded.scan_date
                """, vals)
        return len(rows)

    def get_latest_signals(self) -> pd.DataFrame:
        """返回最新批次(scan_date 最大)的全部信号。"""
        with self.conn() as conn:
            row = conn.execute("SELECT MAX(scan_date) FROM signals").fetchone()
            latest = row[0] if row else None
            if not latest:
                return pd.DataFrame(columns=_COLS)
            return pd.read_sql_query(
                "SELECT * FROM signals WHERE scan_date=? ORDER BY signal_date DESC, code",
                conn, params=(latest,))

    def clear_scan(self, scan_date: str):
        with self.conn() as conn:
            conn.execute("DELETE FROM signals WHERE scan_date=?", (scan_date,))
```

- [ ] **Step 4: 跑测试确认通过**

Run: `docker cp chanlun_signal_db.py agentsstock1:/app/ && docker exec agentsstock1 sh -c "cd /app && python3 -m pytest tests/test_chanlun_signal_db.py -v"`
Expected: PASS（3 passed）

- [ ] **Step 5: Commit**

```bash
git add chanlun_signal_db.py tests/test_chanlun_signal_db.py
git commit -m "feat(chanlun): 信号落库 ChanlunSignalDB（upsert/get_latest/clear_scan）

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 3: 批量扫描 `chanlun_batch.py`

**Files:**
- Create: `chanlun_batch.py`
- Test: `tests/test_chanlun_batch.py`

- [ ] **Step 1: 写失败测试**（在容器内用真实本地数据跑 3 只票，端到端验证落库）

```python
# tests/test_chanlun_batch.py
import os, tempfile
import pytest
from chanlun_batch import scan_codes
from chanlun_signal_db import ChanlunSignalDB


@pytest.mark.skipif(not os.path.exists("/app/tdx-data/database/kline/000001.db"),
                    reason="需容器内本地K线库")
def test_scan_codes_writes_db_without_error():
    db = ChanlunSignalDB(db_path=os.path.join(tempfile.mkdtemp(), "s.db"))
    # 跑 3 只主板票；不强求一定有买点，只验证流程不报错、落库可读
    n = scan_codes(["000001", "600000", "600519"], db, scan_date="2026-05-27", days=7)
    assert isinstance(n, int) and n >= 0
    df = db.get_latest_signals()
    # 若有信号，字段完整
    for _, r in df.iterrows():
        assert r["signal_type"] in ("1买", "2买", "3买")
        assert r["stop_loss"] <= r["buy_price"]
        assert isinstance(r["exit_rule"], str) and len(r["exit_rule"]) > 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `docker cp tests/test_chanlun_batch.py agentsstock1:/app/tests/ && docker exec agentsstock1 sh -c "cd /app && python3 -m pytest tests/test_chanlun_batch.py -v"`
Expected: FAIL — `ModuleNotFoundError: No module named 'chanlun_batch'`

- [ ] **Step 3: 实现**

```python
# chanlun_batch.py
"""缠论选股批量扫描：经 akshare_gw.local 只读 TDX 本地库，算近7交易日买点落库。
手动：docker exec agentsstock1 python3 /app/chanlun_batch.py"""
import logging
import time
from datetime import datetime
import pandas as pd

from chanlun_engine import analyze, buy_point_with_exit
from chanlun_universe import list_universe, board_of
from chanlun_signal_db import ChanlunSignalDB

logger = logging.getLogger(__name__)

_RENAME = {"开盘": "Open", "最高": "High", "最低": "Low", "收盘": "Close", "成交量": "Volume"}


def _load(symbol: str, kind: str, limit: int):
    """经本地源取标准 OHLCV（索引=日期）；无数据返回 None。"""
    from akshare_gateway import akshare_gw
    df = akshare_gw.local.get_kline(symbol, kline_type=kind, limit=limit)
    if df is None or df.empty:
        return None
    df = df.rename(columns=_RENAME).set_index("日期").sort_index()
    return df[["Open", "High", "Low", "Close", "Volume"]]


def scan_codes(codes, db: ChanlunSignalDB, scan_date=None, days=7, name_board=None) -> int:
    """扫一批 code，把近 days 交易日内的买点写库。返回写入条数。
    name_board: {code: (name, board)}；缺省 board 用前缀推断、name 留空。"""
    scan_date = scan_date or datetime.now().strftime("%Y-%m-%d")
    name_board = name_board or {}
    rows = []
    for code in codes:
        try:
            df_day = _load(code, "day", 500)
            if df_day is None or len(df_day) < 60:
                continue
            df_30m = _load(code, "30min", 2000)
            res = analyze(df_day, df_30m)
            if not res.points:
                continue
            # 近 days 交易日的日期集合
            recent_dates = set(df_day.index[-days:])
            day_index = list(df_day.index)
            name, board = name_board.get(code, ("", board_of(code)))
            for p in res.points:
                if p.kind not in ("1买", "2买", "3买"):
                    continue
                if p.i < 0 or p.i >= len(day_index):
                    continue
                sig_dt = day_index[p.i]
                if sig_dt not in recent_dates:
                    continue
                info = buy_point_with_exit(p, res.pivots)
                rows.append({
                    "code": code, "name": name, "board": board,
                    "signal_type": info["signal_type"],
                    "signal_date": pd.Timestamp(sig_dt).strftime("%Y-%m-%d"),
                    "buy_price": info["buy_price"], "stop_loss": info["stop_loss"],
                    "exit_rule": info["exit_rule"], "level": "日线", "scan_date": scan_date,
                })
        except Exception as e:
            logger.debug(f"[缠论批量] {code} 跳过: {type(e).__name__}: {str(e)[:80]}")
    db.upsert_signals(rows)
    return len(rows)


def main():
    logging.basicConfig(level=logging.INFO,
                        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s")
    scan_date = datetime.now().strftime("%Y-%m-%d")
    db = ChanlunSignalDB()
    db.clear_scan(scan_date)  # 同日重跑先清
    universe = list_universe()
    name_board = {c: (n, b) for c, n, b in universe}
    codes = [c for c, _, _ in universe]
    logger.info(f"[缠论批量] 股票池 {len(codes)} 只，开始扫描 scan_date={scan_date}")
    t0 = time.time()
    n = scan_codes(codes, db, scan_date=scan_date, name_board=name_board)
    logger.info(f"[缠论批量] 完成：写入 {n} 条买点信号，耗时 {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `docker cp chanlun_batch.py agentsstock1:/app/ && docker exec agentsstock1 sh -c "cd /app && python3 -m pytest tests/test_chanlun_batch.py -v"`
Expected: PASS（1 passed）

- [ ] **Step 5: Commit**

```bash
git add chanlun_batch.py tests/test_chanlun_batch.py
git commit -m "feat(chanlun): 批量扫描 chanlun_batch（本地源只读+近7交易日买点落库）

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 4: 选股 `chanlun_selector.py`

**Files:**
- Create: `chanlun_selector.py`
- Test: `tests/test_chanlun_selector.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_chanlun_selector.py
import os, tempfile
from chanlun_signal_db import ChanlunSignalDB
from chanlun_selector import ChanlunSelector


def _seed():
    db = ChanlunSignalDB(db_path=os.path.join(tempfile.mkdtemp(), "s.db"))
    db.upsert_signals([
        {"code": "600000", "name": "浦发", "board": "沪主板", "signal_type": "1买",
         "signal_date": "2026-05-26", "buy_price": 10.0, "stop_loss": 9.8,
         "exit_rule": "x", "level": "日线", "scan_date": "2026-05-27"},
        {"code": "300750", "name": "宁德", "board": "创业板", "signal_type": "3买",
         "signal_date": "2026-05-27", "buy_price": 200.0, "stop_loss": 196.0,
         "exit_rule": "x", "level": "日线", "scan_date": "2026-05-27"},
    ])
    return db


def test_get_picks_all():
    ok, df, msg = ChanlunSelector(db=_seed()).get_chanlun_picks()
    assert ok and len(df) == 2


def test_get_picks_filter_type():
    ok, df, msg = ChanlunSelector(db=_seed()).get_chanlun_picks(types=["3买"])
    assert ok and len(df) == 1 and df.iloc[0]["signal_type"] == "3买"


def test_get_picks_empty():
    db = ChanlunSignalDB(db_path=os.path.join(tempfile.mkdtemp(), "s.db"))
    ok, df, msg = ChanlunSelector(db=db).get_chanlun_picks()
    assert ok is False and "暂无" in msg
```

- [ ] **Step 2: 跑测试确认失败**

Run: `docker cp tests/test_chanlun_selector.py agentsstock1:/app/tests/ && docker exec agentsstock1 sh -c "cd /app && python3 -m pytest tests/test_chanlun_selector.py -v"`
Expected: FAIL — `ModuleNotFoundError: No module named 'chanlun_selector'`

- [ ] **Step 3: 实现**

```python
# chanlun_selector.py
"""缠论选股：读 chanlun_signals.db 最新批次，返回 (ok, df, msg)（对齐其它 *_selector）。"""
import logging
from typing import Tuple, Optional, List
import pandas as pd
from chanlun_signal_db import ChanlunSignalDB

_DISPLAY = {"code": "代码", "name": "名称", "board": "板块", "signal_type": "买点",
            "signal_date": "信号日期", "buy_price": "买入参考价", "stop_loss": "止损位",
            "exit_rule": "离场条件"}


class ChanlunSelector:
    def __init__(self, db: Optional[ChanlunSignalDB] = None):
        self.logger = logging.getLogger(__name__)
        self.db = db or ChanlunSignalDB()

    def get_chanlun_picks(self, types: Optional[List[str]] = None
                          ) -> Tuple[bool, Optional[pd.DataFrame], str]:
        df = self.db.get_latest_signals()
        if df is None or df.empty:
            return False, None, "暂无缠论买点信号（批量扫描尚未运行或近7交易日无信号）"
        if types:
            df = df[df["signal_type"].isin(types)]
        if df.empty:
            return False, None, "所选买点类型暂无信号"
        scan_date = df["scan_date"].iloc[0]
        view = df[list(_DISPLAY)].rename(columns=_DISPLAY).reset_index(drop=True)
        return True, view, f"扫描批次 {scan_date}，共 {len(view)} 只"
```

- [ ] **Step 4: 跑测试确认通过**

Run: `docker cp chanlun_selector.py agentsstock1:/app/ && docker exec agentsstock1 sh -c "cd /app && python3 -m pytest tests/test_chanlun_selector.py -v"`
Expected: PASS（3 passed）

- [ ] **Step 5: Commit**

```bash
git add chanlun_selector.py tests/test_chanlun_selector.py
git commit -m "feat(chanlun): 选股读库 ChanlunSelector

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 5: 选股页 `chanlun_ui.py` + app.py 接线

**Files:**
- Create: `chanlun_ui.py`
- Modify: `app.py`（侧栏「选股板块」expander 内加按钮；main() 路由段加 `show_chanlun` 分支）
- Test: `tests/test_chanlun_ui_smoke.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_chanlun_ui_smoke.py
from streamlit.testing.v1 import AppTest


def test_chanlun_page_renders_without_exception():
    at = AppTest.from_file("app.py", default_timeout=120)
    at.session_state["show_chanlun"] = True
    at.run()
    assert not at.exception, at.exception
```

- [ ] **Step 2: 跑测试确认失败**

Run: `docker cp tests/test_chanlun_ui_smoke.py agentsstock1:/app/tests/ && docker exec agentsstock1 sh -c "cd /app && python3 -m pytest tests/test_chanlun_ui_smoke.py -v"`
Expected: FAIL — 页面无 `show_chanlun` 路由 / `chanlun_ui` 不存在（断言 `at.exception` 或 ImportError）

- [ ] **Step 3: 实现 chanlun_ui.py**

```python
# chanlun_ui.py
"""缠论选股页：只读 chanlun_signals.db 最新批次，展示买点/止损/离场条件。"""
import streamlit as st
from chanlun_selector import ChanlunSelector

_TYPES = ["1买", "2买", "3买"]


def display_chanlun_selector():
    st.markdown('<div class="ftc-section">🌀 缠论选股</div>', unsafe_allow_html=True)
    st.caption("严格多级别缠论（日线本级别 + 30分钟次级别确认）·"
               " 选出最近 7 个交易日出现一买/二买/三买的股票。数据源：TDX 本地库。"
               " 信号每日收盘后批量预计算，本页只读结果（初筛候选，请人工复核）。")

    picked = st.multiselect("买点类型", _TYPES, default=_TYPES)
    ok, df, msg = ChanlunSelector().get_chanlun_picks(types=picked)
    st.info(msg)
    if not ok or df is None:
        return
    st.dataframe(df, width='stretch', height=460)
    st.caption("止损=买点下方关键位；离场条件=出现对应缠论卖点(一卖/二卖/三卖)或跌破止损。")
```

- [ ] **Step 4: 接线 app.py**

1. 在「选股板块」expander 内（紧接 `nav_value_stock` 那个 `st.button` 块之后，仍在该 expander 缩进内）加按钮：

```python
            if st.button("🌀 缠论选股", width='stretch', key="nav_chanlun", help="严格多级别缠论 一/二/三买 选股"):
                st.session_state.show_chanlun = True
                for key in ['show_history', 'show_monitor', 'show_config', 'show_sector_strategy',
                           'show_longhubang', 'show_portfolio', 'show_main_force', 'show_low_price_bull',
                           'show_small_cap', 'show_profit_growth', 'show_value_stock', 'show_news_flow',
                           'show_macro_cycle', 'show_macro_analysis']:
                    if key in st.session_state:
                        del st.session_state[key]
```

2. 在 main() 路由段（紧接 `show_value_stock` 分支之后）加：

```python
    if 'show_chanlun' in st.session_state and st.session_state.show_chanlun:
        from chanlun_ui import display_chanlun_selector
        display_chanlun_selector()
        return
```

3. 把 `'show_chanlun'` 补进首页「🏠 股票分析-日」按钮清空其它标志的那个 key 列表（约 app.py 77-78 行附近），保证切回首页时能清掉缠论页标志。

- [ ] **Step 5: 跑测试确认通过**

Run: `docker cp chanlun_ui.py agentsstock1:/app/ && docker cp app.py agentsstock1:/app/ && docker exec agentsstock1 sh -c "cd /app && python3 -m pytest tests/test_chanlun_ui_smoke.py -v"`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add chanlun_ui.py app.py tests/test_chanlun_ui_smoke.py
git commit -m "feat(chanlun): 缠论选股页 + app.py 侧栏按钮与路由

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 6: 调度服务 `chanlun-scanner` + 首次落库 + 部署

**Files:**
- Create: `chanlun_scan_loop.sh`
- Modify: `docker-compose.yml`

- [ ] **Step 1: 写轮询脚本**

```sh
# chanlun_scan_loop.sh —— 每日 18:30 跑一次缠论批量；睡到目标时刻再执行（无需 cron）
#!/bin/sh
set -u
RUN_HOUR=18
RUN_MIN=30
echo "[chanlun-scanner] started; daily run at ${RUN_HOUR}:${RUN_MIN}"
while true; do
    now_h=$(date +%H); now_m=$(date +%M)
    if [ "$now_h" = "$RUN_HOUR" ] && [ "$now_m" = "$(printf '%02d' $RUN_MIN)" ]; then
        echo "[chanlun-scanner] $(date '+%F %T') 开始批量"
        python3 /app/chanlun_batch.py
        echo "[chanlun-scanner] $(date '+%F %T') 批量结束"
        sleep 60   # 跨过本分钟，避免重复触发
    fi
    sleep 30
done
```

- [ ] **Step 2: 加 compose 服务**（复用已构建的 app 镜像，挂同样数据卷，只读 tdx-data）

在 `docker-compose.yml` 的 `services:` 下、`kline-updater` 之后加（缩进对齐其它服务）：

```yaml
  chanlun-scanner:
    image: aiagents-stock-app
    container_name: chanlun-scanner
    depends_on:
      - agentsstock
    working_dir: /app
    command: ["sh", "/app/chanlun_scan_loop.sh"]
    environment:
      - TZ=Asia/Shanghai
      - LOCAL_DB_DIR=/app/tdx-data/database/kline
      - CODES_DB=/app/tdx-api/web/data/database/codes.db
    volumes:
      - ./tdx-data:/app/tdx-data:ro
      - ./data:/app/data
      - ./tdx-api/web/data:/app/tdx-api/web/data:ro
      - ./chanlun_scan_loop.sh:/app/chanlun_scan_loop.sh:ro
    networks:
      - agentsstock-network
```

- [ ] **Step 3: 部署 + 首次手动落库**

Run:
```bash
docker compose up -d --build agentsstock chanlun-scanner
docker exec agentsstock1 python3 /app/chanlun_batch.py   # 首次全市场扫描落库（约 5~18 分钟）
```
Expected: 批量日志输出「股票池 N 只 ... 写入 M 条买点信号」；`data/chanlun_signals.db` 生成。

- [ ] **Step 4: 校验落库**

Run:
```bash
docker exec agentsstock1 sh -c "cd /app && python3 -c \"
from chanlun_selector import ChanlunSelector
ok, df, msg = ChanlunSelector().get_chanlun_picks()
print(msg); print(df.head(10).to_string() if ok else 'none')\""
```
Expected: 打印批次与若干候选（或合理的「暂无」——若当日无买点）。

- [ ] **Step 5: Commit**

```bash
git add chanlun_scan_loop.sh docker-compose.yml
git commit -m "feat(chanlun): chanlun-scanner 调度服务（每日18:30批量）

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 7: 全页回归（16→17 页）+ 真实抽查

**Files:**
- Modify: `tests/test_ui_pages_smoke.py`（PAGE_FLAGS 加 `show_chanlun`）

- [ ] **Step 1: 把 `show_chanlun` 加入页面回归**

在 `tests/test_ui_pages_smoke.py` 的 `PAGE_FLAGS` 列表末尾追加 `"show_chanlun"`。

- [ ] **Step 2: 跑全量页面回归 + 缠论相关测试**

Run:
```bash
docker cp tests/test_ui_pages_smoke.py agentsstock1:/app/tests/
docker exec agentsstock1 sh -c "cd /app && python3 -m pytest tests/test_ui_pages_smoke.py tests/test_chanlun_engine.py tests/test_chanlun_universe.py tests/test_chanlun_signal_db.py tests/test_chanlun_selector.py -q"
docker exec agentsstock1 sh -c "cd /app && python3 -m pytest tests/ -q"
```
Expected: 全 pass（17 页 + 缠论各单测 + 既有回归无回归）。

- [ ] **Step 3: 真实抽查**（人工复核引擎在真实股上的买点合理性）

Run（挑 3 只主板票，打印其缠论买卖点）：
```bash
docker exec agentsstock1 sh -c "cd /app && python3 -c \"
from chanlun_batch import _load
from chanlun_engine import analyze
for code in ['600519','000001','600000']:
    d=_load(code,'day',500); m=_load(code,'30min',2000)
    r=analyze(d,m)
    pts=[(p.kind, str(d.index[p.i].date()) if 0<=p.i<len(d) else '?', round(p.price,2), p.note) for p in r.points][-6:]
    print(code, '中枢数', len(r.pivots), '买卖点(末6)', pts)\""
```
Expected: 输出结构数与近期买卖点；人工核对是否与图形上的底背驰/中枢突破大致吻合。如明显失真，回到计划①对应 Task 调参（如 `_MIN_K_GAP`、背驰 `ratio`、线段判定）。

- [ ] **Step 4: 部署 + 最终核验**

Run:
```bash
docker compose up -d --build agentsstock
docker inspect -f '{{.State.Health.Status}}' agentsstock1   # → healthy
```
打开 `http://<host>:8503` →「选股板块 → 🌀 缠论选股」，确认列表与买点/止损/离场条件展示正常、深浅色主题一致。

- [ ] **Step 5: Commit**

```bash
git add tests/test_ui_pages_smoke.py
git commit -m "test(chanlun): 缠论页纳入17页回归

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Self-Review（plan vs spec）

- **股票池排除科创/北交/ST** → Task 1（`chanlun_universe`）✓
- **信号落库（含 buy_price/stop_loss/exit_rule/level/scan_date）** → Task 2 ✓
- **每日批量预计算 + 仅 TDX 本地源 + 近7交易日买点** → Task 3（`scan_codes` 经 `akshare_gw.local`）✓
- **选股只读库、返回三元组** → Task 4 ✓
- **选股页 + 侧栏按钮 + 路由（套现有模式）** → Task 5 ✓
- **调度串在 kline 更新之后（18:30）** → Task 6（`chanlun-scanner` 复用 app 镜像）✓
- **每只股给出买点+止损+缠论卖点离场条件** → Task 3 写入（来自计划① `buy_point_with_exit`）、Task 5 展示 ✓
- **17 页回归 + 真实抽查** → Task 7 ✓
- **占位符扫描**：无 TBD；每步含完整代码/命令。
- **命名一致性**：`ChanlunSignalDB.upsert_signals/get_latest_signals/clear_scan`、`ChanlunSelector.get_chanlun_picks`、`chanlun_batch.scan_codes/_load`、`chanlun_universe.is_eligible/board_of/list_universe` 全程一致；signals 表 10 列与 `_COLS`、selector `_DISPLAY` 对齐。
- **依赖计划①接口**：`analyze(df_day, df_30m)`、`buy_point_with_exit(bp, pivots)`、`ChanResult.points/.pivots`、`TradePoint.kind/.i/.price/.note` 均与计划①定义一致。
- **风险**：批量耗时（5532×多级别 5~18min）放 18:30 离线可接受；引擎信号质量靠 Task 7 真实抽查复核、必要时回计划①调参。
```
