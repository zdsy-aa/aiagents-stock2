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
