"""Task 3.1: 组合引擎与 57 信号规格(eval_combo / build_57_specs)。

面板实测(load_panel = signal_features.csv + turnover_signal.csv,97,329 行 × 99 列):
Top50 组合串涉及的 33 个不同组合项中有 14 个缺列(主力参与/威科夫B4强势杆/波动率大于5/
量比大于1_5/RSI24低于40/RSI12低于30/RSI6低于20/距60日高点深跌/20日跌幅超15/资金金叉/
做多权重大于1/资金强度大于10/资金强度大于20/KDJ18_3_3低位金叉),对应 spec 标
unavailable(conds 置空 + reason),eval_combo 返回全 False;当前面板可用信号为
TQ15/TQ22/TQ47/TQ50/TQ56。缺列明细与列名映射表见 task-3.1-report.md。
"""
import json
import pathlib

import pandas as pd
import pytest

from backtest.combo_engine import build_57_specs, eval_combo
from backtest.dataio import load_panel

TOP50_PATH = ("/home/tdxback/aiagents-stock/data/commonality_reports/"
              "确认信号_Top50去重_20260908.json")


def test_eval_combo_and():
    df = pd.DataFrame({"A": [1, 0, 1], "B": [1, 1, 0]})
    spec = {"name": "T", "conds": [{"col": "A", "op": ">", "value": 0},
                                    {"col": "B", "op": ">", "value": 0}], "join": "AND"}
    assert eval_combo(spec, df).tolist() == [True, False, False]


def test_eval_combo_missing_col_raises():
    spec = {"name": "T", "conds": [{"col": "不存在列", "op": ">", "value": 0}], "join": "AND"}
    with pytest.raises(KeyError, match="不存在列"):
        eval_combo(spec, pd.DataFrame({"A": [1]}))


def test_build_57_specs_counts():
    specs = build_57_specs()
    assert len(specs) == 57
    names = [s["name"] for s in specs]
    assert "TQ01" in names and "TQ57" in names


def test_top1_spec_evals_on_panel():
    df = load_panel()
    specs = {s["name"]: s for s in build_57_specs()}
    spec = specs["TQ01"]
    if spec.get("unavailable"):
        # 面板缺列(主力参与)时标 unavailable:eval_combo 返回全 False,与对齐测试跳过逻辑配合
        mask = eval_combo(spec, df)
        assert mask.dtype == bool and len(mask) == len(df) and mask.sum() == 0
        pytest.skip(f"TQ01 面板缺列标 unavailable: {spec['reason']}")
    mask = eval_combo(spec, df)
    assert mask.sum() > 0 and mask.dtype == bool


def test_first_available_spec_evals_on_panel():
    """当前面板第一个可用 Top50 信号(TQ15)必须在真实面板上命中 > 0 行。"""
    df = load_panel()
    avail = [s for s in build_57_specs() if not s.get("unavailable")]
    assert avail, "至少应有一个可用信号"
    assert avail[0]["name"] == "TQ15"
    mask = eval_combo(avail[0], df)
    assert mask.sum() > 0 and mask.dtype == bool


def test_available_set_matches_panel_reality():
    """钉住当前面板(数据基座 3.0)的可用/不可用边界,面板增列时须同步更新。"""
    specs = build_57_specs()
    avail = {s["name"] for s in specs if not s.get("unavailable")}
    assert avail == {"TQ15", "TQ22", "TQ47", "TQ50", "TQ56"}
    for s in specs:
        if s.get("unavailable"):
            assert s["conds"] == []
            assert s["reason"] and s["missing_cols"]


def test_eval_combo_unavailable_returns_all_false():
    df = pd.DataFrame({"A": [1, 1, 1]})
    spec = {"name": "TQ01", "conds": [], "join": "AND", "unavailable": True,
            "reason": "面板缺列: 主力参与"}
    m = eval_combo(spec, df)
    assert m.dtype == bool and len(m) == len(df) and not m.any()


def test_eval_combo_or_and_ops():
    df = pd.DataFrame({"A": [1, 0, 1], "B": [1, 1, 0]})
    or_spec = {"name": "T", "conds": [{"col": "A", "op": ">", "value": 0},
                                      {"col": "B", "op": ">", "value": 0}], "join": "OR"}
    assert eval_combo(or_spec, df).tolist() == [True, True, True]
    ge = {"name": "T", "conds": [{"col": "A", "op": ">=", "value": 1}], "join": "AND"}
    assert eval_combo(ge, df).tolist() == [True, False, True]
    lt = {"name": "T", "conds": [{"col": "A", "op": "<", "value": 1}], "join": "AND"}
    assert eval_combo(lt, df).tolist() == [False, True, False]
    le = {"name": "T", "conds": [{"col": "A", "op": "<=", "value": 0}], "join": "AND"}
    assert eval_combo(le, df).tolist() == [False, True, False]
    eq = {"name": "T", "conds": [{"col": "A", "op": "==", "value": 1}], "join": "AND"}
    assert eval_combo(eq, df).tolist() == [True, False, True]


def test_eval_combo_coerces_non_numeric_to_zero():
    df = pd.DataFrame({"A": ["x", 0, 1.5]})
    spec = {"name": "T", "conds": [{"col": "A", "op": ">", "value": 0}], "join": "AND"}
    assert eval_combo(spec, df).tolist() == [False, False, True]


def test_available_spec_conds_exist_in_panel():
    df = load_panel()
    for s in build_57_specs():
        if s.get("unavailable"):
            continue
        for c in s["conds"]:
            assert c["col"] in df.columns, (s["name"], c["col"])


def test_spec_names_and_raw_match_json():
    top50 = json.loads(pathlib.Path(TOP50_PATH).read_text(encoding="utf-8"))
    assert len(top50) == 50
    specs = {s["name"]: s for s in build_57_specs()}
    for item in top50:
        s = specs["TQ%02d" % item["排名"]]
        assert s["raw"] == item["组合"]
    # 51~57 手工映射:名称与形态标注
    labels = {"TQ51": "六脉缠论买:深跌+空头/资金承接",
              "TQ52": "六脉缠论卖:大盘多头+波动率大于5",
              "TQ53": "六脉缠论卖:MA金叉10_20+量比大于1_5",
              "TQ54": "六脉缠论卖:BOLL开口扩张+MA金叉10_20",
              "TQ55": "六脉缠论卖:多头排列+阳包阴",
              "TQ56": "六脉缠论卖:斐波全多头+量比大于1",
              "TQ57": "六脉缠论卖:斐波短中多头+20日新高"}
    for name, label in labels.items():
        assert specs[name]["raw"] == label
