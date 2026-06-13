import fetch_industry_snapshot as F

# _code6: 去交易所前缀 → 6位
assert F._code6("sh.600519") == "600519"
assert F._code6("sz.000001") == "000001"
assert F._code6("bj.830799") == "830799"

# extract_industry: 行=[date,code,name,industry,cls]；只留 universe 内 & 非空行业
rows = [
    ["2026-06-08", "sh.600519", "贵州茅台", "C15酒、饮料和精制茶制造业", "证监会行业分类"],
    ["2026-06-08", "sh.600001", "邯郸钢铁", "", "证监会行业分类"],          # 空行业→剔
    ["2026-06-08", "sz.000001", "平安银行", "J66货币金融服务", "证监会行业分类"],
    ["2026-06-08", "sh.600002", "齐鲁石化", "C25石油加工", "证监会行业分类"],  # 不在 universe→剔
]
universe = {"600519", "000001"}
m = F.extract_industry(rows, universe)
assert m == {"600519": "C15酒、饮料和精制茶制造业", "000001": "J66货币金融服务"}, m

# 全空 → extract 返回空 dict（main 据此抛错）
assert F.extract_industry([], {"600519"}) == {}
print("test_fetch_industry_snapshot ALL OK")
