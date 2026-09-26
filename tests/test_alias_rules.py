# tests/test_alias_rules.py
import json, pathlib

def test_alias_rules_shape():
    p = pathlib.Path("indicators/alias_rules.json")
    d = json.loads(p.read_text(encoding="utf-8"))
    assert set(d) >= {"aliases", "families"}
    assert ["跌20超15", "20日跌幅超15"] in d["aliases"]
    assert ["VOL_MA", "VOL_MA_L", "VOL_MA_S", "Volume_MA"] in d["families"]

def test_package_exports_compute_stub():
    from indicators import compute
    try:
        compute("MACD", None)
        raised = False
    except NotImplementedError:
        raised = True
    assert raised
