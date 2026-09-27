"""Task 2.5 测试:单指标文档自动生成(pipeline `docs <名称>` 子命令)。

- 简报用例(test_gen_doc_for_core_basic)原样保留:docs 核心_基础V3 →
  docs/indicators/核心_基础V3.md,八小节齐全;
- 口径补充用例:未知名称 exit 1 且报错到 stderr;partial 指标的 unsupported
  清单(含原因)进「转换逻辑」;registry params 为空 →
  「固定参数:公式内嵌默认;无独立可调参数」;registry signals 为空 →
  「本指标无标准买卖信号,输出为状态量」;头部注释无【适用周期】/【失效条件】
  →「待补充」;「原始公式」直接引用源文件语句原文;
- 自动注册路径(registry 无条目 → 先 register 再生成)与内置公式路径用临时
  registry/docs 目录(in-process),不触碰仓库 registry.json 与 docs 产物。
"""
import json
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
CLI = REPO / "scripts" / "indicator_pipeline.py"
REG_PATH = REPO / "indicators" / "registry.json"
DOC_PATH = REPO / "docs" / "indicators" / "核心_基础V3.md"
SECTIONS = ("指标说明", "原始公式", "转换逻辑", "参数说明",
            "买入信号", "卖出信号", "适用周期", "失效条件")

if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

import indicator_pipeline as ip  # noqa: E402
import indicators.registry as registry_mod  # noqa: E402


def _run_cli(*args):
    return subprocess.run([sys.executable, str(CLI), *args],
                          capture_output=True, text=True, cwd=str(REPO))


# ---------------------------------------------------------------- 简报用例

def test_gen_doc_for_core_basic():
    r = subprocess.run([sys.executable, "scripts/indicator_pipeline.py", "docs", "核心_基础V3"],
                       capture_output=True, text=True)
    assert r.returncode == 0
    p = pathlib.Path("docs/indicators/核心_基础V3.md")
    assert p.exists()
    txt = p.read_text(encoding="utf-8")
    for sec in ("指标说明", "原始公式", "转换逻辑", "参数说明", "买入信号", "卖出信号", "适用周期", "失效条件"):
        assert sec in txt, sec


# ---------------------------------------------------------------- 内容口径

@pytest.fixture(scope="module")
def core_doc():
    r = _run_cli("docs", "核心_基础V3")
    assert r.returncode == 0, r.stderr
    return DOC_PATH.read_text(encoding="utf-8")


def test_doc_sections_in_template_order(core_doc):
    idx = [core_doc.index(sec) for sec in SECTIONS]
    assert idx == sorted(idx), f"小节顺序不符模板: {list(zip(SECTIONS, idx))}"


def test_doc_raw_formula_quotes_source_statements(core_doc):
    # 原始公式 = 源文件语句原文(含修饰符),直接引用
    assert "涨停幅度:IF(CODELIKE('3') OR CODELIKE('68'),0.2,0.1),NODRAW;" in core_doc
    assert "量缩显著:=VOL<MA(VOL,VL)*0.8;" in core_doc


def test_doc_partial_unsupported_listed_with_reason(core_doc):
    # 核心_基础V3 partial=true:转换逻辑列出 unsupported 清单与原因
    assert "逐语句 AST 求值" in core_doc
    assert "40 个序列" in core_doc
    assert "WINNER" in core_doc          # 原因原文(函数 WINNER 未登记)
    assert "获利盘" in core_doc          # 失败语句名
    assert "not_implemented" in core_doc


def test_doc_empty_params_renders_fixed_default(core_doc):
    # 核心_基础V3 params={} → 固定参数口径句
    assert "固定参数:公式内嵌默认;无独立可调参数" in core_doc


def test_doc_empty_signals_renders_state_quantity(core_doc):
    # 核心_基础V3 signals=[] → 状态量口径句(买入/卖出两节均出现)
    assert core_doc.count("本指标无标准买卖信号,输出为状态量") >= 2


def test_doc_missing_period_and_invalidation_marked(core_doc):
    # 源文件头部无【适用周期】/【失效条件】声明 → 待补充
    tail = core_doc[core_doc.index("## 适用周期"):]
    assert "待补充" in tail


def test_docs_unknown_name_exit1_stderr():
    r = _run_cli("docs", "不存在的指标")
    assert r.returncode == 1
    assert "不存在的指标" in r.stderr
    assert not (REPO / "docs" / "indicators" / "不存在的指标.md").exists()


# ------------------------------------- 头部注释节抽取(语料无这些节,直接用文本单测)

def test_description_prefers_function_description_section():
    head, comments, _ = ip._head_parts(
        "{【指标功能说明】\n  判定价涨量增。\n  第二行要点。\n}\nX:CLOSE;\n")
    assert ip._description(head, comments) == ["判定价涨量增。", "第二行要点。"]


def test_quoted_section_uses_header_declaration_else_pending():
    head, _, _ = ip._head_parts(
        "{【指标功能说明】一句话。\n【适用周期】日线;沪深A股。\n"
        "【失效条件】日K 不足 250 根跳过。\n}\nX:CLOSE;\n")
    assert ip._quoted_section(head, "适用周期") == ["日线;沪深A股。"]
    assert ip._quoted_section(head, "失效条件") == ["日K 不足 250 根跳过。"]
    assert ip._quoted_section(head, "不存在的节") == ["待补充"]


# ---------------------------------------------------------------- 自动注册 / 内置

@pytest.fixture
def tmp_registry(tmp_path, monkeypatch):
    """临时 registry.json + 临时 docs 目录(cmd_docs 全程 in-process)。"""
    reg = tmp_path / "registry.json"
    reg.write_text("{}\n", encoding="utf-8")
    docs = tmp_path / "docs"
    monkeypatch.setattr(registry_mod, "REGISTRY_PATH", reg)
    monkeypatch.setattr(ip, "_registry_path", lambda: reg)
    monkeypatch.setattr(ip, "DOCS_DIR", docs)
    return reg, docs


def test_docs_auto_registers_then_generates(tmp_registry):
    reg, docs = tmp_registry
    before = REG_PATH.read_bytes()
    rc = ip.cmd_docs("资金移动V5")           # 未注册的语料指标
    assert rc == 0
    entry = json.loads(reg.read_text(encoding="utf-8"))["资金移动V5"]
    assert entry["source"].endswith("资金移动V5.txt")
    txt = (docs / "资金移动V5.md").read_text(encoding="utf-8")
    for sec in SECTIONS:
        assert sec in txt, sec
    assert REG_PATH.read_bytes() == before   # 仓库 registry.json 未被触碰


def test_doc_quotes_period_and_invalidation_sections(tmp_path, tmp_registry):
    reg, docs = tmp_registry
    src = tmp_path / "测试指标.txt"
    src.write_text(
        "{【指标功能说明】\n  判定价涨量增。\n【适用周期】日线;沪深A股。\n"
        "【失效条件】日K 不足 250 根跳过。\n}\n"
        "X:CLOSE>REF(CLOSE,1),NODRAW;\n", encoding="utf-8")
    assert registry_mod.register(src) is True
    assert ip.cmd_docs("测试指标") == 0
    txt = (docs / "测试指标.md").read_text(encoding="utf-8")
    assert "判定价涨量增。" in txt
    assert "日线;沪深A股。" in txt[txt.index("## 适用周期"):]
    assert "日K 不足 250 根跳过。" in txt[txt.index("## 失效条件"):]
    assert "X:CLOSE>REF(CLOSE,1),NODRAW;" in txt   # 语句原文直引


def test_docs_builtin_source_macd(tmp_registry):
    reg, docs = tmp_registry
    rc = ip.cmd_docs("MACD")                 # 公式库无标准文件 → 内置公式
    assert rc == 0
    assert json.loads(reg.read_text(encoding="utf-8"))["MACD"]["source"] == \
        "builtin:MACD"
    txt = (docs / "MACD.md").read_text(encoding="utf-8")
    assert "EMA(CLOSE,12)" in txt            # 原始公式引自内置公式文本
    assert "MACD" in txt[txt.index("## 指标说明"):txt.index("## 原始公式")]
