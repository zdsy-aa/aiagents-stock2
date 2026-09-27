r"""指标编译与注册表(Task 2.3)。

编译:读公式文件 → parse_formula → 逐语句 evaluate(合成 df 300 根,build_env
注入列)并把结果写回 env(包括中间 := 语句)→ 汇总 outputs/params/signals。

错误语义(控制器裁决,部分注册):
- compile 逐语句隔离求值:遇 NotImplementedError(如 WINNER 等 8 个未支持
  函数)、NameError(未定义变量)及其他异常的语句,跳过并记入
  result["errors"](注册表 entry["unsupported"],结构与 errors 一致),
  后续语句继续求值;outputs 只含成功求值的输出语句;errors 非空 →
  result["ok"] is False。
- register:只要有 ≥1 个输出成功求值即写入 registry.json(同名覆盖)并返回
  True;entry 增加 "partial": bool(存在 unsupported 即 true)与
  "unsupported": [错误清单];outputs 为空(全部语句失败)才拒绝写入并
  返回 False(错误清单打印 stderr)。
- 核心_基础V3 含 5 条 WINNER 依赖语句(获利盘/活跃筹码/套牢盘 → 未实现
  函数;筹码集中/筹码锁定 → 引用被跳过名)→ partial=true、unsupported=5;
  六脉神剑V5 全语句可求值 → partial=false。

信号标准化:输出名含「买/卖/首发」或头部注释【输出】节声明(声明名须为实际
输出)→ signals 条目 {name, direction: buy|sell|both}。direction 启发式
(控制器裁决):含「卖」→sell;含「买」或「首发」→buy;其余→both(买/卖
兼具按 sell 优先,与裁决列举顺序一致);人工可在 registry.json 修正。
【输出】节匹配 `【输出[^】]*】`(含【输出(对其他指标保持兼容)】变体),
不含【对外输出】。

params:头部注释【参数说明】节正则提取「参数名: ... 默认 N」(简报正则
`参数名:.*?默认?(\\d+)` 的落体);提取不到给空 dict——不臆造。语料当前无
【参数说明】节,故全部为 {}。

code_prefix 语义与 2.2 CODELIKE 一致(如 '600000'/'300001',默认 '600000'
与 evaluator 默认一致;对语料 CODELIKE('3')/CODELIKE('68') 即沪深主板口径)。
"""
import json
import pathlib
import re
import sys
from datetime import datetime

import numpy as np
import pandas as pd

from .evaluator import build_env, evaluate_ast
from .tdx_parser import parse_formula

__all__ = ["compile_indicator", "register", "load_registry"]

REGISTRY_PATH = pathlib.Path(__file__).with_name("registry.json")

_BUY_SELL_MARKERS = ("买", "卖", "首发")

# 【输出】/【参数说明】节内容(到下一个【 或 } 为止)。
# 【输出[^】]*】兼容【输出(对其他指标保持兼容)】变体;【对外输出】不匹配(简报口径)。
_SECTION_RE = re.compile(r"【(输出[^】]*|参数说明)】([\s\S]*?)(?=【|\})")

# 「参数名: ... 默认 N」(简报正则 参数名:.*?默认?(\d+) 的落体;数字可为小数)
_PARAM_RE = re.compile(
    r"([A-Za-z0-9_一-龥]+)\s*[:=]\s*.*?默认\s*[:=]?\s*(\d+(?:\.\d+)?)")

_ID_RE = re.compile(r"[A-Za-z0-9_一-龥]+")


# ---------------------------------------------------------------------------
# 合成行情 df(本任务私有;Task 2.4 会把公共生成器抽到 evaluator.synthetic_df)
# ---------------------------------------------------------------------------

def _syn_df(n=300):
    """300 根合成 OHLCV(与 Task 2.2 测试 _df 同款:种子随机游走)。"""
    rng = np.random.default_rng(7)
    c = pd.Series(10.0 + np.cumsum(rng.normal(0, 0.3, n)))
    return pd.DataFrame({
        "Open": c.shift(1).fillna(c.iloc[0]),
        "High": c + 0.3,
        "Low": c - 0.3,
        "Close": c,
        "Volume": pd.Series(rng.integers(1000, 2000, n), dtype=float),
    }, index=pd.bdate_range("2026-01-01", periods=n))


# ---------------------------------------------------------------------------
# 头部注释节提取
# ---------------------------------------------------------------------------

def _header_sections(text):
    """头部注释中的【输出】/【参数说明】节内容 → {节名: 文本}。"""
    return {m.group(1): m.group(2) for m in _SECTION_RE.finditer(text)}


def _extract_params(section):
    """【参数说明】节 → {参数名: 默认值};无节或匹配不到 → {}。"""
    params = {}
    if not section:
        return params
    for line in section.splitlines():
        m = _PARAM_RE.search(line)
        if m:
            v = m.group(2)
            params[m.group(1)] = int(v) if v.isdigit() else float(v)
    return params


def _direction(name):
    """direction 启发式(控制器裁决):卖→sell;买/首发→buy;其余→both。
    买/卖兼具按 sell 优先(与裁决列举顺序一致)。"""
    if "卖" in name:
        return "sell"
    if "买" in name or "首发" in name:
        return "buy"
    return "both"


def _extract_signals(outputs, declared):
    """signals = (输出名含 买/卖/首发)∪(头部【输出】节声明且为实际输出)。

    按 outputs 顺序去重输出 {name, direction};人工可在 registry.json 修正。"""
    declared_names = set(_ID_RE.findall(declared or ""))
    signals = []
    for nm in outputs:
        if any(m in nm for m in _BUY_SELL_MARKERS) or nm in declared_names:
            signals.append({"name": nm, "direction": _direction(nm)})
    return signals


# ---------------------------------------------------------------------------
# 对外接口
# ---------------------------------------------------------------------------

def compile_indicator(txt_path, code_prefix="600000"):
    """编译单个公式文件。

    返回 {
      "name":     公式名(文件名 stem),
      "source":   源文件路径,
      "outputs":  成功求值的输出语句名(按语句顺序),
      "params":   {可调参数名: 默认值}(【参数说明】节提取,无则 {}),
      "signals":  [{name, direction: buy|sell|both}],
      "warnings": 解析器警告列表(parse_formula 原样),
      "errors":   [{name, line, category, reason}](求值失败语句;非空=compile
                  失败),category ∈ not_implemented/name_error/其他异常类名,
      "ok":       errors 为空(全语句可求值),
    }

    code_prefix 语义与 2.2 CODELIKE 一致(如 '600000'、'300001')。
    """
    txt_path = pathlib.Path(txt_path)
    text = txt_path.read_text(encoding="utf-8", errors="ignore")
    parsed = parse_formula(text)

    env = build_env(_syn_df(300))
    outputs, errors = [], []
    for st in parsed["statements"]:
        try:
            env[st["name"]] = evaluate_ast(st["expr"], env,
                                           code_prefix=code_prefix)
        except NotImplementedError as e:
            errors.append({"name": st["name"], "line": st["line"],
                           "category": "not_implemented", "reason": str(e)})
        except NameError as e:
            errors.append({"name": st["name"], "line": st["line"],
                           "category": "name_error", "reason": str(e)})
        except Exception as e:  # 其他异常同样跳过登记,compile 保持全函数
            errors.append({"name": st["name"], "line": st["line"],
                           "category": type(e).__name__, "reason": str(e)})
        else:
            if st["kind"] == "output":
                outputs.append(st["name"])

    sections = _header_sections(text)
    return {
        "name": txt_path.stem,
        "source": str(txt_path),
        "outputs": outputs,
        "params": _extract_params(sections.get("参数说明", "")),
        "signals": _extract_signals(outputs, sections.get("输出", "")),
        "warnings": parsed["warnings"],
        "errors": errors,
        "ok": not errors,
    }


def register(txt_path, code_prefix="600000"):
    """编译并写入 registry.json(同名覆盖)。

    部分注册语义(控制器裁决):只要有 ≥1 个输出成功求值即写入并返回 True,
    entry 含 "partial"(存在 unsupported 即 true)与 "unsupported"(编译
    错误清单,结构与 compile 的 errors 一致);outputs 为空(全部语句失败)
    才拒绝写入、错误清单打印 stderr 并返回 False(既有同名条目原样保留)。
    """
    c = compile_indicator(txt_path, code_prefix=code_prefix)
    if not c["outputs"]:
        print(f"[registry] {c['name']} compile 失败:无任何输出成功求值"
              f"({len(c['errors'])} 条错误),拒绝写入 registry.json:",
              file=sys.stderr)
        for e in c["errors"]:
            print(f"  - 行 {e['line']} {e['name']}: [{e['category']}] {e['reason']}",
                  file=sys.stderr)
        return False
    _write_entry(c["name"], {
        "source": c["source"],
        "outputs": c["outputs"],
        "signals": c["signals"],
        "params": c["params"],
        "compiled_at": datetime.now().isoformat(timespec="seconds"),
        "unsupported": c["errors"],
        "partial": bool(c["errors"]),
    })
    return True


def _write_entry(name, entry):
    reg = load_registry()
    reg[name] = entry
    REGISTRY_PATH.write_text(
        json.dumps(reg, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")


def load_registry():
    """读 registry.json → {名称: {source, outputs, signals, params, compiled_at,
    unsupported, partial}}。

    文件不存在返回 {}(供流水线首跑/check-new 比对);
    JSON 损坏则抛 JSONDecodeError(真实问题应暴露)。
    """
    if not REGISTRY_PATH.exists():
        return {}
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
