#!/usr/bin/env python3
"""指标增量流水线 CLI(Task 2.4):check-new / run / run-all / smoke / docs。

子命令:
  check-new            输出「新增指标」清单(规则见 find_new_names)
  run <名称> [--code]  定位公式 → 冒烟 → 注册 → 文档(partial 允许成功并标注)
  run-all [--code]     语料 32 个公式文件全部 编译+冒烟+注册(不生成文档)
  smoke <名称> [--code] 仅冒烟(合成 df 300 根,输出全 finite 且长度=n)
  docs <名称> [--code] 生成单指标文档 docs/indicators/<名称>.md(Task 2.5)

docs 语义(Task 2.5,控制器裁决):
  registry 有该名称条目 → 直接渲染;没有 → 先自动注册(内部走 run 的注册
  逻辑:文件 register / 内置公式手工条目)→ 再渲染;两者都失败 → 报错到
  stderr 并 exit 1。渲染口径见 _render_doc 模块注释。

公式定位顺序(控制器裁决):
  1. registry.json 条目 source(文件路径或 "builtin:名")
  2. 公式库 FORMULA_ROOT 下 stem 精确匹配(排序保证确定性)
  3. BUILTIN_FORMULAS 内置公式(公式库无标准文件时的兜底,如 MACD)
  4. 公式库 FORMULA_ROOT 下 rglob(f"{名称}*.txt") 首个命中(排序)
  都未命中 → exit 1。

冒烟判据(控制器裁决):每个输出 Series 长度=n 且 np.isfinite 全 True
(标量输出判 finite)。落体:rolling 函数(MA 等)的头部预热窗 NaN 是通达信
正常语义(语料 K_MA60/K_MA120/六脉神剑V5 均线),严格全 finite 会把参考
对齐指标判为冒烟失败——故非有限值只允许出现在开头连续预热段(首个 finite
之后必须全 finite;全部非有限仍判失败)。
partial 指标(有 unsupported)允许 run 成功,但输出与报告标明 partial;
冒烟失败(非有限值/长度不符)则 run 不注册、exit 1。

公式库(/home/tdxback/通达信指标/)为仓库外只读数据,本脚本不改其中任何文件;
registry.json 写入走 indicators.registry 既有语义(同名覆盖)。
"""
import argparse
import json
import pathlib
import re
import sys
from datetime import datetime

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np
import pandas as pd

from indicators import BUILTIN_FORMULAS, load_alias_rules, load_registry
from indicators.evaluator import build_env, evaluate_ast, synthetic_df
from indicators.registry import compile_indicator, register
from indicators.tdx_parser import parse_formula

FORMULA_ROOT = pathlib.Path("/home/tdxback/通达信指标")
ADD_NEW_TXT = FORMULA_ROOT / "add_new.txt"
ADD_ZB_TXT = FORMULA_ROOT / "add_zb.txt"
ALL_TXT = FORMULA_ROOT / "all.txt"

# run-all 语料范围(与 corpus_test.py 口径一致:排除说明文件后恰 32 个)
CORPUS = FORMULA_ROOT / "20260424001" / "tdx_v4_standalone"
CORPUS_SKIP_DIR = "99_说明手册"
CORPUS_SKIP_FILES = {"导入说明_必读.txt"}

SMOKE_N = 300

# 单指标文档输出目录(Task 2.5;相对仓库根,与 cwd 无关)
DOCS_DIR = REPO_ROOT / "docs" / "indicators"


# ---------------------------------------------------------------------------
# check-new 归并判新
# ---------------------------------------------------------------------------

def _canonical(name, rules):
    """aliases 双向归一到规范名(规范名取每对末元素)。"""
    for pair in rules.get("aliases", []):
        if name in pair:
            return pair[-1]
    return name


def _family_of(name, rules):
    for fam in rules.get("families", []):
        if name in fam:
            return fam
    return None


def find_new_names(candidates, registry_names, all_lines, rules):
    """归并判新(控制器裁决口径)。

    candidates = add_new.txt∪add_zb.txt 名称(顺序保留、调用方去重);
    registry_names = registry.json 名称;all_lines = all.txt 行;
    两者均先在内存中按 alias_rules 归一(不改任何文件)。

    判新:
      - 规范名命中 registry → 已注册,跳过(aliases 双向归一的落点);
      - 属于某 family 且同族任一成员命中(registry ∪ all.txt)→ 已存在,跳过;
      - 其余 → 新增。
    注:all.txt 是厂商在册名录,不是「已转换」集合——名录内但未注册的名称
    (如 MACD)仍判为新增,否则增量入口对任何在册名永久失效。
    """
    rules = rules or {}
    reg = {_canonical(n, rules) for n in registry_names}
    alln = {_canonical(n, rules) for n in all_lines}
    union = reg | alln
    new_names, seen = [], set()
    for raw in candidates:
        c = raw.strip()
        if not c:
            continue
        canon = _canonical(c, rules)
        if canon in seen:
            continue
        seen.add(canon)
        if canon in reg:
            continue
        fam = _family_of(c, rules)
        if fam is not None and any(m in union for m in fam):
            continue  # 同族任一命中(registry 或 all.txt)即视为已存在
        new_names.append(c)
    return new_names


def _read_names(path):
    if not path.exists():
        return []
    return [ln.strip() for ln in
            path.read_text(encoding="utf-8", errors="ignore").splitlines()
            if ln.strip()]


def cmd_check_new():
    rules = load_alias_rules()
    candidates = _read_names(ADD_NEW_TXT) + _read_names(ADD_ZB_TXT)
    new_names = find_new_names(candidates, list(load_registry().keys()),
                               _read_names(ALL_TXT), rules)
    for n in new_names:
        print(n)
    if new_names:
        print(f"[check-new] 新增 {len(new_names)} 个: {new_names}",
              file=sys.stderr)
    else:
        print("[check-new] 无新增(exit 0)", file=sys.stderr)
    return 0


# ---------------------------------------------------------------------------
# 公式定位与求值(冒烟共用)
# ---------------------------------------------------------------------------

def _locate(name):
    """定位公式文本。返回 {kind: file|builtin, path|None, text, source}
    或 None(未命中)。顺序:registry source → stem 精确 → 内置 → 前缀。"""
    reg = load_registry()
    if name in reg:
        src = reg[name].get("source")
        if src:
            if src.startswith("builtin:"):
                bname = src.split(":", 1)[1]
                if bname in BUILTIN_FORMULAS:
                    return {"kind": "builtin", "path": None,
                            "text": BUILTIN_FORMULAS[bname], "source": src}
            p = pathlib.Path(src)
            if p.exists():
                return {"kind": "file", "path": p,
                        "text": p.read_text(encoding="utf-8", errors="ignore"),
                        "source": str(p)}
    for p in sorted(FORMULA_ROOT.rglob(f"{name}.txt")):
        if p.stem == name:
            return {"kind": "file", "path": p,
                    "text": p.read_text(encoding="utf-8", errors="ignore"),
                    "source": str(p)}
    if name in BUILTIN_FORMULAS:
        return {"kind": "builtin", "path": None,
                "text": BUILTIN_FORMULAS[name], "source": f"builtin:{name}"}
    hits = sorted(FORMULA_ROOT.rglob(f"{name}*.txt"))
    if hits:
        p = hits[0]
        return {"kind": "file", "path": p,
                "text": p.read_text(encoding="utf-8", errors="ignore"),
                "source": str(p)}
    return None


def _eval_text(text, code_prefix, n=SMOKE_N):
    """对合成 df 逐语句隔离求值(与 compile_indicator 同口径),
    返回 (outputs 值 dict, errors 清单)。"""
    parsed = parse_formula(text)
    env = build_env(synthetic_df(n))
    outputs, errors = {}, []
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
        except Exception as e:
            errors.append({"name": st["name"], "line": st["line"],
                           "category": type(e).__name__, "reason": str(e)})
        else:
            if st["kind"] == "output":
                outputs[st["name"]] = env[st["name"]]
    return outputs, errors


def smoke_violations(outputs, n=SMOKE_N):
    """冒烟判据:每个输出 Series 长度=n 且 np.isfinite 全 True;标量输出判
    finite。非有限值只允许出现在开头连续预热段(rolling 窗口头部 NaN,通达信
    正常语义);首个 finite 之后出现非有限值、或全部非有限 → 违规。
    返回违规描述列表(空=通过)。"""
    viol = []
    for nm, v in outputs.items():
        if isinstance(v, pd.Series):
            if len(v) != n:
                viol.append(f"{nm}: 长度 {len(v)} != {n}")
                continue
            a = v.to_numpy()
            finite = np.isfinite(a)
            if not finite.any():
                viol.append(f"{nm}: 全部非有限")
                continue
            first_finite = int(np.flatnonzero(finite)[0])
            if not finite[first_finite:].all():
                first_bad = int(np.flatnonzero(~finite[first_finite:])[0])
                viol.append(f"{nm}: 第 {first_finite + first_bad} 根出现非有限值"
                            f"(仅允许头部预热窗 NaN)")
        elif np.isscalar(v):
            if not np.isfinite(v):
                viol.append(f"{nm}: 非有限标量 {v!r}")
        else:
            viol.append(f"{nm}: 非 Series/标量类型 {type(v).__name__}")
    return viol


# ---------------------------------------------------------------------------
# 注册(文件走 2.3 register;内置公式手工写入同构条目)
# ---------------------------------------------------------------------------

def _registry_path():
    import indicators.registry as registry_mod
    return pathlib.Path(registry_mod.__file__).with_name("registry.json")


def _write_builtin_entry(name, outputs, errors):
    """内置公式注册:source="builtin:名",条目结构与 2.3 七键一致。
    内置 MACD 无 买/卖/首发 输出与【输出】节声明 → signals=[];无【参数说明】
    节 → params={}。"""
    reg_path = _registry_path()
    reg = load_registry()
    reg[name] = {
        "source": f"builtin:{name}",
        "outputs": list(outputs.keys()),
        "signals": [],
        "params": {},
        "compiled_at": datetime.now().isoformat(timespec="seconds"),
        "unsupported": errors,
        "partial": bool(errors),
    }
    reg_path.write_text(
        json.dumps(reg, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")


# ---------------------------------------------------------------------------
# 子命令实现
# ---------------------------------------------------------------------------

def cmd_smoke(name, code_prefix="600000"):
    loc = _locate(name)
    if loc is None:
        print(f"[smoke] 未找到公式: {name!r}(registry 无条目、公式库无匹配、"
              f"无内置公式)", file=sys.stderr)
        return 1
    outputs, errors = _eval_text(loc["text"], code_prefix)
    if not outputs:
        print(f"[smoke] {name}: 无任何输出成功求值"
              f"({len(errors)} 条错误)", file=sys.stderr)
        return 1
    viol = smoke_violations(outputs)
    partial = bool(errors)
    for nm, v in outputs.items():
        if isinstance(v, pd.Series):
            desc = f"Series 长度 {len(v)}"
        else:
            desc = f"标量 {v!r}"
        print(f"  {nm}: {desc}")
    if viol:
        print(f"[smoke] {name} 冒烟失败: {viol}", file=sys.stderr)
        return 1
    print(f"[smoke] {name}: {len(outputs)} 个输出全部通过"
          f"{'; partial(unsupported %d 条)' % len(errors) if partial else ''}")
    return 0


def cmd_run(name, code_prefix="600000", generate_doc=True):
    """run 子命令:定位 → 冒烟 → 注册 →(注册成功后)文档生成。

    generate_doc=True 时在 register 成功后追加 cmd_docs 的渲染逻辑
    (_generate_doc),使一条 `run <名称>` 完成 转换→冒烟→注册→文档;
    cmd_docs 的自动注册路径传 False(文档由 cmd_docs 统一生成一次)。
    register 失败(0 输出)照旧 exit 1 且不生成文档。
    """
    loc = _locate(name)
    if loc is None:
        print(f"[run] 未找到公式: {name!r}(registry 无条目、公式库无匹配、"
              f"无内置公式)", file=sys.stderr)
        return 1
    if loc["kind"] == "builtin":
        print(f"[locate] {name}: 公式库无标准文件 → 内置公式"
              f"(source={loc['source']})")
    else:
        print(f"[locate] {name}: {loc['path']}")

    outputs, errors = _eval_text(loc["text"], code_prefix)
    if not outputs:
        print(f"[run] {name} compile 失败:无任何输出成功求值"
              f"({len(errors)} 条错误),不注册", file=sys.stderr)
        for e in errors[:5]:
            print(f"  - 行 {e['line']} {e['name']}: [{e['category']}] "
                  f"{e['reason']}", file=sys.stderr)
        return 1
    viol = smoke_violations(outputs)
    if viol:
        print(f"[smoke] {name} 冒烟失败: {viol}", file=sys.stderr)
        print(f"[run] {name} 冒烟不通过,不注册(exit 1)", file=sys.stderr)
        return 1
    partial = bool(errors)
    print(f"[smoke] {name}: {len(outputs)} 个输出全部通过"
          f"(长度 {SMOKE_N},全 finite,允许头部预热窗 NaN)")

    if loc["kind"] == "file":
        ok = register(loc["path"], code_prefix=code_prefix)
        if not ok:
            print(f"[run] {name} register 拒绝写入(0 输出)", file=sys.stderr)
            return 1
        reg_name = loc["path"].stem   # register 按文件 stem 登记
    else:
        _write_builtin_entry(name, outputs, errors)
        reg_name = name
    print(f"[register] {name}: outputs={list(outputs.keys())}, "
          f"partial={partial}")
    if partial:
        print(f"[run] {name} 为 partial 指标(unsupported {len(errors)} 条),"
              f"已标注 partial=true:")
        for e in errors[:5]:
            print(f"  - 行 {e['line']} {e['name']}: [{e['category']}] "
                  f"{e['reason']}")
    if not generate_doc:
        print(f"[run] {name} 完成:转换→冒烟→注册 ✓")
        return 0
    entry = load_registry().get(reg_name)
    if entry is None:
        print(f"[run] {name} 警告:注册后 registry 查无 {reg_name!r} 条目,"
              f"文档未生成", file=sys.stderr)
        print(f"[run] {name} 完成:转换→冒烟→注册 ✓(文档未生成)")
        return 0
    _generate_doc(reg_name, entry)
    print(f"[run] {name} 完成:转换→冒烟→注册→文档 ✓")
    return 0


def cmd_run_all(code_prefix="600000"):
    files = sorted(f for f in CORPUS.rglob("*.txt")
                   if CORPUS_SKIP_DIR not in f.parts
                   and f.name not in CORPUS_SKIP_FILES)
    ok = partial = fail = 0
    for f in files:
        name = f.stem
        text = f.read_text(encoding="utf-8", errors="ignore")
        outputs, errors = _eval_text(text, code_prefix)
        if not outputs or smoke_violations(outputs):
            fail += 1
            print(f"[run-all] {name}: 冒烟失败/无输出,跳过注册")
            continue
        if not register(f, code_prefix=code_prefix):
            fail += 1
            print(f"[run-all] {name}: register 拒绝写入(0 输出)")
            continue
        if errors:
            partial += 1
            print(f"[run-all] {name}: registered(partial, unsupported "
                  f"{len(errors)} 条)")
        else:
            ok += 1
            print(f"[run-all] {name}: registered")
    print(f"[run-all] 完成: 共 {len(files)} 个公式文件,"
          f"ok={ok}, partial={partial}, fail={fail}")
    return 0  # 批量语义:跑完即 0,逐文件状态见上方清单


# ---------------------------------------------------------------------------
# 单指标文档生成(Task 2.5)
# ---------------------------------------------------------------------------
# 渲染口径(控制器裁决):
#   指标说明  = 头部注释【指标功能说明】原文要点(前 8 行);源文件无该节时
#               依次退到【功能说明】/【指标说明】/【原理】,再无则取头部注释
#               块原文首 8 行(分隔线不计),均无 →「待补充」;
#   原始公式  = 源文件语句原文(parse_formula 的 raw 切片,含修饰符,直接引用
#               源文件文本)代码块;
#   转换逻辑  =「逐语句 AST 求值,输出 N 个序列」+ unsupported 清单(如有,
#               逐条列出语句/类别/原因);
#   参数说明  = registry params(空 →「固定参数:公式内嵌默认;无独立可调参数」);
#   买入/卖出 = registry signals 按 direction 分组(buy/both 入买入,sell/both
#               入卖出;signals 整体为空 →「本指标无标准买卖信号,输出为状态量」,
#               单侧为空 →「本指标无标准{买入|卖出}信号,输出为状态量」);
#   适用周期/失效条件 = 头部注释含【适用周期】/【失效条件】则引用,否则「待补充」。
# 仅头部注释区(首个语句之前)参与节提取,正文注释不参与。
# 文档头元信息:出处=registry source;状态=已转换(partial 时标注 unsupported
# 条数);登记日期=registry compiled_at 的日期部分;类别按名称是否含中文给
# 中文组合指标/英文技术指标(启发式,模板占位符的落体)。

_TITLE_RE = re.compile(r"【([^】]+)】([\s\S]*?)(?=【|\})")
_DESC_TITLES = ("指标功能说明", "功能说明", "指标说明", "原理")
_BANNER_CHARS = set("=—-—* ")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _head_parts(text):
    """文本 → (头部注释区文本, 头部注释列表, 全量 parse 结果)。

    头部注释区 = 首个解析语句所在行之前的文本(正文注释不计入)。
    """
    parsed = parse_formula(text)
    stmts = parsed["statements"]
    if not stmts:
        head_text, head_end = text, text.count("\n") + 1
    else:
        head_end = stmts[0]["line"] - 1
        head_text = "".join(text.splitlines(keepends=True)[:head_end])
    comments = [c for c in parsed["comments"] if c["line"] <= head_end]
    return head_text, comments, parsed


def _title_sections(text):
    """【标题】...到下一个【 或 } 之前的文本 → {标题: 文本}。"""
    return {m.group(1).strip(): m.group(2) for m in _TITLE_RE.finditer(text)}


def _clean_lines(lines, limit=None):
    """去空行/去分隔线(==== 等)后的行列表,可截断到 limit 行。"""
    out = []
    for ln in lines:
        s = ln.strip()
        if not s or set(s) <= _BANNER_CHARS:
            continue
        out.append(s)
        if limit is not None and len(out) >= limit:
            break
    return out


def _description(head_text, head_comments):
    """头部注释 → 指标说明行(【指标功能说明】等优先,兜底头部注释原文)。"""
    secs = _title_sections(head_text)
    for title in _DESC_TITLES:
        if secs.get(title, "").strip():
            return _clean_lines(secs[title].splitlines(), limit=8)
    fallback = []
    for c in head_comments:
        fallback.extend(c["text"].splitlines())
    out = _clean_lines(fallback, limit=8)
    if len(out) > 1 and re.fullmatch(r"【[^】]+】", out[-1]):
        out.pop()  # 截断在下一个节的标题上时去掉悬空标题
    return out or ["待补充"]


def _quoted_section(head_text, title):
    """头部注释节原文(去分隔线);无该节 →「待补充」。"""
    sec = head_text and _title_sections(head_text).get(title, "")
    return _clean_lines(sec.splitlines()) if sec else ["待补充"]


def _md_cell(s):
    return str(s).replace("|", "\\|").replace("\n", " ")


def _conversion_lines(entry):
    outs = entry.get("outputs") or []
    lines = [f"逐语句 AST 求值,输出 {len(outs)} 个序列"
             f"(求值器 indicators/evaluator.py:evaluate_ast;"
             f"函数映射见 indicators/tdx_builtins.py):", ""]
    lines += [f"- {nm}" for nm in outs] or ["- (无)"]
    unsup = entry.get("unsupported") or []
    if unsup:
        lines += ["", f"未支持语句 {len(unsup)} 条(逐语句隔离求值,已跳过并登记;"
                      f"指标标记 partial=true):", "",
                  "| 行 | 语句 | 类别 | 原因 |",
                  "|----|------|------|------|"]
        for e in unsup:
            lines.append(f"| {e.get('line', '')} | {_md_cell(e.get('name', ''))} "
                         f"| {_md_cell(e.get('category', ''))} "
                         f"| {_md_cell(e.get('reason', ''))} |")
    return lines


def _params_lines(entry):
    params = entry.get("params") or {}
    if not params:
        return ["### 固定参数", "",
                "固定参数:公式内嵌默认;无独立可调参数", "",
                "### 可调整参数", "",
                "无(registry params 为空,源文件头部注释无【参数说明】节)"]
    lines = ["### 固定参数", "", "公式内嵌默认。", "",
             "### 可调整参数", "",
             "| 参数 | 默认值 |", "|------|--------|"]
    lines += [f"| {_md_cell(k)} | {v} |" for k, v in params.items()]
    return lines


def _signal_lines(entry, want, label):
    sigs = entry.get("signals") or []
    if not sigs:
        return ["本指标无标准买卖信号,输出为状态量"]
    hits = [s for s in sigs if s.get("direction") in want]
    if not hits:
        return [f"本指标无标准{label}信号,输出为状态量"]
    lines = [f"registry signals 中 direction ∈ {{{', '.join(want)}}} 的输出"
             f"({len(hits)} 个):", ""]
    lines += [f"- {s.get('name')}(direction={s.get('direction')})" for s in hits]
    return lines


def _render_doc(name, entry, loc):
    """registry 条目 + 源文件 → 文档文本(小节顺序遵循 docs/indicator_template.md)。"""
    text = loc["text"] if loc else None
    if text:
        head_text, head_comments, parsed = _head_parts(text)
        raws = [st["raw"] for st in parsed["statements"]]
    else:
        head_text, head_comments, raws = "", [], []
    source = str(entry.get("source") or "(未知)")
    unsup = entry.get("unsupported") or []
    date = (entry.get("compiled_at") or "")[:10] or \
        datetime.now().strftime("%Y-%m-%d")
    kind = "中文组合指标" if _CJK_RE.search(name) else "英文技术指标"
    status = "已转换" + (f"(partial:unsupported {len(unsup)} 条)" if unsup
                         else "")

    out = [f"# {name}", "",
           f"- 类别:{kind}",
           f"- 出处:{source}",
           f"- 状态:{status}",
           f"- 登记日期:{date}", "",
           "## 指标说明", ""]
    out += _description(head_text, head_comments)
    out += ["", "## 原始公式", ""]
    if raws:
        out += ["```"] + raws + ["```"]
    else:
        out.append("待补充(源文件未定位)")
    out += ["", "## 转换逻辑", ""] + _conversion_lines(entry)
    out += ["", "## 参数说明", ""] + _params_lines(entry)
    out += ["", "## 买入信号", ""] + _signal_lines(entry, ("buy", "both"), "买入")
    out += ["", "## 卖出信号", ""] + _signal_lines(entry, ("sell", "both"), "卖出")
    out += ["", "## 适用周期", ""] + _quoted_section(head_text, "适用周期")
    out += ["", "## 失效条件", ""] + _quoted_section(head_text, "失效条件")
    return "\n".join(out) + "\n"


def _generate_doc(name, entry):
    """按 registry 条目渲染并写出 docs/indicators/<名称>.md(渲染唯一出处)。

    cmd_docs 与 cmd_run(注册成功后追加文档)共用本函数,输出口径一致。
    """
    loc = _locate(name)
    if loc is None:
        print(f"[docs] 警告:未定位到源文件,原始公式/指标说明小节将标注待补充",
              file=sys.stderr)
    out_path = DOCS_DIR / f"{name}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(_render_doc(name, entry, loc), encoding="utf-8")
    print(f"[docs] {name}: 已生成 {out_path}(outputs "
          f"{len(entry.get('outputs') or [])} 个,partial="
          f"{bool(entry.get('partial'))})")


def cmd_docs(name, code_prefix="600000"):
    """生成 docs/indicators/<名称>.md。

    registry 有该名称条目 → 直接渲染;没有 → 先自动注册(内部走 cmd_run 的
    注册逻辑:文件 register / 内置公式手工条目)再渲染;注册或渲染失败 →
    报错到 stderr 并 exit 1。
    """
    entry = load_registry().get(name)
    if entry is None:
        print(f"[docs] registry 无 {name!r} 条目 → 先自动注册(run 逻辑)")
        # generate_doc=False:注册由 cmd_run 完成,文档由本函数统一生成一次
        if cmd_run(name, code_prefix, generate_doc=False) != 0:
            print(f"[docs] {name!r} 自动注册失败,无法生成文档(exit 1)",
                  file=sys.stderr)
            return 1
        reg = load_registry()
        entry = reg.get(name)
        if entry is None:  # 定位文件 stem 与名称不一致时按 stem 取
            loc = _locate(name)
            stem = loc["path"].stem if loc and loc.get("path") else None
            entry = reg.get(stem) if stem else None
        if entry is None:
            print(f"[docs] {name!r} 注册成功但 registry 查无对应条目,"
                  f"无法生成文档(exit 1)", file=sys.stderr)
            return 1
    _generate_doc(name, entry)
    return 0


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="indicator_pipeline",
        description="指标增量流水线 CLI(check-new / run / run-all / smoke / docs)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check-new", help="输出「新增指标」清单(add_new.txt∪"
                                      "add_zb.txt 归并后与 registry∪all.txt "
                                      "比对;无新增 exit 0)")

    p_run = sub.add_parser("run", help="定位公式→compile→冒烟→register→文档")
    p_run.add_argument("name")
    p_run.add_argument("--code", default="600000",
                       help="证券代码前缀(CODELIKE 编译期求值用)")

    p_all = sub.add_parser("run-all", help="语料 32 个公式文件全部 "
                                           "compile+smoke+register(不生成文档)")
    p_all.add_argument("--code", default="600000")

    p_smoke = sub.add_parser("smoke", help="仅冒烟(合成 df 300 根)")
    p_smoke.add_argument("name")
    p_smoke.add_argument("--code", default="600000")

    p_docs = sub.add_parser("docs", help="生成单指标文档 docs/indicators/"
                                         "<名称>.md(registry 无条目时先自动"
                                         "注册再生成)")
    p_docs.add_argument("name")
    p_docs.add_argument("--code", default="600000")

    args = parser.parse_args(argv)
    if args.cmd == "check-new":
        return cmd_check_new()
    if args.cmd == "run":
        return cmd_run(args.name, args.code)
    if args.cmd == "run-all":
        return cmd_run_all(args.code)
    if args.cmd == "smoke":
        return cmd_smoke(args.name, args.code)
    if args.cmd == "docs":
        return cmd_docs(args.name, args.code)
    parser.error(f"未知子命令 {args.cmd!r}")


if __name__ == "__main__":
    sys.exit(main())
