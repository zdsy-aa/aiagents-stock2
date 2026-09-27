"""Task 3.1+3.2: 组合引擎与 57 信号规格(eval_combo / build_57_specs)。

3.2 勘误后:列存在性自检基座 = 确认面板(confirm_panel.npz 的 168 布尔 + 17 连续
+ 标签/日期列),Top50 组合串涉及的 33 个组合项全部存在 → 57 条 spec 全部可用
(3.1 时代基于 signal_features.csv 的 52 条 unavailable 已随基座切换消除);
TQ51 深跌承接 = OR 组,经嵌套 or_group 表达(控制器裁决)。
"""
import json
import pathlib

import pandas as pd
import pytest

from backtest.combo_engine import build_57_specs, eval_combo
from backtest.dataio import confirm_panel_columns

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


def test_or_group_any_true_within_and():
    """嵌套 OR 组:组内任一条件为真即组为真,顶层 AND 与其他条件求交。"""
    df = pd.DataFrame({"A": [1, 0, 1, 0],
                       "B": [0, 1, 0, 0],
                       "C": [0, 0, 0, 0],
                       "X": [1, 1, 0, 1]})
    spec = {"name": "T", "join": "AND", "conds": [
        {"col": "X", "op": ">", "value": 0},
        {"or_group": [{"col": "A", "op": ">", "value": 0},
                      {"col": "B", "op": ">", "value": 0},
                      {"col": "C", "op": ">", "value": 0}]}]}
    # 行0: X=1 且 A=1 -> True;行1: X=1 且 B=1 -> True;行2: X=0 -> False;
    # 行3: X=1 但 A/B/C 全 0 -> False
    assert eval_combo(spec, df).tolist() == [True, True, False, False]


def test_or_group_nested_or_group():
    """or_group 可递归嵌套(组内 OR 再含 OR 组)。"""
    df = pd.DataFrame({"A": [0, 0, 0, 1], "B": [0, 1, 0, 0], "C": [0, 0, 1, 0]})
    spec = {"name": "T", "join": "AND", "conds": [
        {"or_group": [{"col": "A", "op": ">", "value": 0},
                      {"or_group": [{"col": "B", "op": ">", "value": 0},
                                    {"col": "C", "op": ">", "value": 0}]}]}]}
    assert eval_combo(spec, df).tolist() == [False, True, True, True]


def test_or_group_empty_is_false():
    df = pd.DataFrame({"X": [1, 1]})
    spec = {"name": "T", "join": "AND", "conds": [
        {"col": "X", "op": ">", "value": 0},
        {"or_group": []}]}
    assert eval_combo(spec, df).tolist() == [False, False]


def test_or_group_missing_col_raises():
    spec = {"name": "T", "join": "AND", "conds": [
        {"or_group": [{"col": "A", "op": ">", "value": 0},
                      {"col": "不存在列", "op": ">", "value": 0}]}]}
    with pytest.raises(KeyError, match="不存在列"):
        eval_combo(spec, pd.DataFrame({"A": [1]}))


def test_tq51_or_group_structure_and_semantics():
    """TQ51 深跌承接 = 嵌套 or_group(大盘空头|趋势空头|资金强度大于10|机构净买),
    组内任一真即真(控制器裁决:修复 3.1 的 AND 扁平化)。"""
    specs = {s["name"]: s for s in build_57_specs()}
    spec = specs["TQ51"]
    assert not spec.get("unavailable")
    last = spec["conds"][-1]
    assert "or_group" in last
    arms = [c["col"] for c in last["or_group"]]
    assert arms == ["大盘空头", "趋势空头", "资金强度大于10", "机构净买"]
    # OR 语义:仅一臂为真即命中(其余顶层条件置真)
    df = pd.DataFrame({"六脉红灯大于6": [1, 1],
                       "缠论一买": [1, 1],
                       "缠论二买": [0, 0],
                       "20日跌幅超15": [1, 1],
                       "大盘空头": [1, 0],
                       "趋势空头": [0, 1],
                       "资金强度大于10": [0, 0],
                       "机构净买": [0, 0]})
    assert eval_combo(spec, df).tolist() == [True, True]
    # 承接组全 0 -> False
    df2 = df.copy()
    df2["趋势空头"] = [0, 0]
    assert eval_combo(spec, df2).tolist() == [True, False]


def test_all_57_available_on_confirm_panel():
    """确认面板基座(3.2 勘误):57 条 spec 全部可用,不再标 unavailable。"""
    specs = build_57_specs()
    assert not any(s.get("unavailable") for s in specs)
    assert {s["name"] for s in specs if not s.get("unavailable")} == {
        f"TQ{i:02d}" for i in range(1, 58)}
    cols = set(confirm_panel_columns())
    for s in specs:
        for cond in s["conds"]:
            for c in _iter_cols(cond):
                assert c in cols, (s["name"], c)


def _iter_cols(cond):
    if "or_group" in cond:
        for sub in cond["or_group"]:
            yield from _iter_cols(sub)
    else:
        yield cond["col"]


def test_available_spec_conds_exist_in_panel():
    cols = set(confirm_panel_columns())
    for s in build_57_specs():
        if s.get("unavailable"):
            continue
        for cond in s["conds"]:
            for c in _iter_cols(cond):
                assert c in cols, (s["name"], c)


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


def test_eval_combo_unavailable_returns_all_false():
    df = pd.DataFrame({"A": [1, 1, 1]})
    spec = {"name": "TQ01", "conds": [], "join": "AND", "unavailable": True,
            "reason": "面板缺列: 某列"}
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


def test_top1_spec_evals_on_synthetic_confirm_cols():
    """TQ01(极限抄底&主力参与&大盘空头)三列在确认面板均存在,合成面板上命中。"""
    df = pd.DataFrame({"极限抄底": [1, 0], "主力参与": [1, 1], "大盘空头": [1, 1]})
    spec = {"name": "TQ01", "raw": "极限抄底 AND 主力参与 AND 大盘空头",
            "join": "AND", "unavailable": False,
            "conds": [{"col": "极限抄底", "op": ">", "value": 0},
                      {"col": "主力参与", "op": ">", "value": 0},
                      {"col": "大盘空头", "op": ">", "value": 0}]}
    assert eval_combo(spec, df).tolist() == [True, False]
