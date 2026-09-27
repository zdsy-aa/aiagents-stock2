# -*- coding: utf-8 -*-
"""筹码数据源选型(Phase5 Task5.5)测试。

原则: 单测不依赖真实网络 —— chip_decision 为记录型实现(结论来自
2026-09-27 实测探测,日志见 docs/chip_data_decision.md);fetch 的
akshare 映射逻辑经 monkeypatch 注入假数据验证,不触碰外网。
"""
import datetime

import pytest

import automation.chip_data as cd


def test_decision_structure():
    d = cd.chip_decision()
    assert d["source"] in ("akshare", "tdx_file", "unavailable")
    assert d["notes"]


def test_decision_recorded_unavailable_with_probe_notes():
    d = cd.chip_decision()
    assert d["source"] == "unavailable"
    assert d["status"] == "unavailable"
    notes = d["notes"]
    for kw in ("akshare", "push2his", "TDX", "通达信"):
        assert kw in notes
    assert "docs/chip_data_decision.md" in notes


def test_fetch_chip_raises_with_guidance():
    with pytest.raises(NotImplementedError) as ei:
        cd.fetch_chip("000001")
    msg = str(ei.value)
    assert "不可用" in msg
    assert "chip_data_decision" in msg


def test_fetch_via_akshare_mapping(monkeypatch):
    import pandas as pd

    fake = pd.DataFrame(
        {
            "日期": [datetime.date(2026, 9, 25), datetime.date(2026, 9, 26)],
            "获利比例": [0.45, 0.52],
            "平均成本": [11.30, 11.32],
            "90成本-低": [11.10, 11.12],
            "90成本-高": [11.50, 11.51],
            "90集中度": [0.017, 0.018],
            "70成本-低": [11.20, 11.21],
            "70成本-高": [11.40, 11.41],
            "70集中度": [0.009, 0.010],
        }
    )
    monkeypatch.setattr(cd, "_ak_cyq_df", lambda code, adjust="": fake)
    out = cd._fetch_via_akshare("000001")
    assert out["date"] == "2026-09-26"
    assert out["获利盘"] == pytest.approx(0.52)
    assert out["平均成本"] == pytest.approx(11.32)
    assert out["90%集中度区间"] == pytest.approx([11.12, 11.51])


def test_tdx_file_probe_offline_safe():
    r = cd.probe_tdx_file()
    assert isinstance(r, dict)
    assert r["candidate"] == "tdx_file"
    assert "ok" in r


def test_probe_helpers_exist():
    assert callable(cd.probe_akshare)
    assert callable(cd.probe_em_http)
    assert callable(cd.probe_tdx_file)


def test_run_with_timeout_returns_on_hang():
    """超时包装在底层调用挂死时必须按时返回,而不是等待线程收尾(审查修复)。"""
    import time

    def slow_probe():
        time.sleep(120)
        return "never"

    t0 = time.monotonic()
    result = cd._run_with_timeout(slow_probe, timeout_s=0.3)
    elapsed = time.monotonic() - t0
    assert elapsed < 2.0
    assert isinstance(result, TimeoutError)
    assert "超时" in str(result)


def test_run_with_timeout_passes_value():
    assert cd._run_with_timeout(lambda: "ok", timeout_s=5.0) == "ok"
