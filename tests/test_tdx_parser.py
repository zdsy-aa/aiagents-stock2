"""Task 2.1 通达信公式解析器:核心语法单测(简报 Step 1 用例 + AST schema 钉桩)。

AST 节点 schema(与简报一致,供 Task 2.2 求值器依赖):
  {"op": "num", "val": 1.0}                         数字
  {"op": "str", "val": "3"}                         字符串字面量(不含引号)
  {"op": "var", "name": "CLOSE"}                    变量/标识符(中文/英文)
  {"op": "call", "func": "REF", "args": [...]}      函数调用
  {"op": "bin", "oper": "+", "left": .., "right": ..} 二元运算
  {"op": "ternary", "cond": .., "then": .., "else": ..} IF(c,a,b) 三元
  {"op": "not", "expr": ..}                         一元非 NOT
  {"op": "neg", "expr": ..}                         一元负(实现补充,简报未定名)
"""
from indicators.tdx_parser import parse_formula


# ---------- 简报 Step 1 用例(逐字) ----------

def test_parse_output_and_intermediate():
    src = "MACD:EMA(CLOSE,8)-EMA(CLOSE,13),NODRAW;\n涨停幅度:=IF(CODELIKE('3') OR CODELIKE('68'),0.2,0.1);"
    f = parse_formula(src)
    kinds = [s["kind"] for s in f["statements"]]
    assert kinds == ["output", "assign"]
    assert f["statements"][0]["name"] == "MACD"
    assert f["statements"][1]["name"] == "涨停幅度"


def test_parse_chinese_identifiers_and_ternary():
    src = "真一字板:=涨停 AND HIGH=LOW;"
    s = parse_formula(src)["statements"][0]
    assert s["name"] == "真一字板"
    assert s["expr"]["op"] == "bin" and s["expr"]["oper"] == "AND"


def test_parse_comment_blocks():
    src = "{==== 头注释 ====}\n价涨:CLOSE>REF(CLOSE,1);"
    f = parse_formula(src)
    assert len(f["statements"]) == 1 and len(f["comments"]) == 1


def test_operator_precedence():
    src = "X:A OR B AND C;"
    e = parse_formula(src)["statements"][0]["expr"]
    assert e["op"] == "bin" and e["oper"] == "OR"
    assert e["right"]["oper"] == "AND"


# ---------- AST schema 钉桩 ----------

def test_ast_node_shapes():
    src = "X:IF(NOT(涨停),-VOL*2+1,MA(CLOSE,5)>=REF(CLOSE,1));"
    e = parse_formula(src)["statements"][0]["expr"]
    assert e["op"] == "ternary"
    cond, then, else_ = e["cond"], e["then"], e["else"]
    assert cond == {"op": "not", "expr": {"op": "var", "name": "涨停"}}
    assert then["op"] == "bin" and then["oper"] == "+"
    assert then["left"]["op"] == "bin" and then["left"]["oper"] == "*"
    assert then["left"]["left"] == {"op": "neg", "expr": {"op": "var", "name": "VOL"}}
    assert then["left"]["right"] == {"op": "num", "val": 2.0}
    assert then["right"] == {"op": "num", "val": 1.0}
    assert else_["op"] == "bin" and else_["oper"] == ">="
    assert else_["left"] == {
        "op": "call",
        "func": "MA",
        "args": [{"op": "var", "name": "CLOSE"}, {"op": "num", "val": 5.0}],
    }


def test_str_literal_and_equality_neq_ops():
    f = parse_formula("A:=CODELIKE('3');B:X<>Y;C:X=Y;")
    assert f["statements"][0]["expr"] == {
        "op": "call", "func": "CODELIKE", "args": [{"op": "str", "val": "3"}],
    }
    assert f["statements"][1]["expr"]["oper"] == "<>"
    assert f["statements"][2]["expr"]["oper"] == "="


def test_modifiers_dropped_raw_kept():
    f = parse_formula("涨停:CLOSE>REF(CLOSE,1)*1.1,NODRAW,COLORRED,LINETHICK2;")
    s = f["statements"][0]
    assert s["expr"]["op"] == "bin" and s["expr"]["oper"] == ">"
    assert "NODRAW" in s["raw"] and "COLORRED" in s["raw"]
    assert "NODRAW" not in str(s["expr"])
    assert s["line"] == 1


def test_draw_statement_skipped_with_warning():
    src = "X:=CLOSE>10;\nSTICKLINE(X,0,100,3,0),COLORRED;\nY:REF(X,1);"
    f = parse_formula(src)
    assert [s["name"] for s in f["statements"]] == ["X", "Y"]
    assert any(w["category"] == "draw_stmt" for w in f["warnings"])


def test_recursive_assign_skipped():
    f = parse_formula("X:=X+1;\nY:CLOSE;")
    assert [s["name"] for s in f["statements"]] == ["Y"]
    assert any(w["category"] == "recursive_assign" for w in f["warnings"])


def test_multiline_statement_and_unary_minus():
    src = "修正量:IF(真一字板,VOL,\n       IF(涨停 AND 缩量,VOL*2,VOL)),NODRAW;"
    f = parse_formula(src)
    assert f["statements"][0]["expr"]["op"] == "ternary"
    assert len(f["warnings"]) == 0
