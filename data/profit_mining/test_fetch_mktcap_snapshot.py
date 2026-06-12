# test_fetch_mktcap_snapshot.py —— 腾讯市值取数 TDD。python3 test_fetch_mktcap_snapshot.py
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_mktcap_snapshot as F


def _line(code6, total_yi):
    """造一条 88 字段的腾讯响应行,代码在 idx2,总市值在 idx45。"""
    f = ["0"] * 88
    f[1] = "名称"
    f[2] = code6
    f[44] = "100.00"          # 流通市值(亿)
    f[45] = str(total_yi)     # 总市值(亿)
    pre = F._prefix(code6)
    return f'v_{pre}="' + "~".join(f) + '";'


def test_prefix():
    assert F._prefix("600519") == "sh600519"
    assert F._prefix("688981") == "sh688981"
    assert F._prefix("000001") == "sz000001"
    assert F._prefix("300750") == "sz300750"
    assert F._prefix("430047") == "bj430047"
    assert F._prefix("830799") == "bj830799"
    assert F._prefix("900901") == "sh900901"
    print("OK _prefix")


def test_parse_line():
    line = _line("600519", 16149.93)
    code, mktcap = F._parse_line(line)
    assert code == "600519", code
    assert abs(mktcap - 16149.93e8) < 1.0, mktcap        # 亿→元
    print("OK _parse_line")


def test_parse_line_malformed():
    assert F._parse_line("garbage no quotes") is None
    assert F._parse_line('v_sh1="a~b~c";') is None        # 字段不足
    assert F._parse_line('v_sh600519="' + "~".join(["x"] * 88) + '";') is None  # idx45非数字
    print("OK _parse_line_malformed")


def test_fetch_mktcap_stub():
    known = {"600519": 16149.93, "000001": 2181.23}

    def stub(prefixed):
        # prefixed 形如 ["sh600519","sz000001"] → 回每只的响应行
        return "\n".join(_line(p[2:], known[p[2:]]) for p in prefixed if p[2:] in known)

    df = F.fetch_mktcap(["600519", "000001"], batch=60, fetch=stub)
    assert len(df) == 2, len(df)
    assert set(df["代码"]) == {"600519", "000001"}
    assert df["代码"].map(len).eq(6).all()
    row = df[df["代码"] == "600519"].iloc[0]
    assert abs(float(row["总市值"]) - 16149.93e8) < 1.0
    print("OK fetch_mktcap_stub")


def test_fetch_mktcap_zfill():
    def stub(prefixed):
        return _line("000001", 50.0)
    df = F.fetch_mktcap(["1"], batch=60, fetch=stub)   # 输入未补零也应输出6位
    assert list(df["代码"]) == ["000001"], list(df["代码"])
    print("OK fetch_mktcap_zfill")


def test_fetch_mktcap_batch_failure_skips():
    def stub(prefixed):
        codes = [p[2:] for p in prefixed]
        if "600000" in codes:
            raise RuntimeError("网络抖动")   # 含600000的批一直失败
        return "\n".join(_line(c, 200.0) for c in codes)
    df = F.fetch_mktcap(["600000", "000002"], batch=1, fetch=stub)
    # 第一批(600000)重试仍失败被跳过,第二批(000002)成功
    assert list(df["代码"]) == ["000002"], list(df["代码"])
    print("OK fetch_mktcap_batch_failure_skips")


def test_fetch_mktcap_all_empty():
    def stub(prefixed):
        return ""
    df = F.fetch_mktcap(["600519"], batch=60, fetch=stub)
    assert len(df) == 0
    print("OK fetch_mktcap_all_empty")


if __name__ == "__main__":
    test_prefix()
    test_parse_line()
    test_parse_line_malformed()
    test_fetch_mktcap_stub()
    test_fetch_mktcap_zfill()
    test_fetch_mktcap_batch_failure_skips()
    test_fetch_mktcap_all_empty()
    print("ALL OK")
