# 缠论选股历史记录 + 日期筛选 — 设计文档

日期：2026-05-29

## 背景与问题

缠论选股每日收盘后由 `chanlun_batch.py` 批量扫描，把近 7 个交易日出现的
一买/二买/三买买点写入 `chanlun_signals.db`。前台 `chanlun_ui.py` 只读
最新批次（`MAX(scan_date)`），无法回看历史，且**历史批次实际留不住**。

**根因**：`signals` 表唯一约束为 `UNIQUE(code, signal_type, signal_date)`，
**不含 `scan_date`**。因每日扫描回看近 7 个交易日，同一个买点
（同 code/signal_type/signal_date）会被连续约 7 天的扫描反复 upsert，
其 `scan_date` 被不断改写为最新值。结果：每个买点只保留"最后一次扫到它的
批次"，干净的"每天选股名单"无法留存。

## 目标

1. 让每天的扫描批次（scan_date）完整、独立地留存为历史，永久保留。
2. 服务器上每日额外保存一份 CSV 备份文件（仅备份，不参与前台展示）。
3. 前台缠论选股页增加**按扫描日期 scan_date 筛选**，默认显示最新一天。

## 确认的需求决策

- **存储**：复用现有 SQLite 库做前台展示；服务器另存一份 CSV 文件做备份，
  备份文件不参与前台展示。
- **筛选维度**：前台按 `scan_date`（扫描批次日期）筛选，默认最新一天。
- **保留策略**：永久保留，DB 不主动删除任何历史批次。
- **备份格式**：CSV，每个扫描日一个文件。

## 非目标（YAGNI）

- 不做按 `signal_date`（买点形成日）的二级筛选。
- 不做历史数据的自动清理/归档。
- 不改动缠论算法、股票池、调度时间。
- 不把 CSV 备份接入前台读取路径。

## 设计

### 1. 数据层（`chanlun_signal_db.py`）—— 核心改动

**唯一约束**：改为 `UNIQUE(code, signal_type, signal_date, scan_date)`，
使每个扫描批次独立保留完整快照。

**就地迁移**：`init_tables()` 中检测现有 `signals` 表的唯一索引列
（`PRAGMA index_list(signals)` + `PRAGMA index_info(<idx>)`）。若该唯一索引
列集合不含 `scan_date`，执行迁移（SQLite 无法直接修改约束）：

1. `CREATE TABLE signals_new (... UNIQUE(code, signal_type, signal_date, scan_date))`
   （列定义与现表一致，含历史遗留的 `exit_rule` 兼容列保持现有补列逻辑）。
2. `INSERT INTO signals_new (<显式列>) SELECT <显式列> FROM signals`。
3. `DROP TABLE signals`；`ALTER TABLE signals_new RENAME TO signals`。

迁移幂等：已是新约束则跳过。旧数据因覆盖问题本身不完整，但迁移后从此
每天干净留存。保留对缺失新列（`buy_reason` 等 `_NEW_COLS`）的就地补列逻辑。

**upsert**：`upsert_signals` 的 `ON CONFLICT(...)` 目标同步改为 4 列键
`(code, signal_type, signal_date, scan_date)`；冲突时更新非键列
（name、board、buy_price、buy_reason、stop_loss、sell_*、level）。

**新增查询方法**：
- `list_scan_dates() -> list[str]`：`SELECT DISTINCT scan_date FROM signals
  ORDER BY scan_date DESC`，供前台日期下拉。
- `get_signals_by_scan_date(scan_date: str) -> pd.DataFrame`：返回该批次全部
  信号，列与 `get_latest_signals` 一致，排序 `signal_date DESC, code`。

`get_latest_signals()` 保留不动。

### 2. 服务器 CSV 备份（`chanlun_batch.py`）

`main()` 在 `upsert_signals` 之后，把当天完整名单导出：
- 目录 `data/chanlun_history/`（不存在则 `os.makedirs(..., exist_ok=True)`）。
- 文件 `data/chanlun_history/<scan_date>.csv`，同日重跑覆盖。
- 内容取自 `db.get_signals_by_scan_date(scan_date)`，`to_csv(index=False,
  encoding="utf-8-sig")`（utf-8-sig 便于 Excel 中文）。
- 空名单时不报错（写表头或跳过，记 info 日志）。
- 导出失败仅记 warning，不影响落库主流程。

### 3. 选股层（`chanlun_selector.py`）

- `get_chanlun_picks(types=None, scan_date=None)`：`scan_date=None` 时
  走 `get_latest_signals()`（保持旧行为）；否则走
  `get_signals_by_scan_date(scan_date)`。其余筛选/列裁剪逻辑不变，
  msg 中体现所选批次日期。
- 新增 `list_dates() -> list[str]`：透传 `db.list_scan_dates()`。

### 4. 前台 UI（`chanlun_ui.py`）

- 取 `dates = ChanlunSelector().list_dates()`；若为空，提示暂无数据并返回。
- 在"买点类型"多选旁加 `st.selectbox("扫描日期", dates, index=0)`
  （倒序，默认 `dates[0]` 即最新）。
- 缓存函数 key 改为 `(types_key, scan_date)`：
  `_cached_picks(types_key, scan_date)` 调
  `get_chanlun_picks(types=list(types_key), scan_date=scan_date)`。
- 其余展示与 caption 不变。

### 5. 测试

`tests/test_chanlun_signal_db.py` 新增：
- 多个 scan_date 写入同一买点（同 code/type/signal_date，不同 scan_date）后
  两条都在，互不覆盖。
- `list_scan_dates()` 去重且倒序。
- `get_signals_by_scan_date()` 只返回指定批次。
- 迁移用例：用旧约束建表写入数据 → `init_tables()` → 验证约束已升级且
  旧数据保留。

`tests/test_chanlun_batch.py` 新增：
- 扫描后 `data/chanlun_history/<scan_date>.csv` 生成，行数/内容与库一致
  （用 tmp 目录或 monkeypatch 输出路径，避免污染真实 data/）。

## 数据流

```
chanlun_batch (每日 20:00)
  → upsert_signals  (含 scan_date 的唯一键，留每日批次)
  → 导出 data/chanlun_history/<scan_date>.csv  (备份)
UI 打开
  → list_scan_dates() 填日期下拉 (默认最新)
  → 选 scan_date → get_signals_by_scan_date() → 展示
```

## 错误处理

- 迁移：包在事务里，失败回滚并抛出，避免半迁移状态。
- CSV 导出：失败仅 warning，不阻断落库。
- UI 无数据：友好提示，不抛异常。

## 影响面

改动文件：`chanlun_signal_db.py`、`chanlun_batch.py`、`chanlun_selector.py`、
`chanlun_ui.py`，及对应两个测试文件。新增产物目录 `data/chanlun_history/`
（随 data 卷持久化，不入 git 跟踪）。不影响其它选股模块与调度框架。
