# tests/test_alias_rules.py
import json, pathlib

def test_alias_rules_shape():
    p = pathlib.Path("indicators/alias_rules.json")
    d = json.loads(p.read_text(encoding="utf-8"))
    assert set(d) >= {"aliases", "families"}
    assert ["跌20超15", "20日跌幅超15"] in d["aliases"]
    assert ["VOL_MA", "VOL_MA_L", "VOL_MA_S", "Volume_MA"] in d["families"]

def test_package_exports_compute():
    # 原占位测试(NotImplementedError)由 Task 2.4 实装取代:未知名称抛 KeyError
    # (详见 tests/test_pipeline_cli.py 的完整断言)。
    from indicators import compute
    import pandas as pd
    df = pd.DataFrame({"Open": [10] * 50, "High": [10.5] * 50, "Low": [9.5] * 50,
                       "Close": [10] * 50, "Volume": [1000] * 50})
    try:
        compute("不存在的指标", df)
        raised = False
    except KeyError:
        raised = True
    assert raised
