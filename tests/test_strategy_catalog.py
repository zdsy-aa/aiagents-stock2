# tests/test_strategy_catalog.py
from strategy_catalog import CATALOG, CATEGORIES


def test_categories_constant():
    assert CATEGORIES == ["选股", "买入卖出", "测试盈利", "找共同点"]


def test_every_entry_well_formed():
    assert len(CATALOG) >= 18
    for e in CATALOG:
        assert e["类别"] in CATEGORIES, e
        assert e["名称"] and isinstance(e["名称"], str)
        assert e["脚本"] and isinstance(e["脚本"], list)
        assert all(isinstance(s, str) for s in e["脚本"])
        assert e["解释"] and isinstance(e["解释"], str)
        assert isinstance(e["关键参数"], list)
        for p in e["关键参数"]:
            assert isinstance(p, tuple) and len(p) == 3, (e["名称"], p)
        assert e["实时"] in (None, "plans", "star", "watchlist", "commonality"), e


def test_all_four_categories_present():
    present = {e["类别"] for e in CATALOG}
    assert present == set(CATEGORIES)
