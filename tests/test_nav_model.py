from views.nav_model import (NAV, all_flags, flag_to_category, current_category,
                             category_pages, category_default_flag)


def test_all_flags_covers_pages():
    flags = all_flags()
    for f in ("show_intraday", "show_qizhang", "show_chanlun_chart", "show_config", "show_history"):
        assert f in flags
    assert None not in flags


def test_flag_to_category():
    assert flag_to_category("show_qizhang") == "选股"
    assert flag_to_category("show_chanlun_chart") == "分析"
    assert flag_to_category("show_sector_strategy") == "策略"
    assert flag_to_category("show_portfolio") == "管理"
    assert flag_to_category("show_config") == "配置"
    assert flag_to_category("unknown") == "分析"


def test_current_category_from_state():
    assert current_category({}) == "分析"
    assert current_category({"show_qizhang": True}) == "选股"
    assert current_category({"show_longhubang": True}) == "策略"


def test_category_pages_and_default():
    names = [c for c, _, _ in NAV]
    assert names == ["分析", "选股", "策略", "管理", "配置"]
    assert category_default_flag("分析") is None
    assert category_default_flag("配置") == "show_config"
