# 稳定选股邮件去明细 + 当天单文件分时段 sheet Excel 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 稳定选股邮件正文删掉全量明细表（明细只进 Excel），Excel 改为当天一个文件、盘中各时段 + 盘后各占一个 sheet，每封邮件附"当天累计完整文件"。

**Architecture:** 方案 A 无状态重建——每封邮件发送时从当天各时段 CSV（`data/profit_mining/watchlist_history/intraday/每日自选股清单_<日期>_<HHMM>.csv`，宿主/容器共享挂载）+ 盘后 latest 现拼多 sheet 工作簿，不依赖把 xlsx 落到共享盘。

**Tech Stack:** Python3、openpyxl 3.1.5、pytest 9（`tests/` 已有 conftest 把项目根加入 sys.path）。

设计依据：`docs/superpowers/specs/2026-06-12-stable-screening-mail-excel-sheets-design.md`

---

## 文件结构

- 改：`ops/export_watchlist_xlsx.py` —— 抽 `fill_sheet(ws,rows,slot_label)`，新增 `build_multi_sheet_workbook` / `build_xlsx_bytes_multi` / `collect_today_slots` / `resolve_data_paths`，`main()` 改产出多 sheet 累计文件 + 新文件名。
- 改：`ops/push_watchlist.py` —— `render_html` 删三档明细 section；附件改累计多 sheet；md/xlsx 附件改名 `每日稳定选股_<日期>`。
- 改：`ops/daily_watchlist_and_mail.sh`、`ops/intraday_watchlist_and_mail.sh` —— report 归档文件名同步去"清单"（仅命名，逻辑不动）。
- 新：`tests/test_watchlist_xlsx_sheets.py` —— 单测 `collect_today_slots` / `build_multi_sheet_workbook` / `resolve_data_paths` / `render_html` 去明细。

约束记忆点：**Excel sheet 名禁用 `\ / ? * [ ] :`**，时段 sheet 用全角冒号 `10：00`（U+FF1A），盘后 sheet 名 `盘后`。

---

## Task 1: export_watchlist_xlsx —— 抽 fill_sheet + 多 sheet + 当天收集

**Files:**
- Modify: `ops/export_watchlist_xlsx.py`
- Test: `tests/test_watchlist_xlsx_sheets.py`

- [ ] **Step 1: 写失败测试（多 sheet 构建 + 当天收集 + 路径推导）**

创建 `tests/test_watchlist_xlsx_sheets.py`：

```python
# -*- coding: utf-8 -*-
import os, sys, csv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "ops"))   # 便于 import ops 内脚本（其自身再 insert 同目录）
import export_watchlist_xlsx as XLS


def _write_csv(path, scan_date, codes):
    """写一份最小可读清单 CSV（含 read_rows / fill_sheet / render_html 用到的列）。"""
    cols = ["扫描日期", "股票代码", "股票名称", "精选", "星级", "可入状态", "优先级",
            "命中规则", "买点类型", "信号日期", "买入价", "扫描日价", "止损价", "止盈价",
            "预估胜率", "量比", "资金确认", "中枢底部", "获利盘%", "大盘环境", "板块"]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for c in codes:
            row = {k: "" for k in cols}
            row["扫描日期"] = scan_date
            row["股票代码"] = c
            row["股票名称"] = "测试股"
            row["命中规则"] = "A"
            w.writerow([row[k] for k in cols])


def test_collect_today_slots_orders_and_names(tmp_path):
    sd = "2026-06-12"
    intra = tmp_path / "intraday"; intra.mkdir()
    for hhmm in ("1100", "1000", "1430"):   # 故意乱序写入
        _write_csv(str(intra / f"每日自选股清单_{sd}_{hhmm}.csv"), sd, ["000001"])
    _write_csv(str(intra / "每日自选股清单_latest.csv"), sd, ["000002"])  # 应被忽略
    _write_csv(str(intra / f"每日自选股清单_2026-06-11_1000.csv"), "2026-06-11", ["000003"])  # 昨日，应被忽略
    slots = XLS.collect_today_slots(sd, include_eod=False,
                                    intraday_dir=str(intra), eod_csv=str(tmp_path / "none.csv"))
    assert [name for name, _ in slots] == ["10：00", "11：00", "14：30"]
    assert all(rows for _, rows in slots)


def test_collect_today_slots_eod_guard(tmp_path):
    sd = "2026-06-12"
    intra = tmp_path / "intraday"; intra.mkdir()
    _write_csv(str(intra / f"每日自选股清单_{sd}_1000.csv"), sd, ["000001"])
    eod = tmp_path / "每日自选股清单.csv"
    # 盘后扫描日期==今天 → 应并入
    _write_csv(str(eod), sd, ["000009"])
    slots = XLS.collect_today_slots(sd, include_eod=True,
                                    intraday_dir=str(intra), eod_csv=str(eod))
    assert [name for name, _ in slots] == ["10：00", "盘后"]
    # 盘后是昨日（刷新失败残留）→ 不并入
    _write_csv(str(eod), "2026-06-11", ["000009"])
    slots2 = XLS.collect_today_slots(sd, include_eod=True,
                                     intraday_dir=str(intra), eod_csv=str(eod))
    assert [name for name, _ in slots2] == ["10：00"]


def test_build_multi_sheet_workbook(tmp_path):
    sd = "2026-06-12"
    rows = [{"扫描日期": sd, "股票代码": "000001", "命中规则": "A", "精选": ""}]
    wb = XLS.build_multi_sheet_workbook([("10：00", rows), ("盘后", rows)])
    assert wb.sheetnames == ["10：00", "盘后"]   # 无默认空 Sheet
    ws = wb["10：00"]
    assert "时段 10：00" in str(ws.cell(row=1, column=1).value)   # 概览行带时段标签


def test_resolve_data_paths_profit_mining():
    intra, eod = XLS.resolve_data_paths(
        "/app/data/profit_mining/watchlist_history/intraday/每日自选股清单_latest.csv")
    assert intra == "/app/data/profit_mining/watchlist_history/intraday"
    assert eod == "/app/data/profit_mining/每日自选股清单.csv"
    intra2, eod2 = XLS.resolve_data_paths("/app/data/profit_mining/每日自选股清单.csv")
    assert intra2 == "/app/data/profit_mining/watchlist_history/intraday"
    assert eod2 == "/app/data/profit_mining/每日自选股清单.csv"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /home/tdxback/aiagents-stock && python3 -m pytest tests/test_watchlist_xlsx_sheets.py -v`
Expected: FAIL（`AttributeError: module 'export_watchlist_xlsx' has no attribute 'collect_today_slots'` 等）

- [ ] **Step 3: 重构 build_workbook → fill_sheet，并新增多 sheet/收集/路径函数**

在 `ops/export_watchlist_xlsx.py`，把现有 `build_workbook(rows)` 整体替换为下面这组函数（顶部 import 增加 `glob, re`）。

文件顶部 import 行 `import sys, io, os, datetime` 改为：

```python
import sys, io, os, re, glob, datetime
```

把 `def build_workbook(rows):` 到其 `return wb` 整段，替换为：

```python
def fill_sheet(ws, rows, slot_label=""):
    """把一段清单写入给定 worksheet ws。slot_label 非空时概览行带"时段 X"。"""
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    nA = sum(1 for r in rows if "A" in r.get("命中规则", ""))
    nB = sum(1 for r in rows if "B" in r.get("命中规则", ""))
    nCore = sum(1 for r in rows if r.get("精选") == "★★核心")
    nSel = sum(1 for r in rows if r.get("精选"))
    nZ = sum(1 for r in rows if r.get("资金确认"))
    nZS = sum(1 for r in rows if r.get("中枢底部"))
    scan = rows[0].get("扫描日期", "") if rows else ""
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    core = [r for r in rows if r.get("精选") == "★★核心"]
    sel = [r for r in rows if r.get("精选") == "★精选"]
    rest = [r for r in rows if not r.get("精选")]
    ordered = core + sel + rest
    ncol = len(SHOW)

    head_fill = PatternFill("solid", fgColor="C9A84A")
    head_font = Font(name="微软雅黑", bold=True, color="FFFFFF", size=11)
    core_fill = PatternFill("solid", fgColor="FFE9A8")
    sel_fill = PatternFill("solid", fgColor="FFF6D5")
    star_font = Font(name="微软雅黑", bold=True, color="B8860B")
    name_font = Font(name="微软雅黑", bold=True)
    base_font = Font(name="微软雅黑", size=10)
    loss_font = Font(name="微软雅黑", size=10, bold=True, color="C0392B")
    gain_font = Font(name="微软雅黑", size=10, bold=True, color="1E7E34")
    thin = Side(style="thin", color="E0D8C0")
    border = Border(bottom=thin)
    center = Alignment(horizontal="center", vertical="center")
    left = Alignment(horizontal="left", vertical="center")

    slot_prefix = f"时段 {slot_label}　" if slot_label else ""
    summary = (f"🛡️ 每日稳定选股　{slot_prefix}扫描日期 {scan}　共 {len(rows)} 只"
               f"（A抄底 {nA} / B抢筹 {nB}）　精选 {nSel}（★★核心 {nCore}）"
               f"　资金确认 {nZ}　中枢底部 {nZS}　|　生成 {now}")
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncol)
    c = ws.cell(row=1, column=1, value=summary)
    c.font = Font(name="微软雅黑", bold=True, color="4A3A1A", size=11)
    c.alignment = left
    c.fill = PatternFill("solid", fgColor="F6F1E4")
    ws.row_dimensions[1].height = 22

    for j, (_, title) in enumerate(SHOW, start=1):
        cell = ws.cell(row=2, column=j, value=title)
        cell.fill = head_fill
        cell.font = head_font
        cell.alignment = center

    for i, r in enumerate(ordered, start=3):
        tier = r.get("精选", "")
        fill = core_fill if tier == "★★核心" else (sel_fill if tier == "★精选" else None)
        for j, (col, _) in enumerate(SHOW, start=1):
            val = r.get(col, "")
            cell = ws.cell(row=i, column=j)
            if col in TEXT_COLS:
                cell.value = str(val)
                cell.number_format = "@"
            else:
                cell.value = val if val not in (None, "") else ""
            cell.border = border
            cell.alignment = left if col in ("股票名称", "板块") else center
            if fill:
                cell.fill = fill
            if col == "精选" and tier:
                cell.font = star_font
            elif col == "股票名称":
                cell.font = name_font
            elif col == "止损价":
                cell.font = loss_font
            elif col == "止盈价":
                cell.font = gain_font
            else:
                cell.font = base_font

    for j, (col, _) in enumerate(SHOW, start=1):
        ws.column_dimensions[get_column_letter(j)].width = WIDTHS.get(col, 10)

    ws.freeze_panes = "A3"
    ws.auto_filter.ref = f"A2:{get_column_letter(ncol)}{2 + len(ordered)}"
    return ws


def build_workbook(rows, slot_label=""):
    """单 sheet 工作簿（向后兼容）。"""
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "每日选股"
    fill_sheet(ws, rows, slot_label)
    return wb


def build_multi_sheet_workbook(slots):
    """slots=[(sheet名, rows), …] → 多 sheet 工作簿（删默认空 sheet）。"""
    from openpyxl import Workbook
    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in slots:
        ws = wb.create_sheet(title=name[:31])
        fill_sheet(ws, rows, name)
    return wb


def resolve_data_paths(csv_path):
    """从传入 csv 路径推导 (盘中时段目录, 盘后latest路径)，容器/宿主通用。"""
    p = os.path.abspath(csv_path)
    parts = p.split(os.sep)
    if "profit_mining" in parts:
        pm = os.sep.join(parts[:parts.index("profit_mining") + 1])
        return (os.path.join(pm, "watchlist_history", "intraday"),
                os.path.join(pm, "每日自选股清单.csv"))
    return (os.path.dirname(p), p)   # 兜底：未知结构（如测试自定义路径）


def collect_today_slots(scan_date, include_eod, intraday_dir, eod_csv):
    """汇集当天各时段(+可选盘后)清单 → [(sheet名, rows), …]，按时间升序。"""
    items = []
    pattern = os.path.join(intraday_dir, f"每日自选股清单_{scan_date}_*.csv")
    for path in glob.glob(pattern):
        m = re.search(r"_(\d{4})\.csv$", os.path.basename(path))
        if not m:
            continue
        hhmm = m.group(1)
        label = f"{hhmm[:2]}：{hhmm[2:]}"   # 全角冒号：Excel sheet 名禁用半角:
        items.append((hhmm, label, path))
    slots = []
    for _, label, path in sorted(items):
        rows = EXP.read_rows(path)
        if rows:
            slots.append((label, rows))
    if include_eod and os.path.exists(eod_csv):
        eod_rows = EXP.read_rows(eod_csv)
        if eod_rows and eod_rows[0].get("扫描日期") == scan_date:
            slots.append(("盘后", eod_rows))
    return slots
```

紧随其后的 `build_xlsx_bytes(rows)` 保留不动，并在其后新增：

```python
def build_xlsx_bytes_multi(slots):
    """多 sheet 工作簿 → .xlsx 二进制（供邮件附件）。"""
    wb = build_multi_sheet_workbook(slots)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /home/tdxback/aiagents-stock && python3 -m pytest tests/test_watchlist_xlsx_sheets.py -v`
Expected: PASS（4 个测试全过）

- [ ] **Step 5: 提交**

```bash
cd /home/tdxback/aiagents-stock
git add ops/export_watchlist_xlsx.py tests/test_watchlist_xlsx_sheets.py
git commit -m "feat(xlsx): 抽 fill_sheet + 多 sheet 工作簿 + 当天各时段收集"
```

---

## Task 2: export_watchlist_xlsx.main() 产出当天累计多 sheet 文件 + 新文件名

**Files:**
- Modify: `ops/export_watchlist_xlsx.py`（`main()`）

- [ ] **Step 1: 改 main() 用累计多 sheet 并改默认文件名**

把 `main()` 中从 `scan = rows[0].get("扫描日期", "")` 到 `wb.save(out)` 一段替换为：

```python
    scan = rows[0].get("扫描日期", "")
    intraday_dir, eod_csv = resolve_data_paths(csv_path)
    slots = collect_today_slots(scan, include_eod=True,
                                intraday_dir=intraday_dir, eod_csv=eod_csv)
    if not slots:
        slots = [("盘后", rows)]   # 兜底：当天无任何时段 CSV
    if out is None:
        out = os.path.join(os.path.dirname(csv_path), f"每日稳定选股_{scan}.xlsx")
    wb = build_multi_sheet_workbook(slots)
    wb.save(out)
```

`main()` 末尾的打印行保持不动（仍用 `rows`/`nSel`/`nCore` 报告盘后那批）。

- [ ] **Step 2: 冒烟验证（用真实当天数据，写临时文件）**

Run:
```bash
cd /home/tdxback/aiagents-stock && python3 ops/export_watchlist_xlsx.py \
  --csv data/profit_mining/每日自选股清单.csv --out /tmp/smoke_stable.xlsx \
  && python3 -c "import openpyxl;print(openpyxl.load_workbook('/tmp/smoke_stable.xlsx').sheetnames)"
```
Expected: 打印形如 `['10：00', '11：00', '13：30', '14：30', '盘后']`（取决于当天已存在的时段 CSV）。

- [ ] **Step 3: 提交**

```bash
cd /home/tdxback/aiagents-stock
git add ops/export_watchlist_xlsx.py
git commit -m "feat(xlsx): main 产出当天累计多 sheet 文件并改名 每日稳定选股_<日期>"
```

---

## Task 3: push_watchlist —— 正文删明细 + 附件改累计多 sheet + 改名

**Files:**
- Modify: `ops/push_watchlist.py`
- Test: `tests/test_watchlist_xlsx_sheets.py`（追加 render_html 去明细断言）

- [ ] **Step 1: 追加失败测试（正文不含三档明细表）**

在 `tests/test_watchlist_xlsx_sheets.py` 末尾追加：

```python
def test_render_html_drops_detail_tables():
    import importlib
    sys.path.insert(0, os.path.join(ROOT, "ops"))
    PW = importlib.import_module("push_watchlist")
    rows = [{"扫描日期": "2026-06-12", "股票代码": "000001", "股票名称": "测试股",
             "命中规则": "A", "精选": "★★核心"}]
    body, scan, n, nSel, nCore = PW.render_html(rows)
    assert "其余命中" not in body          # 三档明细 section 标题已移除
    assert "★★ 核心精选" not in body
    assert "选股逻辑" in body and "操作纪律" in body   # 摘要/逻辑/纪律仍在
    assert scan == "2026-06-12" and n == 1
```

- [ ] **Step 2: 运行确认失败**

Run: `cd /home/tdxback/aiagents-stock && python3 -m pytest tests/test_watchlist_xlsx_sheets.py::test_render_html_drops_detail_tables -v`
Expected: FAIL（`assert "其余命中" not in body` —— 当前正文含三档明细）

- [ ] **Step 3: render_html 删三档明细**

在 `ops/push_watchlist.py` `render_html` 内，删除 `section` 内嵌函数定义（`def section(...)` 整段）以及 `core`/`sel`/`rest` 三行列表推导，并把 `body = (...)` 整块替换为不含 section 的版本。

删除这三行：

```python
    core = [r for r in rows if r.get("精选") == "★★核心"]
    sel = [r for r in rows if r.get("精选") == "★精选"]
    rest = [r for r in rows if not r.get("精选")]
```

删除这段内嵌函数：

```python
    def section(title, sub, rs):
        if not rs:
            return ""
        return (f'<h3 style="margin:22px 0 8px;color:#4a3a1a;font-size:16px;">{title}'
                f'<span style="font-weight:400;color:#998;font-size:13px;"> {sub}</span></h3>'
                + _table(rs))
```

把 `body = (...)` 整块替换为：

```python
    body = (f'<div style="max-width:920px;margin:0 auto;padding:16px;color:#333;">'
            f'<h2 style="color:#3a2e15;border-bottom:2px solid #c9a84a;padding-bottom:8px;">'
            f'🛡️ 每日稳定选股清单</h2>'
            f'{summary}{logic}{discipline}{note}</div>')
    return body, scan, len(rows), nSel, nCore
```

注意：`_table` 函数与 `SHOW` 常量虽不再被正文调用，但保留不删（无害，避免牵动其它引用风险）。

- [ ] **Step 4: 运行确认通过**

Run: `cd /home/tdxback/aiagents-stock && python3 -m pytest tests/test_watchlist_xlsx_sheets.py -v`
Expected: PASS（5 个测试全过）

- [ ] **Step 5: 附件改累计多 sheet + 改文件名**

在 `ops/push_watchlist.py` `main()` 中，把构建 Excel 附件的这段：

```python
    xlsx_bytes = None                       # 附件:同内容 Excel 文档(openpyxl 缺失则降级跳过)
    try:
        xlsx_bytes = XLS.build_xlsx_bytes(rows)
    except Exception as e:
        print(f"⚠ 生成 Excel 附件失败(本次只附 md): {e}", file=sys.stderr)
```

替换为：

```python
    xlsx_bytes = None                       # 附件:当天累计多 sheet Excel(openpyxl 缺失则降级跳过)
    try:
        intraday_dir, eod_csv = XLS.resolve_data_paths(csv_path)
        slots = XLS.collect_today_slots(scan, include_eod=(slot is None),
                                        intraday_dir=intraday_dir, eod_csv=eod_csv)
        if not slots:                       # 兜底:当天暂无时段 CSV → 当前批单 sheet
            slots = [((slot.replace(":", "：") if slot else "盘后"), rows)]
        xlsx_bytes = XLS.build_xlsx_bytes_multi(slots)
    except Exception as e:
        print(f"⚠ 生成 Excel 附件失败(本次只附 md): {e}", file=sys.stderr)
```

再把两处附件文件名（md 与 xlsx）由 `每日稳定选股清单_` 改为 `每日稳定选股_`：

md 行：

```python
    att.add_header("Content-Disposition", "attachment",
                   filename=("utf-8", "", f"每日稳定选股_{scan}.md"))
```

xlsx 行：

```python
        xatt.add_header("Content-Disposition", "attachment",
                        filename=("utf-8", "", f"每日稳定选股_{scan}.xlsx"))
```

- [ ] **Step 6: 盘中态 --dry 冒烟（不发信，校验 sheet 数与附件名）**

Run:
```bash
cd /home/tdxback/aiagents-stock && python3 ops/push_watchlist.py \
  --csv data/profit_mining/watchlist_history/intraday/每日自选股清单_latest.csv \
  --slot 14:30 --dry --out /tmp/push_intraday.html
python3 -c "import re;h=open('/tmp/push_intraday.html',encoding='utf-8').read();print('其余命中' in h, '操作纪律' in h)"
```
Expected: `--dry` 行打印 `行数 …；附件md …字符，xlsx …字节`；末行打印 `False True`（正文无明细、有纪律）。

- [ ] **Step 7: 盘后态 --dry 冒烟（含盘后 sheet）**

Run:
```bash
cd /home/tdxback/aiagents-stock && python3 ops/push_watchlist.py --dry --out /tmp/push_eod.html \
  && echo "--- 校验附件多 sheet（重建到临时文件查看 sheetnames）---" \
  && python3 -c "
import sys; sys.path.insert(0,'ops')
import export_watchlist_md as E, export_watchlist_xlsx as X
rows=E.read_rows(E.DEFAULT_CSV); scan=rows[0]['扫描日期']
idir,eod=X.resolve_data_paths(E.DEFAULT_CSV)
slots=X.collect_today_slots(scan, True, idir, eod)
print([n for n,_ in slots])"
```
Expected: 打印当天 sheet 列表，末位为 `'盘后'`。

- [ ] **Step 8: 提交**

```bash
cd /home/tdxback/aiagents-stock
git add ops/push_watchlist.py tests/test_watchlist_xlsx_sheets.py
git commit -m "feat(mail): 正文删全量明细 + 附件改当天累计多 sheet + 改名 每日稳定选股_<日期>"
```

---

## Task 4: 同步两个 .sh 的 report 归档文件名

**Files:**
- Modify: `ops/daily_watchlist_and_mail.sh`

- [ ] **Step 1: 改盘后 sh 的归档文件名**

在 `ops/daily_watchlist_and_mail.sh` 第 20–23 行，把两处 `每日稳定选股清单_${TS}` 改为 `每日稳定选股_${TS}`：

```bash
python3 "$OPS/export_watchlist_md.py" --out "$REPORT/每日稳定选股_${TS}.md" \
  && echo "[$(date '+%F %T')] Markdown 已生成 $REPORT/每日稳定选股_${TS}.md"
python3 "$OPS/export_watchlist_xlsx.py" --out "$REPORT/每日稳定选股_${TS}.xlsx" \
  && echo "[$(date '+%F %T')] Excel 已生成 $REPORT/每日稳定选股_${TS}.xlsx"
```

（`intraday_watchlist_and_mail.sh` 不写 report 归档，无需改。）

- [ ] **Step 2: 语法检查**

Run: `bash -n ops/daily_watchlist_and_mail.sh && echo OK`
Expected: `OK`

- [ ] **Step 3: 提交**

```bash
cd /home/tdxback/aiagents-stock
git add ops/daily_watchlist_and_mail.sh
git commit -m "chore(ops): report 归档文件名同步 每日稳定选股_<日期>"
```

---

## Task 5: 全量回归

- [ ] **Step 1: 跑相关单测 + 不破坏既有测试**

Run: `cd /home/tdxback/aiagents-stock && python3 -m pytest tests/test_watchlist_xlsx_sheets.py -v`
Expected: 全部 PASS。

- [ ] **Step 2: 收尾**

确认 `git status` 干净、`git log --oneline -5` 含本次 4 个提交。
