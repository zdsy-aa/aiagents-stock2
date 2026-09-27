"""Task 2.1 语料全量解析验收:32 个公式文件零语法错误。

验收口径:
- 文件集 = tdx_v4_standalone 下全部 .txt,排除 99_说明手册 目录(4 个说明文件)
  与根目录 导入说明_必读.txt(也是说明文件,共 5 个,公式文件恰 32 个)
- 每个文件 parse_formula 后 statements 非空
- warnings 只能属于"已登记暂不支持"类别(draw_stmt / bare_output /
  recursive_assign / unclosed_comment 等);出现 syntax_error / lex_error 即语法面
  未覆盖,须按 R2.1-A 登记或修复 —— 本测试即"零语法错误"的机器可验形式
  (数字开头标识符经控制器裁决改为支持,已从暂不支持移除)
"""
import pathlib

from indicators.tdx_parser import parse_formula

FORMULA_ROOT = pathlib.Path("/home/tdxback/通达信指标/20260424001/tdx_v4_standalone")
SKIP_DIR = "99_说明手册"
SKIP_FILES = {"导入说明_必读.txt"}

# 与 indicators/tdx_parser.py 头部"暂不支持"登记一一对应
# (数字开头标识符经控制器裁决改为支持,已从暂不支持移除)
REGISTERED_WARNING_CATEGORIES = {
    "draw_stmt",          # DRAW*/STICKLINE 等绘图语句
    "bare_output",        # 裸表达式输出语句(无 NAME: 头)
    "recursive_assign",   # 递归 :=
    "array_index",        # 数组下标 X[1](防御性,语料 0 处)
    "preprocessor",       # # 预处理指令(防御性,语料 0 处)
    "unclosed_comment",   # 未闭合 { 注释(按行容错)
}


def test_parse_all_formula_files():
    files = sorted(
        f for f in FORMULA_ROOT.rglob("*.txt")
        if SKIP_DIR not in f.parts and f.name not in SKIP_FILES
    )
    assert len(files) == 32, f"预期 32 个公式文件,实际 {len(files)}: {[f.name for f in files]}"
    total_stmt = 0
    total_warn = 0
    for f in files:
        r = parse_formula(f.read_text(encoding="utf-8", errors="ignore"))
        assert r["statements"], f"{f}: 未解析出任何语句"
        unregistered = [
            w for w in r["warnings"] if w["category"] not in REGISTERED_WARNING_CATEGORIES
        ]
        assert not unregistered, f"{f}: 未登记的语法错误 {unregistered[:3]}"
        total_stmt += len(r["statements"])
        total_warn += len(r["warnings"])
    print(f"语料解析通过: {len(files)} 文件 / {total_stmt} 语句 / {total_warn} warnings(已登记)")
