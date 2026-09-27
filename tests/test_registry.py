"""Task 2.3 测试:compile_indicator / register / load_registry。

设计要点(控制器裁决):
- compile 逐语句隔离求值并把结果写回 env;遇 NotImplementedError(如 WINNER)/
  NameError 的语句跳过、记入 result["errors"],后续语句继续求值;
  outputs 只含成功求值的输出语句。
- register 部分注册语义:只要有 ≥1 个输出成功求值即写入 registry.json
  (同名覆盖)并返回 True;entry 含 "unsupported"(错误清单)与
  "partial"(存在 unsupported 即 true);outputs 为空才拒绝写入返回 False。
  核心_基础V3 partial=true(5 条 WINNER 语句);六脉神剑V5 partial=false。
- signals direction 启发式:含「卖」→sell;含「买」或「首发」→buy;其余→both
  (买/卖兼具按 sell 优先)。
- 写类测试用 backup_restore fixture 快照/还原 registry.json,保证测试后
  仓库内文件不变。
"""
import pathlib

import pytest

from indicators.registry import compile_indicator, load_registry, register

CORE = ("/home/tdxback/通达信指标/20260424001/tdx_v4_standalone/"
        "00_公共核心模块/核心_基础V3.txt")
LIUMAI = ("/home/tdxback/通达信指标/20260424001/tdx_v4_standalone/"
          "03_资金流向体系/六脉神剑V5.txt")

REG_PATH = pathlib.Path(__file__).parent.parent / "indicators" / "registry.json"

_ENTRY_KEYS = {"source", "outputs", "signals", "params", "compiled_at",
               "unsupported", "partial"}


@pytest.fixture
def backup_restore():
    """快照 registry.json,测试结束还原(写类测试必须用)。"""
    original = REG_PATH.read_bytes() if REG_PATH.exists() else None
    yield
    if original is None:
        REG_PATH.unlink(missing_ok=True)
    else:
        REG_PATH.write_bytes(original)


# ---------------------------------------------------------------- brief 测试

def test_compile_core_basic():
    p = CORE
    c = compile_indicator(p, code_prefix="600000")
    assert "涨停" in c["outputs"] and "修正量" in c["outputs"]
    assert "量比" in c["outputs"]
    assert c["warnings"] is not None


def test_register_writes_registry(backup_restore):
    p = CORE
    register(p)
    reg = load_registry()
    assert "核心_基础V3" in reg


# ---------------------------------------------------------------- 编译语义

def test_compile_core_basic_winner_errors_pinned():
    """核心_基础V3 末段 5 条 WINNER 依赖语句:compile 失败但产出已成功部分。
    3 条 WINNER → NotImplementedError;筹码集中/筹码锁定 引用被跳过名 →
    NameError。outputs 保留筹码节之前的全部输出(主力强度),不含 5 条失败名。
    (register 层按部分注册语义仍写入,见 test_register_core_basic_partial。)"""
    c = compile_indicator(CORE, code_prefix="600000")
    assert c["ok"] is False
    cats = [e["category"] for e in c["errors"]]
    assert cats.count("not_implemented") == 3
    assert cats.count("name_error") == 2
    for skipped in ("获利盘", "活跃筹码", "套牢盘", "筹码集中", "筹码锁定"):
        assert skipped not in c["outputs"], skipped
    assert "主力强度" in c["outputs"]


def test_compile_liumai_clean_and_signals():
    """六脉神剑V5 全语句可求值;signals = 名称含 买/卖/首发 ∪ 头部【输出】声明。
    direction 启发式:首发→buy(控制器裁决),声明无标记→both。"""
    c = compile_indicator(LIUMAI, code_prefix="600000")
    assert c["name"] == "六脉神剑V5"
    assert c["ok"] is True and c["errors"] == []
    assert "六脉得分" in c["outputs"] and "六脉6红首发" in c["outputs"]
    sig = {s["name"]: s["direction"] for s in c["signals"]}
    assert sig["六脉6红首发"] == "buy" and sig["六脉5红首发"] == "buy"
    assert sig["MACD多"] == "both"       # 头部【输出】声明、无买/卖/首发 → both
    assert "得分曲线" not in sig         # 未声明、无买/卖/首发 → 非信号


def test_compile_params_default_empty_for_corpus():
    """语料头部无【参数说明】节 → params 空 dict(不臆造)。"""
    assert compile_indicator(CORE)["params"] == {}
    assert compile_indicator(LIUMAI)["params"] == {}


# ---------------------------------------------------------------- 注册行为

def test_register_core_basic_partial(backup_restore):
    """部分注册(控制器裁决):核心_基础V3 有 5 条 WINNER 依赖语句 → register
    返回 True;entry partial=true、unsupported=5 条;outputs 不含失败语句名。"""
    assert register(CORE) is True
    entry = load_registry()["核心_基础V3"]
    assert entry["partial"] is True
    assert len(entry["unsupported"]) == 5
    assert all(set(e) == {"name", "line", "category", "reason"}
               for e in entry["unsupported"])
    cats = [e["category"] for e in entry["unsupported"]]
    assert cats.count("not_implemented") == 3
    for skipped in ("获利盘", "活跃筹码", "套牢盘", "筹码集中", "筹码锁定"):
        assert skipped not in entry["outputs"], skipped
    assert "主力强度" in entry["outputs"]


def test_register_success_clean_entry(backup_restore):
    """六脉神剑V5 全语句可求值 → partial=false、unsupported 空。"""
    assert register(LIUMAI) is True
    entry = load_registry()["六脉神剑V5"]
    assert set(entry) == _ENTRY_KEYS
    assert entry["partial"] is False and entry["unsupported"] == []
    assert "六脉得分" in entry["outputs"]
    assert entry["source"] == LIUMAI


def test_register_broken_formula_refused(tmp_path, backup_restore):
    """全部语句失败(0 个输出成功求值)→ 拒绝写入并返回 False。"""
    p = tmp_path / "坏指标.txt"
    p.write_text("获利盘:WINNER(CLOSE)*100;", encoding="utf-8")
    before = load_registry()
    assert register(p) is False
    assert load_registry() == before


# ---------------------------------------------------------------- 参数/信号提取

def test_params_extraction_synthetic(tmp_path):
    p = tmp_path / "参数指标.txt"
    p.write_text(
        "{【参数说明】\n"
        "  快线周期:默认5\n"
        "  慢线周期:默认 20\n"
        "  平滑系数:默认0.5\n"
        "【输出】快慢线\n"
        "}\n"
        "快慢线:EMA(CLOSE,5)-EMA(CLOSE,20),NODRAW;\n",
        encoding="utf-8",
    )
    c = compile_indicator(p)
    assert c["params"] == {"快线周期": 5, "慢线周期": 20, "平滑系数": 0.5}
    assert c["outputs"] == ["快慢线"]
    assert c["ok"] is True


def test_signals_direction_synthetic(tmp_path):
    """direction 启发式各一例:卖→sell、买→buy、首发→buy、声明/其余→both、
    买卖兼具→sell 优先。"""
    p = tmp_path / "信号指标.txt"
    p.write_text(
        "{【输出】多头确认、空头确认\n}\n"
        "多头确认:CLOSE>OPEN;\n"
        "买入信号:CLOSE>OPEN;\n"
        "卖出信号:CLOSE<OPEN;\n"
        "金叉首发:CLOSE>OPEN;\n"
        "买卖点:CLOSE>OPEN;\n",
        encoding="utf-8",
    )
    c = compile_indicator(p)
    sig = {s["name"]: s["direction"] for s in c["signals"]}
    assert sig == {
        "多头确认": "both",   # 【输出】声明(空头确认非实际输出,已过滤)
        "买入信号": "buy",
        "卖出信号": "sell",
        "金叉首发": "buy",
        "买卖点": "sell",     # 买卖兼具 → sell 优先(与裁决列举顺序一致)
    }


# ---------------------------------------------------------------- 注册表文件

def test_load_registry_shape():
    """初始 registry.json 两条目结构与部分注册字段(控制器验收)。"""
    reg = load_registry()
    assert "核心_基础V3" in reg and "六脉神剑V5" in reg
    for name, entry in reg.items():
        assert set(entry) == _ENTRY_KEYS, name
        assert pathlib.Path(entry["source"]).name == name + ".txt", name
        assert isinstance(entry["outputs"], list)
        assert all(set(s) == {"name", "direction"} for s in entry["signals"])
        assert isinstance(entry["partial"], bool)
        assert isinstance(entry["unsupported"], list)
    assert reg["核心_基础V3"]["partial"] is True
    assert len(reg["核心_基础V3"]["unsupported"]) == 5
    assert reg["六脉神剑V5"]["partial"] is False
