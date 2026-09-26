"""指标转换流水线包:parse -> evaluate -> register -> smoke -> docs。"""
def compute(name, df, code_prefix=""):
    raise NotImplementedError("Task 2.3 实装")

def load_alias_rules():
    import json, pathlib
    return json.loads((pathlib.Path(__file__).parent / "alias_rules.json")
                      .read_text(encoding="utf-8"))
