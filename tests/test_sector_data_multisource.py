"""智策多源兜底纯逻辑：涨跌家数统计 / 腾讯指数报文解析 / 源切换 / 换手率提示。"""
import pandas as pd

from sector_strategy_data import (
    _breadth_from_spot, _parse_tencent_index, _try_sources,
    SectorStrategyDataFetcher,
)


def test_breadth_from_spot_counts():
    df = pd.DataFrame({"涨跌幅": [9.6, 5.0, 0.0, -3.0, -9.6, 10.1, -10.2]})
    r = _breadth_from_spot(df)
    assert r["total_stocks"] == 7
    assert r["up_count"] == 3      # 9.6, 5.0, 10.1
    assert r["down_count"] == 3    # -3, -9.6, -10.2
    assert r["flat_count"] == 1    # 0.0
    assert r["limit_up"] == 2      # >=9.5: 9.6, 10.1
    assert r["limit_down"] == 2    # <=-9.5: -9.6, -10.2
    assert abs(r["up_ratio"] - round(3 / 7 * 100, 2)) < 1e-9


def test_breadth_from_spot_empty():
    assert _breadth_from_spot(pd.DataFrame({"涨跌幅": []}))["total_stocks"] == 0


def test_parse_tencent_index():
    raw = ('v_sh000001="1~上证指数~000001~4108.08~4091.89~4074.29~370668682~0~0~0.00~'
           + "~".join(["0"] * 21) + '~16.19~0.40~' + "~".join(["0"] * 50) + '";\n')
    fields = raw.split('="')[1].split('~')
    assert fields[1] == "上证指数" and fields[3] == "4108.08" and fields[31] == "16.19" and fields[32] == "0.40"
    out = _parse_tencent_index(raw)
    assert "000001" in out
    assert abs(out["000001"]["close"] - 4108.08) < 1e-6
    assert abs(out["000001"]["change_pct"] - 0.40) < 1e-6
    assert abs(out["000001"]["change"] - 16.19) < 1e-6


def test_parse_tencent_index_malformed_skipped():
    assert _parse_tencent_index("garbage no tilde") == {}


def test_try_sources_falls_through_and_returns_first_ok():
    calls = []
    def bad(): calls.append("bad"); raise RuntimeError("x")
    def empty(): calls.append("empty"); return None
    def good(): calls.append("good"); return "DATA"
    r = _try_sources([("bad", bad, 2), ("empty", empty, 2), ("good", good, 2)])
    assert r == "DATA"
    assert calls == ["bad", "empty", "good"]


def test_try_sources_all_fail_returns_none():
    assert _try_sources([("a", lambda: None, 2),
                         ("b", lambda: (_ for _ in ()).throw(ValueError()), 2)]) is None


def test_get_index_quotes_uses_tencent_first(monkeypatch):
    f = SectorStrategyDataFetcher()
    monkeypatch.setattr(f, "_index_from_tencent", lambda: {
        "sh_index": {"code": "000001", "name": "上证指数", "close": 4108.08, "change_pct": 0.4, "change": 16.19},
        "sz_index": {"code": "399001", "name": "深证成指", "close": 15745.0, "change_pct": 0.5, "change": 70.0},
        "cyb_index": {"code": "399006", "name": "创业板指", "close": 4107.0, "change_pct": 0.6, "change": 20.0},
    })
    monkeypatch.setattr(f, "_index_from_sina", lambda: (_ for _ in ()).throw(AssertionError("不应走新浪")))
    q = f._get_index_quotes()
    assert q["sh_index"]["close"] == 4108.08
    assert q["cyb_index"]["code"] == "399006"


def test_get_index_quotes_falls_to_sina_when_tencent_empty(monkeypatch):
    f = SectorStrategyDataFetcher()
    monkeypatch.setattr(f, "_index_from_tencent", lambda: {})
    monkeypatch.setattr(f, "_index_from_sina", lambda: {
        "sh_index": {"code": "000001", "name": "上证指数", "close": 4083.86, "change_pct": -0.2, "change": -8.0},
    })
    q = f._get_index_quotes()
    assert q["sh_index"]["close"] == 4083.86
