# tests/test_chanlun_universe.py
from chanlun_universe import is_eligible, board_of


def test_board_of_prefixes():
    assert board_of("600000") == "沪主板"
    assert board_of("000001") == "深主板"
    assert board_of("002594") == "中小板"
    assert board_of("300750") == "创业板"
    assert board_of("688981") == "科创板"
    assert board_of("830799") == "北交所"
    assert board_of("920819") == "北交所"


def test_is_eligible_excludes_kechuang_beijiao_st():
    assert is_eligible("600000", "浦发银行") is True
    assert is_eligible("300750", "宁德时代") is True
    assert is_eligible("688981", "中芯国际") is False   # 科创排除
    assert is_eligible("830799", "艾融软件") is False   # 北交排除
    assert is_eligible("000001", "ST平安") is False      # ST 排除
    assert is_eligible("000001", "*ST深发") is False     # *ST 排除
