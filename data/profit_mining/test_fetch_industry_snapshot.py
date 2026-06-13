# test_fetch_industry_snapshot.py —— baostock 行业取数 TDD。python3 test_fetch_industry_snapshot.py
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_industry_snapshot as F


def test_code6():
    # _code6: 去交易所前缀 → 6位
    assert F._code6("sh.600519") == "600519"
    assert F._code6("sz.000001") == "000001"
    assert F._code6("bj.830799") == "830799"
    print("OK code6")


def test_extract_industry():
    # extract_industry: 行=[date,code,name,industry,cls]；只留 universe 内 & 非空行业
    rows = [
        ["2026-06-08", "sh.600519", "贵州茅台", "C15酒、饮料和精制茶制造业", "证监会行业分类"],
        ["2026-06-08", "sh.600001", "邯郸钢铁", "", "证监会行业分类"],          # 空行业→剔
        ["2026-06-08", "sz.000001", "平安银行", "J66货币金融服务", "证监会行业分类"],
        ["2026-06-08", "sh.600002", "齐鲁石化", "C25石油加工", "证监会行业分类"],  # 不在 universe→剔
    ]
    m = F.extract_industry(rows, {"600519", "000001"})
    assert m == {"600519": "C15酒、饮料和精制茶制造业", "000001": "J66货币金融服务"}, m
    print("OK extract_industry")


def test_extract_industry_empty():
    # 全空 → extract 返回空 dict（main 据此抛错）
    assert F.extract_industry([], {"600519"}) == {}
    print("OK extract_industry_empty")


if __name__ == "__main__":
    test_code6()
    test_extract_industry()
    test_extract_industry_empty()
    print("test_fetch_industry_snapshot ALL OK")
