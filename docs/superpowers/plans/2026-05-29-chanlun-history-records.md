# 缠论选股历史记录 + 日期筛选 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让缠论选股每个扫描批次(scan_date)完整留存为历史，前台按扫描日期筛选(默认最新)，并每日导出一份 CSV 备份到服务器。

**Architecture:** 复用现有 `chanlun_signals.db`(SQLite)。把唯一约束从 `(code, signal_type, signal_date)` 升级为含 `scan_date` 的 4 列键(带就地迁移)，使每日批次互不覆盖。新增按日期查询方法供前台日期下拉与展示。`chanlun_batch` 落库后额外导出当日 CSV 备份(仅备份，不参与展示)。

**Tech Stack:** Python 3、SQLite(via `base_db.BaseDatabase`)、pandas、Streamlit、pytest。

**Baseline note:** 工作区已有一份未提交的"买入理由/卖点"在制改动(buy_reason / sell_type / sell_date / sell_reason 列已替换旧 exit_rule)。本计划**在该工作区状态之上**实现，所有代码片段与之对齐。

---

## File Structure

- `chanlun_signal_db.py`(Modify):升级唯一约束 + 迁移 + 新增 `list_scan_dates()`、`get_signals_by_scan_date()`。数据层唯一改动点。
- `chanlun_selector.py`(Modify):`get_chanlun_picks` 增加 `scan_date` 参数；新增 `list_dates()`。
- `chanlun_batch.py`(Modify):新增 `export_scan_csv()` 并在 `main()` 调用。
- `chanlun_ui.py`(Modify):加扫描日期下拉框，缓存 key 含 scan_date。
- `tests/test_chanlun_signal_db.py`(Modify):多批次留存、迁移、新查询方法用例。
- `tests/test_chanlun_selector.py`(Modify):按日期取 picks、`list_dates`。
- `tests/test_chanlun_batch.py`(Modify):CSV 导出用例。

测试运行约定(项目坑)：用 `python3 -m pytest`，不要用 `python`。

---

## Task 1: 数据层唯一约束升级 + 就地迁移

**Files:**
- Modify: `chanlun_signal_db.py`
- Test: `tests/test_chanlun_signal_db.py`

- [ ] **Step 1: 写失败测试 —— 多 scan_date 同一买点不被覆盖**

在 `tests/test_chanlun_signal_db.py` 末尾追加：

```python
def test_same_signal_different_scan_dates_both_kept():
    db = _db()
    base = {"code": "600000", "name": "浦发", "board": "沪主板", "signal_type": "1买",
            "signal_date": "2026-05-26", "buy_price": 10.0, "buy_reason": "x", "stop_loss": 9.8,
            "sell_type": "", "sell_date": "", "sell_reason": "", "level": "日线"}
    db.upsert_signals([dict(base, scan_date="2026-05-27")])
    db.upsert_signals([dict(base, scan_date="2026-05-28")])
    with db.conn() as conn:
        n = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
    assert n == 2  # 两个批次各留一条，互不覆盖
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python3 -m pytest tests/test_chanlun_signal_db.py::test_same_signal_different_scan_dates_both_kept -v`
Expected: FAIL —— 旧唯一键 `(code, signal_type, signal_date)` 触发冲突，COUNT 为 1。

- [ ] **Step 3: 升级唯一约束 + upsert 冲突目标**

在 `chanlun_signal_db.py`，把 `init_tables` 里 CREATE TABLE 的约束行改为含 scan_date：

```python
                level TEXT,
                scan_date TEXT NOT NULL,
                UNIQUE(code, signal_type, signal_date, scan_date)
            )""")
```

把 `upsert_signals` 的 `ON CONFLICT(...)` 目标改为 4 列键，并**移除** `scan_date=excluded.scan_date`(它已是键)：

```python
                conn.execute(f"""
                    INSERT INTO signals ({','.join(_COLS)})
                    VALUES ({','.join(['?'] * len(_COLS))})
                    ON CONFLICT(code, signal_type, signal_date, scan_date) DO UPDATE SET
                        name=excluded.name, board=excluded.board,
                        buy_price=excluded.buy_price, buy_reason=excluded.buy_reason,
                        stop_loss=excluded.stop_loss,
                        sell_type=excluded.sell_type, sell_date=excluded.sell_date,
                        sell_reason=excluded.sell_reason, level=excluded.level
                """, vals)
```

- [ ] **Step 4: 运行新测试 + 既有测试，确认通过**

Run: `python3 -m pytest tests/test_chanlun_signal_db.py -v`
Expected: 全部 PASS —— 新用例 2 条；`test_upsert_idempotent_on_unique_key`(同 scan_date 同键)仍覆盖为 buy_price=11.0。

- [ ] **Step 5: 写迁移失败测试 —— 旧约束库升级后保留数据并放开覆盖**

追加：

```python
def test_migrates_old_unique_constraint(tmp_path):
    import sqlite3
    path = str(tmp_path / "old.db")
    # 手造旧表(3 列唯一键、含遗留 exit_rule、缺新列)并塞一条数据
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT NOT NULL, name TEXT, board TEXT,
        signal_type TEXT NOT NULL, signal_date TEXT NOT NULL,
        buy_price REAL, stop_loss REAL, exit_rule TEXT, level TEXT,
        scan_date TEXT NOT NULL,
        UNIQUE(code, signal_type, signal_date))""")
    conn.execute("INSERT INTO signals (code, signal_type, signal_date, buy_price, scan_date) "
                 "VALUES ('600000','1买','2026-05-26',10.0,'2026-05-27')")
    conn.commit(); conn.close()

    db = ChanlunSignalDB(db_path=path)  # 触发 init_tables → 迁移
    # 旧数据仍在
    with db.conn() as c:
        assert c.execute("SELECT COUNT(*) FROM signals").fetchone()[0] == 1
    # 迁移后同买点不同 scan_date 可并存(说明约束已升级)
    db.upsert_signals([{"code": "600000", "name": "", "board": "沪主板", "signal_type": "1买",
                        "signal_date": "2026-05-26", "buy_price": 10.0, "buy_reason": "",
                        "stop_loss": 9.8, "sell_type": "", "sell_date": "", "sell_reason": "",
                        "level": "日线", "scan_date": "2026-05-28"}])
    with db.conn() as c:
        assert c.execute("SELECT COUNT(*) FROM signals").fetchone()[0] == 2
```

- [ ] **Step 6: 运行确认失败**

Run: `python3 -m pytest tests/test_chanlun_signal_db.py::test_migrates_old_unique_constraint -v`
Expected: FAIL —— 旧约束未迁移，第二次 upsert 冲突覆盖，COUNT 为 1。

- [ ] **Step 7: 实现迁移逻辑**

在 `chanlun_signal_db.py` 的 `ChanlunSignalDB` 类内新增两个方法：

```python
    @staticmethod
    def _unique_has_scan_date(conn) -> bool:
        for idx in conn.execute("PRAGMA index_list(signals)"):
            name, is_unique = idx[1], idx[2]
            if not is_unique:
                continue
            cols = {r[2] for r in conn.execute(f"PRAGMA index_info('{name}')")}
            if {"code", "signal_type", "signal_date", "scan_date"} <= cols:
                return True
        return False

    def _migrate_unique_key(self, conn):
        old_cols = [r[1] for r in conn.execute("PRAGMA table_info(signals)")]
        conn.execute("""CREATE TABLE signals_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL, name TEXT, board TEXT,
            signal_type TEXT NOT NULL, signal_date TEXT NOT NULL,
            buy_price REAL, buy_reason TEXT, stop_loss REAL,
            sell_type TEXT, sell_date TEXT, sell_reason TEXT,
            level TEXT, scan_date TEXT NOT NULL,
            UNIQUE(code, signal_type, signal_date, scan_date))""")
        new_cols = ["code", "name", "board", "signal_type", "signal_date",
                    "buy_price", "buy_reason", "stop_loss",
                    "sell_type", "sell_date", "sell_reason", "level", "scan_date"]
        common = ",".join(c for c in new_cols if c in old_cols)
        conn.execute(f"INSERT INTO signals_new ({common}) SELECT {common} FROM signals")
        conn.execute("DROP TABLE signals")
        conn.execute("ALTER TABLE signals_new RENAME TO signals")
        self.logger.info("[缠论库] 唯一约束已迁移为含 scan_date(历史批次将完整保留)")
```

在 `init_tables` 的补列循环之后追加迁移调用(仍在 `with self.conn() as conn:` 块内，借 BaseDatabase 的成功自动 commit / 异常 rollback 保证原子)：

```python
            for col in _NEW_COLS:
                if col not in existing:
                    conn.execute(f"ALTER TABLE signals ADD COLUMN {col} TEXT")
            if not self._unique_has_scan_date(conn):
                self._migrate_unique_key(conn)
```

- [ ] **Step 8: 运行整文件测试确认全绿**

Run: `python3 -m pytest tests/test_chanlun_signal_db.py -v`
Expected: 全部 PASS。

- [ ] **Step 9: 提交**

```bash
git add chanlun_signal_db.py tests/test_chanlun_signal_db.py
git commit -m "feat(chanlun): scan_date 纳入唯一键并迁移旧库，历史批次互不覆盖

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: 数据层新增按日期查询方法

**Files:**
- Modify: `chanlun_signal_db.py`
- Test: `tests/test_chanlun_signal_db.py`

- [ ] **Step 1: 写失败测试**

追加：

```python
def test_list_scan_dates_distinct_desc():
    db = _db()
    base = {"code": "600000", "name": "", "board": "沪主板", "signal_type": "1买",
            "signal_date": "2026-05-26", "buy_price": 10.0, "buy_reason": "", "stop_loss": 9.8,
            "sell_type": "", "sell_date": "", "sell_reason": "", "level": "日线"}
    for sd in ("2026-05-27", "2026-05-28", "2026-05-27"):
        db.upsert_signals([dict(base, scan_date=sd)])
    assert db.list_scan_dates() == ["2026-05-28", "2026-05-27"]


def test_get_signals_by_scan_date():
    db = _db()
    base = {"code": "600000", "name": "", "board": "沪主板", "signal_type": "1买",
            "signal_date": "2026-05-26", "buy_price": 10.0, "buy_reason": "", "stop_loss": 9.8,
            "sell_type": "", "sell_date": "", "sell_reason": "", "level": "日线"}
    db.upsert_signals([dict(base, scan_date="2026-05-27")])
    db.upsert_signals([dict(base, code="300750", scan_date="2026-05-28")])
    df = db.get_signals_by_scan_date("2026-05-27")
    assert len(df) == 1 and df.iloc[0]["code"] == "600000"
```

- [ ] **Step 2: 运行确认失败**

Run: `python3 -m pytest tests/test_chanlun_signal_db.py::test_list_scan_dates_distinct_desc tests/test_chanlun_signal_db.py::test_get_signals_by_scan_date -v`
Expected: FAIL —— `AttributeError: 'ChanlunSignalDB' object has no attribute 'list_scan_dates'`。

- [ ] **Step 3: 实现两个查询方法**

在 `ChanlunSignalDB` 内(`get_latest_signals` 之后)新增：

```python
    def list_scan_dates(self) -> list:
        """全部扫描批次日期，去重、倒序(最新在前)，供前台日期下拉。"""
        with self.conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT scan_date FROM signals ORDER BY scan_date DESC"
            ).fetchall()
        return [r[0] for r in rows]

    def get_signals_by_scan_date(self, scan_date: str) -> pd.DataFrame:
        """返回指定扫描批次的全部信号(列同 get_latest_signals)。"""
        with self.conn() as conn:
            return pd.read_sql_query(
                "SELECT * FROM signals WHERE scan_date=? ORDER BY signal_date DESC, code",
                conn, params=(scan_date,))
```

- [ ] **Step 4: 运行确认通过**

Run: `python3 -m pytest tests/test_chanlun_signal_db.py -v`
Expected: 全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add chanlun_signal_db.py tests/test_chanlun_signal_db.py
git commit -m "feat(chanlun): 新增 list_scan_dates / get_signals_by_scan_date

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: 选股层支持按日期取数

**Files:**
- Modify: `chanlun_selector.py`
- Test: `tests/test_chanlun_selector.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_chanlun_selector.py` 末尾追加(复用文件顶部 `_seed`，其 scan_date 为 "2026-05-27")：

```python
def test_list_dates():
    sel = ChanlunSelector(db=_seed())
    assert sel.list_dates() == ["2026-05-27"]


def test_get_picks_by_scan_date():
    db = _seed()
    # 追加一个更早批次，确认按日期能取到旧批次而非最新
    db.upsert_signals([
        {"code": "000001", "name": "平安", "board": "深主板", "signal_type": "1买",
         "signal_date": "2026-05-20", "buy_price": 12.0, "buy_reason": "x", "stop_loss": 11.8,
         "sell_type": "", "sell_date": "", "sell_reason": "", "level": "日线",
         "scan_date": "2026-05-22"}])
    sel = ChanlunSelector(db=db)
    ok, df, msg = sel.get_chanlun_picks(scan_date="2026-05-22")
    assert ok and len(df) == 1 and df.iloc[0]["code"] == "000001"
```

- [ ] **Step 2: 运行确认失败**

Run: `python3 -m pytest tests/test_chanlun_selector.py::test_list_dates tests/test_chanlun_selector.py::test_get_picks_by_scan_date -v`
Expected: FAIL —— `list_dates` 不存在；`get_chanlun_picks` 不接受 `scan_date`。

- [ ] **Step 3: 实现**

在 `chanlun_selector.py`，把 `get_chanlun_picks` 签名与取数改为：

```python
    def get_chanlun_picks(self, types: Optional[List[str]] = None,
                          scan_date: Optional[str] = None
                          ) -> Tuple[bool, Optional[pd.DataFrame], str]:
        df = (self.db.get_signals_by_scan_date(scan_date) if scan_date
              else self.db.get_latest_signals())
        if df is None or df.empty:
            return False, None, "暂无缠论买点信号（批量扫描尚未运行或近7交易日无信号）"
        if types:
            df = df[df["signal_type"].isin(types)]
        if df.empty:
            return False, None, "所选买点类型暂无信号"
        scan_date = df["scan_date"].iloc[0]
        view = df[KEEP_COLS].reset_index(drop=True)
        return True, view, f"扫描批次 {scan_date}，共 {len(view)} 只"
```

并在类内新增：

```python
    def list_dates(self) -> List[str]:
        """可选的扫描批次日期(倒序)，供前台日期下拉。"""
        return self.db.list_scan_dates()
```

- [ ] **Step 4: 运行确认通过**

Run: `python3 -m pytest tests/test_chanlun_selector.py -v`
Expected: 全部 PASS(含原有 3 条)。

- [ ] **Step 5: 提交**

```bash
git add chanlun_selector.py tests/test_chanlun_selector.py
git commit -m "feat(chanlun): selector 支持按 scan_date 取数 + list_dates

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: 每日 CSV 备份导出

**Files:**
- Modify: `chanlun_batch.py`
- Test: `tests/test_chanlun_batch.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_chanlun_batch.py` 末尾追加(不依赖容器 K 线库，直接喂库)：

```python
def test_export_scan_csv(tmp_path):
    import pandas as pd
    from chanlun_batch import export_scan_csv
    db = ChanlunSignalDB(db_path=str(tmp_path / "s.db"))
    db.upsert_signals([
        {"code": "600000", "name": "浦发", "board": "沪主板", "signal_type": "1买",
         "signal_date": "2026-05-26", "buy_price": 10.0, "buy_reason": "x", "stop_loss": 9.8,
         "sell_type": "", "sell_date": "", "sell_reason": "", "level": "日线",
         "scan_date": "2026-05-27"}])
    out = tmp_path / "hist"
    path = export_scan_csv(db, "2026-05-27", out_dir=str(out))
    assert os.path.exists(path)
    assert path.endswith("2026-05-27.csv")
    df = pd.read_csv(path, dtype=str)
    assert len(df) == 1 and df.iloc[0]["code"] == "600000"
```

- [ ] **Step 2: 运行确认失败**

Run: `python3 -m pytest tests/test_chanlun_batch.py::test_export_scan_csv -v`
Expected: FAIL —— `ImportError: cannot import name 'export_scan_csv'`。

- [ ] **Step 3: 实现导出函数并接入 main**

在 `chanlun_batch.py` 顶部 import 区补充：

```python
import os
from base_db import DATA_DIR
```

新增函数(放在 `scan_codes` 之后、`main` 之前)：

```python
def export_scan_csv(db: ChanlunSignalDB, scan_date: str, out_dir: str = None) -> str:
    """把指定批次完整名单导出 CSV 备份(仅备份，不参与前台展示)。返回文件路径。"""
    out_dir = out_dir or os.path.join(DATA_DIR, "chanlun_history")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{scan_date}.csv")
    df = db.get_signals_by_scan_date(scan_date)
    df.to_csv(path, index=False, encoding="utf-8-sig")  # utf-8-sig 便于 Excel 中文
    return path
```

在 `main()` 的 `logger.info(f"[缠论批量] 完成：...")` 之后追加(导出失败不阻断主流程)：

```python
    try:
        csv_path = export_scan_csv(db, scan_date)
        logger.info(f"[缠论批量] 已导出 CSV 备份：{csv_path}")
    except Exception as e:
        logger.warning(f"[缠论批量] CSV 备份导出失败(不影响落库): {type(e).__name__}: {e}")
```

- [ ] **Step 4: 运行确认通过**

Run: `python3 -m pytest tests/test_chanlun_batch.py::test_export_scan_csv -v`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add chanlun_batch.py tests/test_chanlun_batch.py
git commit -m "feat(chanlun): 每日扫描后导出 CSV 备份到 data/chanlun_history

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: 前台扫描日期下拉框

**Files:**
- Modify: `chanlun_ui.py`

说明：Streamlit 页面渲染逻辑不做单元测试(项目惯例：用 AppTest 无头跑全站冒烟，单页交互手验)。本任务以代码改动 + 手动验证为准。

- [ ] **Step 1: 改造缓存函数签名(加 scan_date)**

在 `chanlun_ui.py`，把缓存函数改为：

```python
@st.cache_data(ttl=1800, show_spinner=False)
def _cached_picks(types_key: tuple, scan_date: str):
    return ChanlunSelector().get_chanlun_picks(types=list(types_key), scan_date=scan_date)
```

- [ ] **Step 2: 加日期下拉并传参**

把 `display_chanlun_selector` 中从 `picked = st.multiselect(...)` 到 `ok, df, msg = _cached_picks(...)` 之间改为：

```python
    dates = ChanlunSelector().list_dates()
    if not dates:
        st.info("暂无缠论买点信号（批量扫描尚未运行）")
        return

    col1, col2 = st.columns([2, 1])
    with col1:
        picked = st.multiselect("买点类型", _TYPES, default=_TYPES)
    with col2:
        scan_date = st.selectbox("扫描日期", dates, index=0)  # 倒序，默认最新

    ok, df, msg = _cached_picks(tuple(picked), scan_date)
```

其余(`st.info(msg)`、`st.dataframe(...)`、caption)保持不变。

- [ ] **Step 3: 语法自检**

Run: `python3 -c "import ast; ast.parse(open('chanlun_ui.py').read()); print('ok')"`
Expected: 打印 `ok`。

- [ ] **Step 4: 手动验证(容器内)**

在已部署环境中打开缠论选股页，确认：
1. 顶部出现"扫描日期"下拉，默认选中最新日期；
2. 切换到较早日期后，列表内容随之变化、`st.info` 提示的"扫描批次"日期同步；
3. 改变"买点类型"多选与日期组合，结果正确。

若无运行环境，至少用 Streamlit AppTest 冒烟：
Run: `python3 -c "from streamlit.testing.v1 import AppTest"` 确认 AppTest 可用，再按项目既有无头测试法跑全站入口。

- [ ] **Step 5: 提交**

```bash
git add chanlun_ui.py
git commit -m "feat(chanlun): 前台增加扫描日期下拉(默认最新)，可回看历史批次

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: 全量回归

- [ ] **Step 1: 跑全部缠论相关测试**

Run: `python3 -m pytest tests/test_chanlun_signal_db.py tests/test_chanlun_selector.py tests/test_chanlun_batch.py -v`
Expected: 全部 PASS(容器外 `test_scan_codes_writes_db_without_error` 因 skipif 跳过属正常)。

- [ ] **Step 2: 确认 data/chanlun_history 不入 git 跟踪**

Run: `git status --short data/`
Expected: 无 `data/chanlun_history/` 出现(data/ 已整体移出跟踪)。如出现，确认 `.gitignore` 已忽略 data/。

---

## Self-Review(已核对)

- **Spec 覆盖**：唯一约束修复+迁移→Task1；list_scan_dates/get_signals_by_scan_date→Task2；selector scan_date 参数+list_dates→Task3；CSV 备份→Task4；UI 日期下拉→Task5；永久保留=不加清理逻辑(全程未引入删除)；回归→Task6。全部命中。
- **占位符**：无 TBD/TODO，所有代码步骤含完整代码。
- **类型/命名一致**：`list_scan_dates`(DB)↔`list_dates`(selector/UI)；`get_signals_by_scan_date`(DB)被 selector(Task3)、export_scan_csv(Task4)一致调用；`export_scan_csv(db, scan_date, out_dir=None)` 签名在测试与 main 调用一致；`_cached_picks(types_key, scan_date)` 与定义一致。
- **基线一致**：所有 `_COLS`/列名(buy_reason、sell_type、sell_date、sell_reason)与工作区在制状态一致。
