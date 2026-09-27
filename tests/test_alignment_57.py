"""Task 3.2 对齐验收:57 信号在确认面板上的训练/测试胜率(涨跌占比)与支持数。

数据基座(控制器勘误):confirm_panel.npz(v1)——Top50 JSON 的胜率/支持挖掘底座
(mine_confirm.py,2026-09-03 构建,15,115,796 行),支持数可与 JSON 完全一致;
3.0 的 load_panel(signal_features.csv 买点事件面板)缺 14 个组合项列,不用于对齐。

TQ51~TQ57:文件头涨跌占比(测试段 上涨% / 下跌% 与支持)挖掘自
confirm_panel_v2.npz(mine_combo11.py,2026-09-08 构建;v2 的 Y 多含 y_dn 下跌标签,
v1 只有 y_up/ext_up,下跌占比在 v1 上不可计算),故该段对齐用 v2,并用 v1 交叉验证
(上涨率 + 支持)。文件头只有测试段占比 → 训练段跳过。

容差(控制器裁决):胜率/占比 ±0.3pp;支持完全一致(1~50 对 JSON;51~57 对
文件头/信号说明的 n,其 n 实测 = mine_combo11 净方向重排表「支持」列 = 全期支持)。
unavailable 判定:按 spec.get("unavailable") 跳过并记账(不计 fails)。
确属口径差异的信号显式标 expected_deviation,跳过断言并记账(见
test_tq51_57_v1_cross_check 与 EXPECTED_DEVIATIONS)。
"""
import json
import pathlib

import pandas as pd

from backtest.combo_engine import build_57_specs, eval_combo
from backtest.dataio import (DOWN_LABEL_COL, load_confirm_panel,
                             split_train_test)
from backtest.engine import run_backtest

TOP50 = json.loads(
    (pathlib.Path("/home/tdxback/aiagents-stock/data/commonality_reports/"
                  "确认信号_Top50去重_20260908.json")).read_text(encoding="utf-8"))

WIN_TOL = 0.003  # ±0.3pp

# TQ51~TQ57 文件头基准(tq_confirm_top10.py 头部注释;n 取 六脉缠论_信号说明 的
# n= 标注,实测 = 挖掘报告「净方向重排」表支持列 = 训练+测试全期支持)。
# TQ51 文件头为「大盘空头+20日跌幅超15」子口径(承接 OR 组的单臂),n=570 取
# 挖掘报告该行支持。
REFS_51_57 = {
    "TQ51": {"up": 0.647, "dn": 0.111, "n": 570,
             "note": "子口径:大盘空头+20日跌幅超15(文件头口径)"},
    "TQ52": {"up": 0.488, "dn": 0.748, "n": 835},
    "TQ53": {"up": 0.246, "dn": 0.441, "n": 955},
    "TQ54": {"up": 0.263, "dn": 0.431, "n": 1052},
    "TQ55": {"up": 0.349, "dn": 0.515, "n": 684},
    "TQ56": {"up": 0.470, "dn": 0.626, "n": 549},
    "TQ57": {"up": 0.407, "dn": 0.556, "n": 624},
}

# v1 交叉验证的已知口径差异:文件头基准挖掘自 v2(多 2026-09-03~07 五个交易日),
# v1 缺这些行 → 测试段支持少 1~4 行、上涨率差 0.5~0.7pp(超 ±0.3pp 容差)。
# 与 Top50(挖掘自 v1)无关;非口径可修项,显式标 expected_deviation 跳过断言。
EXPECTED_DEVIATIONS = {
    "TQ53": "v1 缺 v2 的 2026-09-03~07 行(v2 基准测试支持 118, v1 116)",
    "TQ54": "v1 缺 v2 的 2026-09-03~07 行(v2 基准测试支持 137, v1 133)",
    "TQ55": "v1 缺 v2 的 2026-09-03~07 行(v2 基准测试支持 103, v1 102)",
}


def _tq51_subspec(spec51):
    """TQ51 子口径 spec(文件头口径):组合11 & 20日跌幅超15 & 大盘空头。

    即把 TQ51 承接 OR 组(大盘空头|趋势空头|资金强度大于10|机构净买,末位元素)
    替换为其「大盘空头」单臂。完整 OR 组 spec 无文件头基准,由
    test_combo_engine::test_tq51_or_group 与 test_tq51_57_alignment 内断言
    (全组支持 >= 子口径支持)覆盖。
    """
    conds = [dict(c) for c in spec51["conds"]]
    assert "or_group" in conds[-1], "TQ51 末位条件应为承接 OR 组"
    conds[-1] = {"col": "大盘空头", "op": ">", "value": 0}
    return {"name": "TQ51(子口径:大盘空头+20日跌幅超15)", "join": "AND",
            "unavailable": False, "conds": conds}


def _record(skipped, name, reason):
    skipped.append((name, reason))


def test_top50_alignment():
    """1~50:run_backtest 在 confirm_panel(v1) 训练/测试两段的胜率与支持
    对比 Top50 JSON(±0.3pp / 完全一致);不一致逐条打印差异表并 FAIL。"""
    df = load_confirm_panel()
    tr, te = split_train_test(df)
    specs = {s["name"]: s for s in build_57_specs()}
    fails, skipped = [], []
    for item in TOP50:
        name = "TQ%02d" % item["排名"]
        spec = specs.get(name)
        if spec is None or spec.get("unavailable"):
            _record(skipped, name, "spec unavailable")
            continue
        r_tr = run_backtest(spec, tr)
        r_te = run_backtest(spec, te)
        if r_tr["n"] != item["训练支持"] or r_te["n"] != item["测试支持"]:
            fails.append((name, f"support {r_tr['n']}/{r_te['n']} vs "
                                f"{item['训练支持']}/{item['测试支持']}"))
        if (abs(r_tr["win_rate"] - item["训练胜率"]) > WIN_TOL
                or abs(r_te["win_rate"] - item["测试胜率"]) > WIN_TOL):
            fails.append((name, f"win_rate {r_tr['win_rate']:.4f}/{r_te['win_rate']:.4f}"
                                f" vs {item['训练胜率']:.4f}/{item['测试胜率']:.4f}"))
    print(f"\n[alignment] Top50: {len(TOP50)} 条,失败 {len(fails)},跳过 {len(skipped)}")
    for row in fails:
        print("  FAIL", row)
    for row in skipped:
        print("  SKIP", row)
    assert not fails, fails


def _dn_rate(spec, te):
    """测试段下跌率 = 命中行中 是否下跌(y_dn)==1 的占比(v2 面板列)。"""
    mask = eval_combo(spec, te)
    dn = pd.to_numeric(te.loc[mask, DOWN_LABEL_COL], errors="coerce")
    dn_v = dn.dropna()
    if len(dn_v) == 0:
        return 0.0
    return float((dn_v == 1).mean())


def test_tq51_57_alignment():
    """51~57:v2 面板上对照文件头涨跌占比(测试段 上涨%/下跌% ±0.3pp)与
    支持(完全一致);训练段跳过(文件头只有测试段占比)。"""
    df = load_confirm_panel(v2=True)
    te = split_train_test(df)[1]
    specs = {s["name"]: s for s in build_57_specs()}
    fails, skipped = [], []
    for name, ref in REFS_51_57.items():
        spec = specs[name] if name != "TQ51" else _tq51_subspec(specs["TQ51"])
        if spec.get("unavailable"):
            _record(skipped, name, f"spec unavailable: {spec.get('reason')}")
            continue
        r_full = run_backtest(spec, df)
        r_te = run_backtest(spec, te)
        dn = _dn_rate(spec, te)
        if r_full["n"] != ref["n"]:
            fails.append((name, f"support {r_full['n']} vs {ref['n']}"))
        if abs(r_te["win_rate"] - ref["up"]) > WIN_TOL:
            fails.append((name, f"上涨率 {r_te['win_rate']:.4f} vs {ref['up']:.4f}"))
        if abs(dn - ref["dn"]) > WIN_TOL:
            fails.append((name, f"下跌率 {dn:.4f} vs {ref['dn']:.4f}"))
    # TQ51 完整 OR 组 spec 可用且支持 >= 子口径(承接组任一臂命中即计数)
    full51 = specs["TQ51"]
    r_full51 = run_backtest(full51, df)
    r_sub51 = run_backtest(_tq51_subspec(full51), df)
    assert r_full51["n"] > 0 and r_full51["n"] >= r_sub51["n"]
    print(f"\n[alignment] TQ51~57(v2): 7 条,失败 {len(fails)},跳过 {len(skipped)}")
    for row in fails:
        print("  FAIL", row)
    for row in skipped:
        print("  SKIP", row)
    assert not fails, fails


def test_tq51_57_v1_cross_check():
    """51~57 在 v1(控制器指定基座)上的上涨率 + 支持交叉验证。

    v1 与 v2 行集差异:上涨率/支持与文件头基准对比;下跌率 v1 无 y_dn 标签,
    不可计算(见模块 docstring)。EXPECTED_DEVIATIONS 内的信号显式跳过断言。
    """
    df = load_confirm_panel()
    tr, te = split_train_test(df)
    specs = {s["name"]: s for s in build_57_specs()}
    fails, skipped, dev = [], [], []
    for name, ref in REFS_51_57.items():
        spec = specs[name] if name != "TQ51" else _tq51_subspec(specs["TQ51"])
        r_tr = run_backtest(spec, tr)
        r_te = run_backtest(spec, te)
        n_full = r_tr["n"] + r_te["n"]
        if name in EXPECTED_DEVIATIONS:
            dev.append((name, f"expected_deviation: {EXPECTED_DEVIATIONS[name]}"
                              f"(v1 up {r_te['win_rate']*100:.1f}%/{n_full}"
                              f" vs 基准 {ref['up']*100:.1f}%/{ref['n']})"))
            continue
        if n_full != ref["n"]:
            fails.append((name, f"support {n_full} vs {ref['n']}"))
        if abs(r_te["win_rate"] - ref["up"]) > WIN_TOL:
            fails.append((name, f"上涨率 {r_te['win_rate']:.4f} vs {ref['up']:.4f}"))
    print(f"\n[alignment] TQ51~57(v1 交叉验证): 失败 {len(fails)},"
          f"expected_deviation {len(dev)},跳过 {len(skipped)}")
    for row in fails:
        print("  FAIL", row)
    for row in dev:
        print("  DEV ", row)
    assert not fails, fails
