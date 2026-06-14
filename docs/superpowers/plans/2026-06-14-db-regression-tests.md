# db 层防回归测试安全网 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 6 个未测 db 模块补 characterization CRUD 回路测试,根治"重构时静默丢方法",纯新增 tests/ 零生产改动。

**Architecture:** 每模块一个 `tests/test_<x>_db.py`(pytest):用临时 sqlite 实例化,对主要公共方法跑 save→get(+update/delete) 回路,断言写入值能取回。这是对**既有未测代码**的特征测试——实现者须读该模块的 save/get 方法体确定确切入参(Dict键/位置参数),不臆造。

**Tech Stack:** Python3 + pytest + sqlite。容器内可 `python3 -m pytest tests/test_x.py` 或宿主跑(conftest.py 把根目录加入 sys.path 并设 LOCAL_DB_*)。

参考 spec：`docs/superpowers/specs/2026-06-14-db-regression-tests-design.md`

## 通用规范(所有 Task 遵守)
- 测试放 `tests/`,文件名 `test_<module>.py`,pytest 风格(函数 `def test_...`,assert)。
- **临时库**:每测试用 `os.path.join(tempfile.mkdtemp(), "t.db")` 作 db 路径,实例化时传入(注意各构造器参数名)。互不影响、不写真实 data/*.db。
- **不做任何类级 monkeypatch / 全局态修改 / AppTest**(吸取本会话 flaky:类级替换泄漏致假阳)。不依赖执行顺序。
- **read-source 要求**:save/get 的确切入参(Dict 键名或位置参数、字段)以**模块源码为准**——实现者打开该 .py 读 init_tables 的 CREATE TABLE 列 + save_/get_ 方法体,据此构造合成数据。round-trip 断言必须对**当前行为**为真(测试应 PASS,捕获现状)。
- **零生产改动**:只新增 tests/ 文件,不改任何 *_db.py / base_db.py。
- conftest.py 已存在(把项目根加 sys.path)。从仓库根跑:`python3 -m pytest tests/test_x.py -q`。

## 通用模板(每 Task 按此改写,填入该模块真实方法/字段)
```python
import os, tempfile
from <MODULE> import <CLASS>

def _db():
    return <CLASS>(<CTOR_KW>=os.path.join(tempfile.mkdtemp(), "t.db"))

def test_<module>_crud_roundtrip():
    db = _db()
    # 1) save 合成记录(入参按源码: Dict键/位置参数)
    rid = db.save_xxx(...)          # 或 add_xxx(...)
    # 2) get 取回并断言写入值
    rows = db.get_xxx(...)
    assert rows, "应能取回刚写入的记录"
    # 断言关键字段 round-trip(字段名按源码返回结构)
    assert rows[0]["<某字段>"] == <写入值>
    # 3) (若有)update→值变 / delete→取不到
    ...
```

---

### Task 1: test_main_force_batch_db.py（最简,单表,作样板）

**Files:** Create `tests/test_main_force_batch_db.py`

- [ ] **Step 1: 读源码确定入参** — 打开 `main_force_batch_db.py`:类 `MainForceBatchDatabase(db_path=...)`;表 `batch_analysis_history`(列: analysis_date,batch_count,analysis_mode,success_count,failed_count,total_time,results_json,created_at);方法 `save_batch_analysis(...)`(读其 def 形参与体,确定它接收哪些字段/是否接收 results list)、`get_all_history(limit)`、`get_record_by_id(record_id)`、`delete_record(record_id)`、`get_statistics()`。

- [ ] **Step 2: 写测试**(按真实签名填入参) — 结构:
```python
import os, tempfile
from main_force_batch_db import MainForceBatchDatabase

def _db():
    return MainForceBatchDatabase(db_path=os.path.join(tempfile.mkdtemp(), "t.db"))

def test_main_force_batch_crud():
    db = _db()
    rid = db.save_batch_analysis(<按源码: 如 analysis_mode/批量结果list等>)
    hist = db.get_all_history(limit=10)
    assert hist and any(r.get("id") == rid for r in hist)
    rec = db.get_record_by_id(rid)
    assert rec is not None
    st = db.get_statistics()
    assert isinstance(st, dict)
    assert db.delete_record(rid) in (True, 1, None)
    assert db.get_record_by_id(rid) in (None, {}, [])

if __name__ == "__main__":
    test_main_force_batch_crud(); print("ALL main_force_batch_db OK")
```
入参与断言字段以源码为准微调,使测试 PASS。

- [ ] **Step 3: 跑** — `python3 -m pytest tests/test_main_force_batch_db.py -q`(或 `cd tests && python3 -c "..."`)→ PASS。若 save 入参不符,读源码改正(不改生产)。

- [ ] **Step 4: 提交** — `git add tests/test_main_force_batch_db.py && git commit -m "test(db): main_force_batch_db CRUD 回路特征测试

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"`

---

### Task 2: test_sector_strategy_db.py

**Files:** Create `tests/test_sector_strategy_db.py`

- [ ] **Step 1: 读源码** — `SectorStrategyDatabase(db_path=...)`;表 `sector_raw_data`/`sector_analysis_reports`;方法 `save_raw_data(data_type, data_list)`、`get_latest_raw_data(data_type, limit)`、`save_analysis_report(data_date_range, analysis_content, ...)`、`get_analysis_reports(limit)`、`get_analysis_report(report_id)`、`delete_analysis_report(report_id)`。读 save_raw_data 体确定 data_list 元素是 dict(哪些键)还是别的;读 save_analysis_report 的其余形参。

- [ ] **Step 2: 写测试** — 覆盖:save_raw_data(合成1-2条) → get_latest_raw_data 取回非空;save_analysis_report → get_analysis_reports 含之 → get_analysis_report(id) 非空 → delete_analysis_report(id) 后 get_analysis_report 取不到。结构同模板。`if __name__` 加 print("ALL sector_strategy_db OK")。

- [ ] **Step 3: 跑** — `python3 -m pytest tests/test_sector_strategy_db.py -q` → PASS。

- [ ] **Step 4: 提交** — `git add tests/test_sector_strategy_db.py && git commit -m "test(db): sector_strategy_db CRUD 回路特征测试

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"`

---

### Task 3: test_monitor_db.py

**Files:** Create `tests/test_monitor_db.py`

- [ ] **Step 1: 读源码** — `StockMonitorDatabase(db_path=...)`;表 `monitored_stocks`/`price_history`/`notifications`;方法 `add_monitored_stock(symbol,name,rating,entry_range,...)`(读 def 全形参,entry_range 是 dict)、`get_monitored_stocks()`、`update_stock_price(stock_id,price)`、`update_last_checked(stock_id)`、`has_recent_notification(stock_id,type,minutes)`、`add_notification(stock_id,type,message)`、`get_pending_notifications()`、`mark_notification_sent(notification_id)`。

- [ ] **Step 2: 写测试** — 覆盖:add_monitored_stock → get_monitored_stocks 返回该股(断言 symbol/name);取其 id → update_stock_price(id,价) 不崩 + get 后 current_price 变;add_notification(id,...) → get_pending_notifications 含之 → mark_notification_sent(nid) 后 get_pending 不含;has_recent_notification 返回 bool。结构同模板。

- [ ] **Step 3: 跑** — `python3 -m pytest tests/test_monitor_db.py -q` → PASS。

- [ ] **Step 4: 提交** — `git add tests/test_monitor_db.py && git commit -m "test(db): monitor_db CRUD 回路特征测试

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"`

---

### Task 4: test_smart_monitor_db.py（⚠️构造参数 db_file）

**Files:** Create `tests/test_smart_monitor_db.py`

- [ ] **Step 1: 读源码** — `SmartMonitorDB(db_file=...)`(**注意是 db_file 不是 db_path**);表 `monitor_tasks`/`ai_decisions`/`trade_records`...;方法 `add_monitor_task(task_data: Dict)`(读体确定 task_data 必需键,如 stock_code 等)、`get_monitor_tasks(enabled_only)`、`update_monitor_task(stock_code, updates: Dict)`、`delete_monitor_task(task_id)`、`save_ai_decision(decision_data: Dict)`、`get_ai_decisions(stock_code,limit)`。

- [ ] **Step 2: 写测试** — `_db()` 用 `SmartMonitorDB(db_file=tmp)`。覆盖:add_monitor_task(合成dict) → get_monitor_tasks(enabled_only=False) 含之;update_monitor_task(stock_code, {...}) → 值变;save_ai_decision(dict) → get_ai_decisions 含之;delete_monitor_task(task_id) 后取不到。dict 键以源码为准。结构同模板。

- [ ] **Step 3: 跑** — `python3 -m pytest tests/test_smart_monitor_db.py -q` → PASS。

- [ ] **Step 4: 提交** — `git add tests/test_smart_monitor_db.py && git commit -m "test(db): smart_monitor_db CRUD 回路特征测试(db_file构造)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"`

---

### Task 5: test_longhubang_db.py

**Files:** Create `tests/test_longhubang_db.py`

- [ ] **Step 1: 读源码** — `LonghubangDatabase(db_path=...)`;表 `longhubang_records`/`longhubang_analysis`/`stock_tracking`;方法 `save_longhubang_data(data_list)`(读体确定 data_list 元素 dict 键)、`get_longhubang_data(start_date,end_date,stock_code)`、`get_top_stocks(...)`、`save_analysis_report(data_date_range, analysis_content, ...)`、`get_analysis_reports(limit)`、`get_analysis_report(report_id)`、`delete_analysis_report(report_id)`。

- [ ] **Step 2: 写测试** — 覆盖:save_longhubang_data([合成dict]) → get_longhubang_data() 取回非空(断言某字段);save_analysis_report → get_analysis_reports 含之 → get_analysis_report(id) 非空 → delete_analysis_report(id) 后取不到;get_top_stocks() 不崩返回 list。结构同模板。

- [ ] **Step 3: 跑** — `python3 -m pytest tests/test_longhubang_db.py -q` → PASS。

- [ ] **Step 4: 提交** — `git add tests/test_longhubang_db.py && git commit -m "test(db): longhubang_db CRUD 回路特征测试

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"`

---

### Task 6: test_news_flow_db.py（最大,28方法,覆盖核心回路即可）

**Files:** Create `tests/test_news_flow_db.py`

- [ ] **Step 1: 读源码** — `NewsFlowDatabase(db_path=...)`;表 `flow_snapshots`/`platform_news`/`stock_related_news`/`sentiment_records`/`flow_statistics`...;核心方法 `save_flow_snapshot(flow_data: Dict, platforms_data: List[Dict], ...)`(读 def 全形参 + 体,确定 flow_data 键 / 还接哪些参数 / 返回 snapshot_id)、`get_latest_snapshot()`、`get_recent_snapshots(limit)`、`save_sentiment_record(snapshot_id, sentiment_data: Dict)`、`get_recent_scores(hours)`、`get_daily_statistics(...)`。

- [ ] **Step 2: 写测试** — 覆盖核心回路:save_flow_snapshot(合成 flow_data + platforms_data) → 返回 snapshot_id;get_latest_snapshot() 非空(断言某字段);get_recent_snapshots(10) 含之;save_sentiment_record(snapshot_id, dict) → get_recent_scores(24) 含之/非空;get_daily_statistics(...) 不崩。入参/字段以源码为准。结构同模板。(28 方法不必全覆盖;核心 save/get 回路 + 主要查询即可,纯展示/聚合方法验"不崩返回预期类型"。)

- [ ] **Step 3: 跑** — `python3 -m pytest tests/test_news_flow_db.py -q` → PASS。

- [ ] **Step 4: 提交** — `git add tests/test_news_flow_db.py && git commit -m "test(db): news_flow_db 核心CRUD回路特征测试

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"`

---

### Task 7: 全量回归确认 + 收尾

**Files:** 无新增(验证)。

- [ ] **Step 1: 全量跑** — `cd /home/tdxback/aiagents-stock && python3 -m pytest tests/ -q` → 期望 6 个新 db 测试全过 + 无回归(0 failed;test_liumai_selector 等本会话已修)。若某新测失败=该模块真实签名与测试不符 → 回到对应 Task 读源码改测试(不改生产)。

- [ ] **Step 2: 记忆/收尾** — 在 memory backlog 标注 db 层防回归安全网已建(6 模块特征测试),db 层重构痛点("改时丢方法")已通过测试根治;统一/抽重复/ORM 仍留"诊断后另议"。

---

## Self-Review

**1. Spec coverage:** 6 个未测模块 → Task1-6 各一;核心 CRUD 回路 → 每 Task Step2 save→get(+update/delete);零生产改动 → 仅 tests/;flaky 规范 → 通用规范"不做类级monkeypatch/独立临时库/不依赖顺序";全量回归 → Task7。✓
**2. Placeholder scan:** 各 Task 给了 类/构造器/表/方法清单/模板/断言结构/运行命令/提交;save 的确切入参刻意要求"读源码"——这是对既有未测代码做特征测试的必要步骤(入参只在源码),非 hand-wave:已提供完整模板+方法覆盖清单+round-trip 验收标准。非占位。
**3. Type consistency:** 各 Task 构造器参数名已核对(5个 db_path,smart_monitor **db_file**);方法名取自实际 grep;模板一致(_db()/save→get→assert);Task7 跑全量。
