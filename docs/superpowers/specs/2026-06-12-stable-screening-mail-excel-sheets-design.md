# 稳定选股邮件改造：正文去明细 + 当天单文件分时段 sheet Excel

日期：2026-06-12
状态：已批准设计（待写实现计划）
涉及文件：`ops/push_watchlist.py`、`ops/export_watchlist_xlsx.py`

## 背景与现状

稳定选股每天发 5 封邮件：盘中 4 封（10:00 / 11:00 / 13:30 / 14:30，容器内 `docker exec` 跑）+ 盘后 1 封（21:00，宿主跑）。

现状问题：每封邮件正文都**内嵌完整三档明细表**（核心/精选/其余），且每封各自附一个**单 sheet、每次新建**的 `每日稳定选股清单_<日期>.xlsx`。用户希望：

- 邮件正文**不再贴全量明细表**，明细只进 Excel。
- Excel **一天一个文件**，文件名 `每日稳定选股_<日期>.xlsx`，**按时间点分 sheet**（各盘中时段 + 盘后），同一天累积在一个文件里。

## 关键事实（已核实）

- `data/` 在宿主与容器间共享挂载（`/home/tdxback/aiagents-stock/data` ↔ `/app/data`）。
- 盘中各时段 CSV 已天然累积：`data/profit_mining/watchlist_history/intraday/每日自选股清单_<日期>_<HHMM>.csv`，宿主与容器都可读。
- 盘后 latest：`data/profit_mining/每日自选股清单.csv`（其「扫描日期」字段为当前交易日）。
- `/home/tdxback/report` **未挂进容器**（故不能作为跨容器/宿主共享落盘点）。

## 方案

**方案 A（采用）：无状态重建。** 每封邮件发送时，从当天各时段 CSV 现拼一个多 sheet 工作簿。"累积"的真实来源是已天然累积的 per-slot CSV，无需把 xlsx 落到共享盘，也无需 openpyxl 增量追加，彻底绕开跨容器持久化。

方案 B（弃用）：xlsx 落共享盘 + 每时段 load→加/替 sheet→save。有状态，需处理并发/坏档/跨天清理，复杂度高、无收益。

## 已确认的产品决策

1. **正文范围**：保留 **顶部摘要 + 选股逻辑 + 操作纪律**（+ 盘中那封的红色"临时态"免责声明）。删除三档全量明细表（核心/精选/其余 `section`）。
2. **盘中"本时段新增/变动"小列表（🆕/⤴ 几只股）**：**保留**（这是盘中邮件看点，非全量明细）。
3. **md 附件**：保留（md + xlsx 都发）。md 仍为**当前时段单文档**（不做多 sheet 概念），随文件名改名。
4. **附件累积**：每封邮件附带的当天 Excel = **当天累计完整文件**（含此前所有时段 sheet；如 14:30 那封含 10:00/11:00/13:30/14:30）。
5. **盘后并入**：盘后（21:00）作为当天**同一文件**的一个 sheet（名 `盘后`）。

## 设计细节

### `export_watchlist_xlsx.py`

- 抽出 `fill_sheet(ws, rows, slot_label)`：把现 `build_workbook` 写单表的全部逻辑（概览合并行 + 表头 + 三档排序 + 高亮 + 列宽 + 冻结 + AutoFilter）改为写入**给定的 worksheet**；概览摘要文案带上 `slot_label`（如 `时段 10：00` / `盘后`）。
- 新增 `build_multi_sheet_workbook(slots)`：`slots = [(sheet名, rows), …]`，按时间顺序建多个 sheet，逐个调 `fill_sheet`。删除默认空 sheet。
- 新增 `collect_today_slots(scan_date, include_eod, intraday_dir, eod_csv)`：
  - glob `intraday/每日自选股清单_<scan_date>_*.csv`，逐个 `EXP.read_rows`；从文件名解析 `HHMM` → 显示名 `HH：00`（**全角冒号 U+FF1A**，因 Excel sheet 名禁用半角 `:`）。
  - 按 HHMM 升序排列。
  - `include_eod=True` 时，读 `eod_csv`（盘后 latest）；**仅当其「扫描日期」== scan_date** 才作为 `盘后` sheet 追加到末尾（防止盘中阶段把昨日盘后误并入）。
  - 返回 `[(sheet名, rows), …]`。
- `build_xlsx_bytes(rows)` 保持签名兼容（旧单段调用回退为单 sheet）；新增 `build_xlsx_bytes_multi(slots)` 供 push 调用。

Sheet 命名规则：盘中 `HH：00`（全角冒号），盘后 `盘后`。Excel sheet 名禁用字符 `\ / ? * [ ] :`，全角冒号合法。

### `push_watchlist.py`

- `render_html`：移除三档明细 `section(核心/精选/其余)` 的拼接，仅保留 `summary + logic + discipline + note`。返回值不变。
- 盘中分支（有 `slot`）：保留 `disclaimer` + "本时段新增/变动"`banner`，二者置于 `body` 顶部（现状逻辑不动）。
- 附件 Excel：改为调用 `collect_today_slots` 拼当天累计工作簿：
  - `scan_date` 取 `rows[0]["扫描日期"]`。
  - `include_eod = (slot is None)`（盘后无 slot）。
  - 失败降级：异常时回退当前 `rows` 单 sheet（保证有附件），打印告警，不影响发信。
- 附件文件名：
  - Excel：`每日稳定选股_<scan>.xlsx`（去掉"清单"二字）。
  - md：`每日稳定选股_<scan>.md`（同步改名；内容仍为当前时段单文档）。
- 主题不变。

### 路径常量

- `INTRADAY_DIR = data/profit_mining/watchlist_history/intraday`（容器 `/app/...`，宿主 `/home/tdxback/aiagents-stock/...`，经 `ENV_PATH` 同款"宿主优先、容器回退"探测拼出）。
- `EOD_CSV = DEFAULT_CSV`（盘后 latest）。

## 边界与降级

- 某时段 CSV 缺失：跳过该 sheet（glob 自然不含）。
- 当天尚无任何时段 CSV（异常）：`collect_today_slots` 返回空 → 回退当前 `rows` 单 sheet。
- 盘后 latest 仍是昨日（盘后刷新失败）：扫描日期 != scan_date → 不并入盘后 sheet（盘中阶段本就不并）。
- 跨天残留的旧时段 CSV：glob 用精确 `scan_date` 过滤，天然隔离。
- openpyxl 缺失：沿用现有 try/except，只附 md。

## 测试要点

- `collect_today_slots`：构造多个 `_<sd>_HHMM.csv` → 返回按时间排序、命名正确、含/不含盘后符合 `include_eod` 与扫描日期守卫。
- `build_multi_sheet_workbook`：sheet 名集合、顺序、无多余空 sheet、每 sheet 概览行带时段标签。
- `render_html`：输出不含三档明细表（无"核心精选/精选/其余命中"section 表），仍含摘要/逻辑/纪律。
- push `--dry`：正确报告 sheet 数与附件名；盘中（带 `--slot`）正文含 disclaimer+banner，盘后（无 slot）含盘后 sheet。
- 沿用项目 AppTest/无头方式不涉及（纯脚本，命令行 `--dry` 验证 + 单测）。
