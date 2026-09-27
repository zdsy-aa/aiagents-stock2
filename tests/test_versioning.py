"""Task 3.5: 策略版本管理与回测报告(versioning / report)。

- versioning: bump_version / param_history 的 JSON 读写全部 monkeypatch
  VERSIONS_PATH 到 tmp_path,绝不写真实 backtest/strategy_versions.json。
- report: gen_report 单策略路径与 gen_report_57 整表渲染路径均用合成面板
  验证(monkeypatch build_57_specs + 传入合成 df),不跑真面板(控制器裁决:
  报告生成只跑一次,真面板实测在提交前手工执行)。
"""
import json
import pathlib

import pandas as pd
import pytest

import backtest.report as rep
import backtest.versioning as ver


def test_bump_version_and_history(tmp_path, monkeypatch):
    """简报 Step 1 测试:版本号 V+1 推进,param_history 按参数变更顺序返回。"""
    monkeypatch.setattr(ver, "VERSIONS_PATH", tmp_path / "strategy_versions.json")
    v1 = ver.bump_version("TQ01", {"阈值": 0}, {"win_rate": 0.58})
    v2 = ver.bump_version("TQ01", {"阈值": 0.5}, {"win_rate": 0.59})
    assert (v1, v2) == ("V1", "V2")
    hist = ver.param_history("TQ01")
    assert [h["params"] for h in hist] == [{"阈值": 0}, {"阈值": 0.5}]


def test_bump_version_preserves_other_strategies(tmp_path, monkeypatch):
    """读-改-写:新策略 bump 不清掉已有策略条目,params 与 backtest 绑定。"""
    monkeypatch.setattr(ver, "VERSIONS_PATH", tmp_path / "strategy_versions.json")
    ver.bump_version("TQ01", {"a": 1}, {"win_rate": 0.5})
    ver.bump_version("TQ02", {"b": 2}, {"win_rate": 0.6})
    data = json.loads((tmp_path / "strategy_versions.json").read_text(encoding="utf-8"))
    assert set(data) == {"TQ01", "TQ02"}
    assert len(data["TQ01"]["versions"]) == 1
    assert data["TQ02"]["versions"][0]["version"] == "V1"
    assert data["TQ02"]["versions"][0]["params"] == {"b": 2}
    assert data["TQ02"]["versions"][0]["backtest"] == {"win_rate": 0.6}
    assert "created_at" in data["TQ02"]["versions"][0]


def test_param_history_empty(tmp_path, monkeypatch):
    """无记录策略:返回空列表,不创建文件。"""
    p = tmp_path / "strategy_versions.json"
    monkeypatch.setattr(ver, "VERSIONS_PATH", p)
    assert ver.param_history("NOPE") == []
    assert not p.exists()


def test_bump_version_nonfinite_backtest_values(tmp_path, monkeypatch):
    """引擎 12 键可能含 inf/nan:落盘转 None(JSON 安全),不抛错。"""
    monkeypatch.setattr(ver, "VERSIONS_PATH", tmp_path / "strategy_versions.json")
    ver.bump_version("TQ01", {"阈值": 0.5},
                     {"win_rate": 0.5, "profit_loss_ratio": float("inf"),
                      "ret_std": float("nan")})
    hist = ver.param_history("TQ01")
    assert hist[0]["backtest"]["profit_loss_ratio"] is None
    assert hist[0]["backtest"]["ret_std"] is None


def test_corrupted_versions_file_raises(tmp_path, monkeypatch):
    """损坏 JSON:load 抛 RuntimeError(消息含路径)且文件内容不变。"""
    p = tmp_path / "strategy_versions.json"
    p.write_text("{ not valid json", encoding="utf-8")
    monkeypatch.setattr(ver, "VERSIONS_PATH", p)
    with pytest.raises(RuntimeError, match="strategy_versions.json"):
        ver.param_history("TQ01")
    assert p.read_text(encoding="utf-8") == "{ not valid json"


def test_non_dict_versions_file_raises(tmp_path, monkeypatch):
    """顶层非 dict(合法 JSON):同样抛 RuntimeError,不静默当 {}。"""
    p = tmp_path / "strategy_versions.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    monkeypatch.setattr(ver, "VERSIONS_PATH", p)
    with pytest.raises(RuntimeError, match="strategy_versions.json"):
        ver.bump_version("TQ01", {"a": 1}, {"win_rate": 0.5})
    assert p.read_text(encoding="utf-8") == "[1, 2, 3]"


def test_bump_version_preserves_corrupted_file(tmp_path, monkeypatch):
    """损坏时 bump 不覆盖:抛 RuntimeError,原文件内容不变。"""
    p = tmp_path / "strategy_versions.json"
    p.write_text("{ corrupted", encoding="utf-8")
    monkeypatch.setattr(ver, "VERSIONS_PATH", p)
    with pytest.raises(RuntimeError, match="strategy_versions.json"):
        ver.bump_version("TQ01", {"a": 1}, {"win_rate": 0.5})
    assert p.read_text(encoding="utf-8") == "{ corrupted"


def test_bump_version_atomic_on_write_failure(tmp_path, monkeypatch):
    """写盘中断(模拟磁盘满):原文件保持完整合法 JSON(先写 tmp 再 replace)。"""
    p = tmp_path / "strategy_versions.json"
    monkeypatch.setattr(ver, "VERSIONS_PATH", p)
    ver.bump_version("TQ01", {"a": 1}, {"win_rate": 0.5})
    before = p.read_text(encoding="utf-8")

    def boom(*args, **kwargs):
        raise OSError("disk full")
    monkeypatch.setattr(ver.json, "dump", boom)
    with pytest.raises(OSError, match="disk full"):
        ver.bump_version("TQ01", {"a": 2}, {"win_rate": 0.6})
    # 原文件未被破坏,仍是合法 JSON 且历史完整
    assert p.read_text(encoding="utf-8") == before
    data = json.loads(before)
    assert [v["params"] for v in data["TQ01"]["versions"]] == [{"a": 1}]


def test_bump_version_valid_json_no_tmp_leftover(tmp_path, monkeypatch):
    """正常 bump 后:文件为合法 JSON、历史完整、无 tmp 残留。"""
    p = tmp_path / "strategy_versions.json"
    monkeypatch.setattr(ver, "VERSIONS_PATH", p)
    ver.bump_version("TQ01", {"a": 1}, {"win_rate": 0.5})
    ver.bump_version("TQ01", {"a": 2}, {"win_rate": 0.6})
    assert not (tmp_path / ".strategy_versions.json.tmp").exists()
    data = json.loads(p.read_text(encoding="utf-8"))
    assert [v["params"] for v in data["TQ01"]["versions"]] == [{"a": 1}, {"a": 2}]
    assert [v["version"] for v in data["TQ01"]["versions"]] == ["V1", "V2"]


# ---------------------------------------------------------------------------
# report 合成面板测试(不跑真面板)
# ---------------------------------------------------------------------------

def _synthetic_df():
    """8 行合成面板:4 行训练(2024)+ 4 行测试(2025),A/B 全 1,C 选择性命中。"""
    return pd.DataFrame({
        "股票代码": ["1"] * 8,
        "信号日期": [20240101, 20240102, 20240103, 20240104,
                     20250101, 20250102, 20250103, 20250104],
        "是否盈利": [1, 1, 0, 0, 1, 0, 1, 0],
        "区间涨跌幅": [0.10, 0.12, -0.05, -0.10, 0.15, -0.08, 0.20, -0.15],
        "年": [2024, 2024, 2024, 2024, 2025, 2025, 2025, 2025],
        "A": [1] * 8,
        "B": [1] * 8,
        "C": [1, 1, 0, 0, 0, 1, 0, 1],
    })


def _synthetic_specs():
    """TQ01 全命中(过拟合标志「否」)/ TQ02 缺列不可用 / TQ03 训练 100% 测试 0%
    (过拟合标志「是」)/ TQ51 手工映射(涨跌占比占位)。"""
    return [
        {"name": "TQ01", "raw": "A AND B", "join": "AND", "unavailable": False,
         "conds": [{"col": "A", "op": ">", "value": 0},
                   {"col": "B", "op": ">", "value": 0}]},
        {"name": "TQ02", "raw": "缺列组合", "join": "AND", "unavailable": True,
         "conds": [], "reason": "面板缺列: X", "missing_cols": ["X"]},
        {"name": "TQ03", "raw": "C", "join": "AND", "unavailable": False,
         "conds": [{"col": "C", "op": ">", "value": 0}]},
        {"name": "TQ51", "raw": "六脉缠论买:深跌+空头/资金承接", "join": "AND",
         "unavailable": False,
         "conds": [{"col": "A", "op": ">", "value": 0}]},
    ]


def test_gen_report_synthetic(tmp_path, monkeypatch):
    """单策略报告:合成面板输出六段 Markdown,含策略名/条件/指标。"""
    monkeypatch.setattr(ver, "VERSIONS_PATH", tmp_path / "strategy_versions.json")
    monkeypatch.setattr(rep, "build_57_specs", _synthetic_specs)
    p = rep.gen_report("TQ01", str(tmp_path), df=_synthetic_df())
    assert pathlib.Path(p).exists()
    text = pathlib.Path(p).read_text(encoding="utf-8")
    assert "回测报告_TQ01_" in pathlib.Path(p).name
    for section in ("策略逻辑", "参数", "进出场条件", "回测结果", "版本历史", "已知问题"):
        assert f"## {section}" in text
    assert "A AND B" in text            # 策略逻辑
    assert "- A > 0" in text and "- B > 0" in text   # 进出场条件
    assert "训练段" in text and "测试段" in text      # 回测结果分段
    assert "胜率" in text
    assert "无版本记录" in text          # 版本历史/参数(未 bump)


def test_gen_report_unknown_strategy(tmp_path, monkeypatch):
    """未知策略名:KeyError,不落盘。"""
    monkeypatch.setattr(rep, "build_57_specs", _synthetic_specs)
    try:
        rep.gen_report("NOPE", str(tmp_path), df=_synthetic_df())
        raise AssertionError("应当 KeyError")
    except KeyError as e:
        assert "NOPE" in str(e)


def test_gen_report_57_synthetic(tmp_path, monkeypatch):
    """57 整表渲染:表头/行/过拟合标志/涨跌占比占位/生成时间(合成面板)。"""
    monkeypatch.setattr(rep, "build_57_specs", _synthetic_specs)
    p = rep.gen_report_57(str(tmp_path), df=_synthetic_df())
    text = pathlib.Path(p).read_text(encoding="utf-8")
    assert "回测报告_57信号_" in pathlib.Path(p).name
    assert "生成时间" in text
    assert "训练胜率" in text and "测试胜率" in text
    assert "过拟合标志" in text and "涨跌占比" in text
    for name in ("TQ01", "TQ02", "TQ03", "TQ51"):
        assert f"| {name} |" in text
    # 过拟合标志: TQ03 训练 100% / 测试 0% -> 「是」; TQ01 50%/50% -> 「否」
    assert "是" in text and "否" in text
    # TQ51~TQ57 涨跌占比 spec 无法表达 -> 占位,不编造数字
    assert "见 tq_confirm_top10 文件头" in text
    # TQ02 不可用:指标标「—」
    assert "—" in text


def test_gen_report_57_overfit_row(tmp_path, monkeypatch):
    """TQ03 行过拟合标志确为「是」(|1.0 - 0.0| > 0.10)。"""
    monkeypatch.setattr(rep, "build_57_specs", _synthetic_specs)
    p = rep.gen_report_57(str(tmp_path), df=_synthetic_df())
    lines = pathlib.Path(p).read_text(encoding="utf-8").splitlines()
    row = [ln for ln in lines if ln.startswith("| TQ03 |")][0]
    assert row.split("|")[-2].strip() == "是"
    row01 = [ln for ln in lines if ln.startswith("| TQ01 |")][0]
    assert row01.split("|")[-2].strip() == "否"


def test_gen_report_57_inf_profit_loss_ratio(tmp_path, monkeypatch):
    """测试段亏损行收益为正 -> 引擎盈亏比 = inf(无亏损),渲染「∞」而非「—」。

    实测确认面板 TQ01 测试段即此情形(亏损行 ext_up 为正,avg_loss <= 0)。
    """
    df = pd.DataFrame({
        "股票代码": ["1"] * 4,
        "信号日期": [20250101, 20250102, 20250103, 20250104],
        "是否盈利": [1, 0, 1, 0],
        "区间涨跌幅": [0.15, 0.08, 0.20, 0.05],
        "年": [2025] * 4,
        "D": [1] * 4,
    })
    specs = [{"name": "TQ99", "raw": "D", "join": "AND", "unavailable": False,
              "conds": [{"col": "D", "op": ">", "value": 0}]}]
    monkeypatch.setattr(rep, "build_57_specs", lambda: specs)
    p = rep.gen_report_57(str(tmp_path), df=df)
    lines = pathlib.Path(p).read_text(encoding="utf-8").splitlines()
    row = [ln for ln in lines if ln.startswith("| TQ99 |")][0]
    assert "∞" in row
