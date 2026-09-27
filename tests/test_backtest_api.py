# -*- coding: utf-8 -*-
"""Task 4.3:run_backtest_api 统一回测接口 + gen_report HTML 报告。

- 测试一律传合成 df,不加载 15M 确认面板(控制器裁决);df=None 真面板路径
  (自动 load_confirm_panel + 按年切分)仅真实调用使用。
- gen_report 三种 kind(analysis/candidates/backtest)各断言关键内容与
  单文件内联 CSS 特征(双击可开,无外链)。
"""
import pandas as pd

import interfaces.backtest_api as ba
import interfaces.html_report as hr


def _synthetic_df():
    """合成面板:6 行,前 3 行 2024(训练)后 3 行 2025(测试),全行命中 TQ01。"""
    return pd.DataFrame({
        "极限抄底": [1] * 6, "主力参与": [1] * 6, "大盘空头": [1] * 6,
        "是否盈利": [1, 1, 0, 0, 1, 0], "区间涨跌幅": [0.2] * 6,
        "年": ["2024"] * 3 + ["2025"] * 3,
        "信号日期": ["20240101"] * 3 + ["20250101"] * 3,
        "股票代码": ["1"] * 6})


def test_run_backtest_api_by_name_synthetic():
    df = _synthetic_df()
    spec = {"name": "TQ01", "conds": [{"col": c, "op": ">", "value": 0}
            for c in ("极限抄底", "主力参与", "大盘空头")], "join": "AND"}
    r = ba.run_backtest_api(spec, df=df)
    assert "train" in r and "test" in r and r["train"]["n"] == 3


def test_run_backtest_api_by_name_lookup():
    # "TQ01" 经 build_57_specs 解析(Top50 组合串一致),合成 df 训练/测试各 3 行
    r = ba.run_backtest_api("TQ01", df=_synthetic_df())
    assert r["name"] == "TQ01"
    assert r["train"]["n"] == 3 and r["test"]["n"] == 3


def test_run_backtest_api_unknown_name_raises():
    try:
        ba.run_backtest_api("TQ99", df=_synthetic_df())
    except ValueError as e:
        assert "TQ99" in str(e)
    else:
        raise AssertionError("未知信号名应抛 ValueError")


def test_run_backtest_api_missing_col_wraps_runtime_error():
    spec = {"name": "X", "conds": [{"col": "不存在的列", "op": ">", "value": 0}]}
    try:
        ba.run_backtest_api(spec, df=_synthetic_df())
    except RuntimeError as e:
        assert "run_backtest_api" in str(e)  # R4-A:接口名入错误消息
    else:
        raise AssertionError("面板缺列应包装为 RuntimeError(R4-A)")


def test_gen_report_creates_html(tmp_path):
    p = hr.gen_report("backtest", {"title": "T", "rows": [{"信号": "TQ01", "训练胜率": "58.4%"}]}, out_dir=str(tmp_path))
    assert p.endswith(".html") and "TQ01" in open(p, encoding="utf-8").read()


def test_gen_report_three_kinds(tmp_path):
    analysis = {"symbol": "600000", "name": "浦发银行", "period": "日K",
                "generated_at": "2026-09-27 10:00:00", "current_state": "震荡",
                "trend": "横盘", "chip": "集中", "capital": "流入", "industry": "银行",
                "news": "无", "signals": ["S1"], "evidence": ["E1"],
                "scenarios": [{"name": "上涨", "trigger": "T1", "confirm": "C",
                               "target": "G", "invalidate": "I"},
                              {"name": "震荡", "trigger": "T2", "observe": "O",
                               "invalidate": "I2"},
                              {"name": "下跌", "trigger": "T3", "risk": "R",
                               "end": "E", "invalidate": "I3"}],
                "degraded": False, "degraded_reason": ""}
    pa = hr.gen_report("analysis", analysis, out_dir=str(tmp_path))
    text = open(pa, encoding="utf-8").read()
    assert "浦发银行" in text and "上涨" in text and "触发条件" in text

    pc = hr.gen_report("candidates", {"title": "候选", "rows": [
        {"代码": "600000", "名称": "浦发银行", "信号": "TQ01", "得分": "0.9", "备注": ""}]},
        out_dir=str(tmp_path))
    text_c = open(pc, encoding="utf-8").read()
    assert "浦发银行" in text_c and "TQ01" in text_c

    pb = hr.gen_report("backtest", {"title": "57信号回测", "rows": [
        {"信号": "TQ01", "训练胜率": "58.4%", "测试胜率": "60.1%",
         "训练支持": "100", "测试支持": "50", "平均收益": "+3.2%",
         "最大回撤": "12.3%", "连续亏损": "2", "盈亏比": "1.5",
         "过拟合标志": "否"}]}, out_dir=str(tmp_path))
    text_b = open(pb, encoding="utf-8").read()
    assert "TQ01" in text_b and "过拟合标志" in text_b


def test_gen_report_invalid_kind_raises(tmp_path):
    try:
        hr.gen_report("weekly", {"title": "x"}, out_dir=str(tmp_path))
    except ValueError:
        pass
    else:
        raise AssertionError("未知 kind 应抛 ValueError")


def test_gen_report_single_file_inline_css(tmp_path):
    p = hr.gen_report("candidates", {"rows": []}, out_dir=str(tmp_path))
    text = open(p, encoding="utf-8").read()
    assert "<style>" in text and "<html" in text  # 内联 CSS,单文件双击可开
