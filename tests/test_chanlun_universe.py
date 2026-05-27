# tests/test_chanlun_universe.py
from chanlun_universe import is_eligible, board_of, list_universe


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


def test_list_universe_handles_prefixed_filenames(tmp_path):
    # 本地K线文件名带 sh/sz/bj 前缀（tdx-api 批量下载命名），应剥成裸代码
    for fname in ["sh600000.db", "sz000001.db", "sz300750.db", "sh688981.db",
                  "bj920000.db", "600519.db", "sh600519.db"]:
        (tmp_path / fname).write_bytes(b"")
    uni = list_universe(kline_dir=str(tmp_path))
    codes = [c for c, _, _ in uni]
    assert "600000" in codes and "000001" in codes and "300750" in codes  # 前缀已剥离
    assert "688981" not in codes        # 科创排除
    assert "920000" not in codes        # 北交排除
    assert codes.count("600519") == 1   # 裸名+前缀名并存时去重
    assert all(not c.startswith(("sh", "sz", "bj")) for c in codes)
