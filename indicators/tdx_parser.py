"""通达信公式解析器。语料验收:32 个公式文件零语法错误
(位于 /home/tdxback/通达信指标/20260424001/tdx_v4_standalone,排除 5 个说明文件)。

语法面(与简报一致):
- 语句:`NAME:EXPR;`(输出)/ `NAME:=EXPR;`(中间);语句可跨行
- `{...}` 块注释,可多行;未闭合的 `{` 按行容错(整行视为注释)
- 修饰符:语句(输出或中间)尾部 `,NODRAW` / `,COLORXXXX` / `,LINETHICKn` /
  `,DOTLINE` / `,VOLSTICK` / `,COLORSTICK` / `,DRAWNULL` 等(解析后丢弃,记入语句 raw;
  语料含 `成交额:=V*C/100,NODRAW;` 这类 := 带修饰符的写法)
- 表达式优先级(低→高):OR(10) > AND(20) > NOT(30,一元) > 比较(40:
  >= <= > < = != <>) > 加减(50) > 乘除(60) > 一元负(70) > 原子
- 原子:数字(含小数)、字符串字面量('...')、变量名(中文/英文标识符,
  [A-Za-z_一-龥][A-Za-z0-9_一-龥]*)、函数调用 FUNC(arg1,...,argN)、括号、
  三元 IF(cond,a,b)(特化为 ternary 节点)、NOT(x)(特化为 not 节点)

AST 节点(与简报一致,供 Task 2.2 求值器依赖):
  {"op": "num", "val": 1.0}
  {"op": "str", "val": "3"}
  {"op": "var", "name": "CLOSE"}
  {"op": "call", "func": "REF", "args": [...]}
  {"op": "bin", "oper": "+", "left": ..., "right": ...}
  {"op": "ternary", "cond": ..., "then": ..., "else": ...}
  {"op": "not", "expr": ...}
  {"op": "neg", "expr": ...}   # 一元负(简报未定名,实现取 neg)

暂不支持特性(逐条登记;遇之跳过该语句并计 warning,不中断整文件;
语料实测零 syntax_error,全部 warnings 属于下列类别):
1. draw_stmt:DRAW*/STICKLINE 等绘图语句(STICKLINE / DRAWTEXT / DRAWTEXT_FIX /
   DRAWBAND / DRAWICON,无 NAME: 头的函数调用语句头)—— 语料 330 处
2. digit_id:数字开头的标识符 —— 语料特例:六脉神剑V5 的 6红原始/5红原始/
   6红首发原/5红首发原/6红距上次/5红距上次(简报标识符正则不允许数字开头,
   按 R2.1-A 登记跳过,是否扩语法面由控制器裁决)
3. bare_output:裸表达式输出语句(无 NAME: 头,如 `CLOSE,COLORWHITE,NODRAW;`)
   —— 语料 1 处(缠论_主图V9 末行),R2.1-A 登记
4. recursive_assign:递归 :=(RHS 中引用自身变量名,求值层禁止;解析层检测跳过)
5. 数组下标 `X[1]`(语料 0 处,防御性检测)
6. `#` 预处理指令(语料 0 处,防御性检测)
"""
import bisect
import re

__all__ = ["parse_formula"]

# ---------------------------------------------------------------------------
# 词法
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(
    r"""
      (?P<num>\d+\.?\d*)
    | (?P<str>'[^'\n]*')
    | (?P<id>[A-Za-z_一-龥][A-Za-z0-9_一-龥]*)
    | (?P<op>:=|>=|<=|<>|!=|[-+*/()<>,;:={}\[\]#])
    """,
    re.X,
)

_DRAW_STMT_RE = re.compile(r"^(DRAW[A-Za-z0-9_]*|STICKLINE)$")


def _extract_comments(text, warnings):
    """剥离 {...} 块注释(可多行),返回(等价文本, 注释列表)。

    等价文本与原文本等长:注释内容替换为空格、换行保留,故词法偏移/行号
    与原文本一致(raw 切取可直接用原文本)。字符串字面量内的 `{` 不视为
    注释开始。未闭合的 `{` 按行容错:整行余下视为注释。
    """
    out = []
    comments = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "'":
            j = text.find("'", i + 1)
            if j == -1:  # 未闭合字符串:余下原样保留,由解析层报错
                out.append(text[i:])
                break
            out.append(text[i:j + 1])
            i = j + 1
        elif ch == "{":
            line = text.count("\n", 0, i) + 1
            j = text.find("}", i + 1)
            if j == -1:
                eol = text.find("\n", i + 1)
                j = eol if eol != -1 else n - 1
                warnings.append({
                    "line": line,
                    "category": "unclosed_comment",
                    "reason": "未闭合的 { 注释(按行容错)",
                    "raw": text[i:j + 1][:200],
                })
            comments.append({"text": text[i + 1:j], "line": line})
            out.append("".join("\n" if c == "\n" else " " for c in text[i:j + 1]))
            i = j + 1
        else:
            out.append(ch)
            i += 1
    return "".join(out), comments


class _Tok:
    __slots__ = ("kind", "value", "start", "end", "line")

    def __init__(self, kind, value, start, end, line):
        self.kind = kind
        self.value = value
        self.start = start
        self.end = end
        self.line = line


def _tokenize(text, warnings):
    """把(已剥离注释的)文本切成 token 列表,末尾追加 EOF 哨兵(None)。"""
    line_starts = [0]
    for m in re.finditer(r"\n", text):
        line_starts.append(m.start() + 1)
    toks = []
    i, n = 0, len(text)
    while i < n:
        m = _TOKEN_RE.match(text, i)
        if m is None:
            if text[i].isspace():
                i += 1
            else:
                warnings.append({
                    "line": bisect.bisect_right(line_starts, i),
                    "category": "lex_error",
                    "reason": f"无法识别的字符 {text[i]!r}",
                    "raw": text[max(0, i - 10):i + 10],
                })
                i += 1
            continue
        toks.append(_Tok(
            m.lastgroup, m.group(), m.start(), m.end(),
            bisect.bisect_right(line_starts, m.start()),
        ))
        i = m.end()
    toks.append(None)  # EOF 哨兵
    return toks


# ---------------------------------------------------------------------------
# 语法
# ---------------------------------------------------------------------------

# 二元运算符优先级(低→高)。NOT/一元负为前缀,不在此表。
_BIN_PREC = {
    "OR": 10,
    "AND": 20,
    "=": 40, "!=": 40, "<>": 40, ">": 40, ">=": 40, "<": 40, "<=": 40,
    "+": 50, "-": 50,
    "*": 60, "/": 60,
}
_NOT_PREC = 30   # 一元 NOT 的绑定优先级
_NEG_PREC = 70   # 一元负的绑定优先级


class _ParseError(Exception):
    """语法错误:该语句按未登记语法错误处理(语料验收不允许出现)。"""


class _SkipStatement(Exception):
    """已登记"暂不支持"特性:跳过该语句,计 warning。"""

    def __init__(self, category, reason):
        super().__init__(reason)
        self.category = category
        self.reason = reason


def _contains_var(node, name):
    """AST 中是否出现名为 name 的变量引用(用于递归 := 检测)。"""
    if not isinstance(node, dict):
        return False
    op = node.get("op")
    if op == "var":
        return node.get("name") == name
    if op == "bin":
        return _contains_var(node["left"], name) or _contains_var(node["right"], name)
    if op == "ternary":
        return any(_contains_var(node[k], name) for k in ("cond", "then", "else"))
    if op in ("not", "neg"):
        return _contains_var(node["expr"], name)
    if op == "call":
        return any(_contains_var(a, name) for a in node["args"])
    return False


class _Parser:
    def __init__(self, text):
        self.text = text
        self.warnings = []
        clean, self.comments = _extract_comments(text, self.warnings)
        self.toks = _tokenize(clean, self.warnings)
        self.pos = 0

    # ---- token 游标 ----

    def _at_end(self):
        return self.toks[self.pos] is None

    def _peek(self, offset=0):
        idx = self.pos + offset
        return self.toks[idx] if idx < len(self.toks) else None

    def _next(self):
        t = self.toks[self.pos]
        if t is not None:
            self.pos += 1
        return t

    def _is_op(self, value, offset=0):
        t = self._peek(offset)
        return t is not None and t.kind == "op" and t.value == value

    def _expect_op(self, value):
        if not self._is_op(value):
            t = self._peek()
            got = t.value if t else "<EOF>"
            raise _ParseError(f"期望 {value!r},遇到 {got!r}")
        return self._next()

    # ---- 语句级 ----

    def _statements(self):
        stmts = []
        while not self._at_end():
            if self._is_op(";"):  # 空语句
                self._next()
                continue
            try:
                s = self._parse_statement()
                if s is not None:
                    stmts.append(s)
            except _SkipStatement as e:
                self._warn(e.category, e.reason)
                self._skip_to_semicolon()
            except _ParseError as e:
                self._warn("syntax_error", str(e))
                self._skip_to_semicolon()
        return stmts

    def _warn(self, category, reason):
        t = self._peek()
        line = t.line if t else (self.text.count("\n") + 1)
        raw = self._statement_snippet()
        self.warnings.append({"line": line, "category": category,
                              "reason": reason, "raw": raw})

    def _statement_snippet(self):
        """当前语句余下部分的原文切片(截断 200 字符),供登记/报告用。"""
        t = self._peek()
        if t is None:
            return ""
        end = t.start
        for tok in self.toks[self.pos:]:
            if tok is not None and tok.kind == "op" and tok.value == ";":
                end = tok.end
                break
        return self.text[t.start:end][:200]

    def _skip_to_semicolon(self):
        while not self._at_end():
            t = self._next()
            if t is not None and t.kind == "op" and t.value == ";":
                return

    def _parse_statement(self):
        start_tok = self._peek()
        if start_tok is None:
            return None
        if start_tok.kind == "num":
            raise _SkipStatement(
                "digit_id",
                f"语句头 {start_tok.value!r} 不是标识符(数字开头的标识符暂不支持)",
            )
        if start_tok.kind != "id":
            if start_tok.kind == "op" and start_tok.value == "#":
                raise _SkipStatement("preprocessor", "# 预处理指令暂不支持")
            raise _ParseError(f"非法语句头 {start_tok.value!r}")
        name = start_tok.value
        self._next()

        t = self._peek()
        if t is None:
            raise _ParseError("语句未完成:缺少 : 或 := 与表达式")
        if t.kind == "op" and t.value == "(":
            if _DRAW_STMT_RE.match(name):
                raise _SkipStatement("draw_stmt", f"绘图语句 {name}(...) 暂不支持")
            raise _ParseError(f"意外的函数调用语句头 {name}(...)")
        if t.kind == "op" and t.value == ":":
            self._next()
            if self._is_op("="):  # `:=` 被空格拆开的容错
                self._next()
                kind = "assign"
            else:
                kind = "output"
        elif t.kind == "op" and t.value == ":=":
            self._next()
            kind = "assign"
        else:
            raise _SkipStatement(
                "bare_output",
                f"裸表达式输出语句(无 NAME: 头,以 {t.value!r} 续接)暂不支持",
            )

        expr = self._parse_expr()

        # 注意:必须在消费 ';' 之前抛出,否则外层 skip 会吞掉下一条语句
        if kind == "assign" and _contains_var(expr, name):
            raise _SkipStatement("recursive_assign", f"递归 :={name} 自引用)暂不支持")

        # 修饰符:输出与中间语句均可带(语料:成交额:=V*C/100,NODRAW;)
        if self._is_op(","):
            while self._is_op(","):
                self._next()
                mt = self._peek()
                if mt is None or mt.kind not in ("id", "num", "str"):
                    raise _ParseError("修饰符位置出现非法记号")
                self._next()

        end_tok = self._peek()
        if end_tok is not None and end_tok.kind == "op" and end_tok.value == ";":
            self._next()
            end_off = end_tok.end
        elif end_tok is None:
            end_off = self.toks[self.pos - 1].end  # 文件末缺分号:容错
        else:
            raise _ParseError(f"期望 ';',遇到 {end_tok.value!r}")

        return {
            "kind": kind,
            "name": name,
            "expr": expr,
            "raw": self.text[start_tok.start:end_off],
            "line": start_tok.line,
        }

    # ---- 表达式级(优先级爬升) ----

    def _parse_expr(self, min_prec=0):
        t = self._peek()
        if t is None:
            raise _ParseError("表达式意外结束")
        if t.kind == "op" and t.value == "-":
            self._next()
            node = {"op": "neg", "expr": self._parse_expr(_NEG_PREC)}
        elif t.kind == "id" and t.value == "NOT":
            # 裸 NOT 前缀(语料均为 NOT(...) 调用形式;此处为语法面完整性)
            self._next()
            node = {"op": "not", "expr": self._parse_expr(_NOT_PREC)}
        else:
            node = self._parse_atom()
        while True:
            t = self._peek()
            if t is None:
                break
            if t.kind == "id" and t.value in ("OR", "AND"):
                prec = _BIN_PREC[t.value]
            elif t.kind == "op" and t.value in _BIN_PREC:
                prec = _BIN_PREC[t.value]
            else:
                break
            if prec < min_prec:
                break
            self._next()
            right = self._parse_expr(prec + 1)  # 左结合
            node = {"op": "bin", "oper": t.value, "left": node, "right": right}
        return node

    def _parse_atom(self):
        t = self._peek()
        if t is None:
            raise _ParseError("表达式意外结束")
        if t.kind == "num":
            self._next()
            nxt = self._peek()
            # 字符级紧邻(无空白)才是数字开头标识符(如 6红原始);
            # 空白分隔的 `0.99 AND` 不是
            if nxt is not None and nxt.kind == "id" and nxt.start == t.end:
                raise _SkipStatement(
                    "digit_id",
                    f"数字开头的标识符 {t.value}{nxt.value} 暂不支持",
                )
            return {"op": "num", "val": float(t.value)}
        if t.kind == "str":
            self._next()
            return {"op": "str", "val": t.value[1:-1]}
        if t.kind == "op" and t.value == "(":
            self._next()
            e = self._parse_expr()
            self._expect_op(")")
            return e
        if t.kind == "id":
            name = t.value
            self._next()
            if self._is_op("("):
                self._next()
                args = []
                if not self._is_op(")"):
                    while True:
                        args.append(self._parse_expr())
                        if not self._is_op(","):
                            break
                        self._next()
                self._expect_op(")")
                if name == "IF" and len(args) == 3:  # 三元特化
                    return {"op": "ternary", "cond": args[0],
                            "then": args[1], "else": args[2]}
                if name == "NOT" and len(args) == 1:  # 一元非特化
                    return {"op": "not", "expr": args[0]}
                return {"op": "call", "func": name, "args": args}
            if self._is_op("["):
                raise _SkipStatement("array_index", "数组下标暂不支持")
            return {"op": "var", "name": name}
        raise _ParseError(f"意外的记号 {t.value!r}")


# ---------------------------------------------------------------------------
# 对外接口
# ---------------------------------------------------------------------------

def parse_formula(text):
    """解析通达信公式文本。

    返回 dict{name, statements, comments, warnings}:
      name       公式名(当前固定 "(unnamed)",待语料命名规范后补充)
      statements [{kind, name, expr, raw, line}],kind ∈ {"output", "assign"}
      comments   [{text, line}]
      warnings   [{line, category, reason, raw}],category 见模块头登记
    """
    p = _Parser(text)
    return {
        "name": "(unnamed)",
        "statements": p._statements(),
        "comments": p.comments,
        "warnings": p.warnings,
    }
