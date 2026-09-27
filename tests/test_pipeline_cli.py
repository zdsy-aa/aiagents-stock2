"""Task 2.4 测试:指标增量流水线 CLI(check-new / run / run-all / smoke)与
indicators.compute 实装。

设计要点(控制器裁决):
- check-new 归并语义:add_new.txt∪add_zb.txt 名称先过 alias_rules 归一
  (aliases 双向归一到规范名;families 同族任一命中即视为已存在——命中面为
  registry.json 名称 ∪ all.txt 行);输出「新增」清单;all.txt 在内存中归一,
  不改文件。all.txt 是厂商在册名录,不是「已转换」集合:名录内但未注册的
  名称(如 MACD)仍判为新增(否则增量入口对任何在册名永久失效)。
- run 冒烟判据:每个输出 Series 长度=n 且 np.isfinite 全 True(标量输出判
  finite);partial 指标(有 unsupported)允许 run 成功但输出与报告标明 partial。
- compute:registry 查 source → parse(带缓存)→ env 求值 → {输出名: Series};
  未知名称抛 KeyError;失败语句跳过(与 compile 部分注册口径一致)。
- 写 registry.json 的测试统一挂 backup_restore fixture(简报前置:
  「registry.json 无 MACD」由 fixture 保证并还原)。
"""
import pathlib
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import indicator_pipeline as ip  # noqa: E402

from indicators import compute  # noqa: E402
from indicators.evaluator import synthetic_df  # noqa: E402
from indicators.registry import load_registry  # noqa: E402

REG_PATH = REPO / "indicators" / "registry.json"


@pytest.fixture
def backup_restore():
    """快照 registry.json 并临时移除 MACD(简报前置),测试结束还原。"""
    original = REG_PATH.read_bytes() if REG_PATH.exists() else None
    if original is not None:
        reg = ip.json.loads(original.decode("utf-8"))
        if "MACD" in reg:
            reg.pop("MACD")
            REG_PATH.write_text(
                ip.json.dumps(reg, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8")
    yield
    if original is None:
        REG_PATH.unlink(missing_ok=True)
    else:
        REG_PATH.write_bytes(original)


# ---------------------------------------------------------------- 简报用例

def test_check_new_finds_macd_before_registration(backup_restore):
    # 前置:registry.json 无 MACD(backup_restore fixture 保证)
    r = subprocess.run([sys.executable, "scripts/indicator_pipeline.py",
                        "check-new"],
                       capture_output=True, text=True, cwd=str(REPO))
    assert r.returncode == 0
    assert "MACD" in r.stdout          # add_new.txt 含 MACD 且未注册


def test_compute_unknown_raises():
    df = pd.DataFrame({"Open": [10] * 50, "High": [10.5] * 50, "Low": [9.5] * 50,
                       "Close": [10] * 50, "Volume": [1000] * 50})
    try:
        compute("不存在的指标", df)
        raised = False
    except KeyError:
        raised = True
    assert raised


# ---------------------------------------------------------------- check-new 归并

_RULES = {
    "aliases": [["跌20超15", "20日跌幅超15"]],
    "families": [["VOL_MA", "VOL_MA_L", "VOL_MA_S", "Volume_MA"]],
}


def test_find_new_plain_registered_skipped():
    assert ip.find_new_names(["MACD"], ["MACD"], [], _RULES) == []


def test_find_new_alias_bidirectional():
    # 候选是别名、registry 是规范名(反向亦然)→ 均视为已存在
    assert ip.find_new_names(["跌20超15"], ["20日跌幅超15"], [], _RULES) == []
    assert ip.find_new_names(["20日跌幅超15"], ["跌20超15"], [], _RULES) == []


def test_find_new_family_hit_in_registry():
    assert ip.find_new_names(["Volume_MA"], ["VOL_MA_L"], [], _RULES) == []


def test_find_new_family_hit_in_all_txt():
    # families 同族任一命中即视为已存在:命中面含 all.txt 行
    assert ip.find_new_names(["Volume_MA"], [], ["VOL_MA"], _RULES) == []


def test_find_new_catalog_name_still_new():
    # all.txt 是厂商在册名录,不是已转换集合:名录内未注册名仍为新增(MACD 语义)
    assert ip.find_new_names(["MACD"], [], ["MACD"], _RULES) == ["MACD"]


def test_find_new_dedup_preserves_order():
    assert ip.find_new_names(["MACD", "BOLL", "MACD"], [], [], _RULES) == \
        ["MACD", "BOLL"]


# ---------------------------------------------------------------- compute 实装

def test_compute_liumai_returns_series():
    out = compute("六脉神剑V5", synthetic_df(50))
    assert isinstance(out, dict) and "MACD多" in out and "六脉6红首发" in out
    for nm, v in out.items():
        assert isinstance(v, pd.Series), f"{nm} 非 Series"
        assert len(v) == 50, f"{nm} 长度 {len(v)} != 50"
        # rolling 头部预热窗 NaN 是正常语义(均线等),尾部必须全 finite
        assert np.isfinite(v.to_numpy()[-40:]).all(), f"{nm} 尾部含非有限值"


# ---------------------------------------------------------------- 冒烟判据

def _s(values):
    return pd.Series(values, dtype=float)


def test_smoke_judge_clean_series_passes():
    assert ip.smoke_violations({"X": _s([1.0] * 300)}) == []


def test_smoke_judge_wrong_length_fails():
    assert ip.smoke_violations({"X": _s([1.0] * 299)})


def test_smoke_judge_warmup_prefix_allowed():
    # rolling 头部预热窗 NaN(MA 语义)→ 通过
    a = _s([np.nan] * 9 + [2.0] * 291)
    assert ip.smoke_violations({"X": a}) == []


def test_smoke_judge_internal_nan_fails():
    a = _s([1.0] * 10 + [np.nan] + [1.0] * 289)
    assert ip.smoke_violations({"X": a})


def test_smoke_judge_all_nan_fails():
    assert ip.smoke_violations({"X": _s([np.nan] * 300)})


def test_smoke_judge_infinite_middle_fails():
    a = _s([1.0] * 5 + [np.inf] + [1.0] * 294)
    assert ip.smoke_violations({"X": a})


def test_smoke_judge_scalar():
    assert ip.smoke_violations({"N": 10.0}) == []
    assert ip.smoke_violations({"N": np.inf})


# ---------------------------------------------------------------- CLI 冒烟/运行

def test_smoke_liumai_exit0():
    r = subprocess.run([sys.executable, "scripts/indicator_pipeline.py",
                        "smoke", "六脉神剑V5"],
                       capture_output=True, text=True, cwd=str(REPO))
    assert r.returncode == 0, r.stderr


def test_smoke_unknown_exit1():
    r = subprocess.run([sys.executable, "scripts/indicator_pipeline.py",
                        "smoke", "不存在的指标"],
                       capture_output=True, text=True, cwd=str(REPO))
    assert r.returncode == 1


def test_run_macd_end_to_end(backup_restore):
    rc = ip.cmd_run("MACD", "600000")
    assert rc == 0
    reg = load_registry()
    entry = reg["MACD"]
    assert entry["source"] == "builtin:MACD"
    assert entry["outputs"] == ["DIFF", "DEA", "MACD"]
    assert entry["partial"] is False
    out = compute("MACD", synthetic_df(50))
    assert set(out) == {"DIFF", "DEA", "MACD"}
    for nm, v in out.items():
        assert len(v) == 50 and np.isfinite(v.to_numpy()).all(), nm


def test_run_all_registers_corpus(backup_restore):
    rc = ip.cmd_run_all("600000")
    assert rc == 0
    reg = load_registry()
    assert "六脉神剑V5" in reg and "核心_基础V3" in reg
