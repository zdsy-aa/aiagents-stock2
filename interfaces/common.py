"""Phase4 公共约定:分析结果字段、情景模板、接口错误包装、选股统一输出列。

本模块只放「跨接口共享的常量与纯函数」,不含任何业务取数逻辑。

约定(Phase4 前置裁决 R4-A / R4-B):
- 接口失败约定(R4-A):数据/依赖缺失抛 RuntimeError(消息含原因,统一走
  :func:`api_error` 包装,消息含接口名);输入非法抛 ValueError;AI 调用失败
  由接口内部转成结构化降级(``degraded=True`` + ``degraded_reason``),不抛异常。
- 情景模板(R4-B)字段固定:上涨 trigger/confirm/target/invalidate;
  震荡 trigger/observe/invalidate;下跌 trigger/risk/end;
  三类情景均必填 trigger 与 invalidate。
"""

# AnalysisResult 字段常量:interfaces.analyze.analyze_stock 返回 dict 的完整键集合
# (顺序即报告渲染顺序,消费方按此结构取值,缺失项不得省略键)。
ANALYSIS_KEYS = [
    "symbol",
    "name",
    "period",
    "generated_at",
    "current_state",
    "trend",
    "chip",
    "capital",
    "industry",
    "news",
    "signals",
    "scenarios",
    "evidence",
    "degraded",
    "degraded_reason",
]

# 批量选股统一输出列(interfaces.screen.screen_stocks 返回 DataFrame 的列顺序)。
SCREEN_RESULT_COLS = ["代码", "名称", "信号", "得分", "备注"]

# 情景类型名与字段集(R4-B);SCENARIO_DEFAULTS 用于构造时补空串占位。
SCENARIO_NAMES = ("上涨", "震荡", "下跌")
SCENARIO_FIELDS = (
    "name",
    "trigger",
    "confirm",
    "target",
    "invalidate",
    "observe",
    "risk",
    "end",
)


def Scenario(
    name,
    trigger="",
    confirm="",
    target="",
    invalidate="",
    observe="",
    risk="",
    end="",
):
    """构造单个情景 dict(R4-B),返回含 SCENARIO_FIELDS 全部 8 键的普通 dict。

    参数按情景类型选填,但 ``trigger`` 与 ``invalidate`` 三类情景均必填:
    上涨填 confirm/target,震荡填 observe,下跌填 risk/end。
    ``name`` 须为 上涨/震荡/下跌 之一(允许「上涨情景」「A-上涨」等含关键词的写法),
    否则抛 ValueError;必填字段为空(或非字符串)抛 ValueError。
    未填字段返回空串占位,便于消费方按固定列渲染。
    """
    if not isinstance(name, str) or not any(k in name for k in SCENARIO_NAMES):
        raise ValueError(
            f"情景 name 非法:{name!r},应为 {'/'.join(SCENARIO_NAMES)} 之一"
        )
    for field, value in (("trigger", trigger), ("invalidate", invalidate)):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"情景 {field} 必填且不能为空:{value!r}")
    return {
        "name": name.strip(),
        "trigger": trigger,
        "confirm": confirm,
        "target": target,
        "invalidate": invalidate,
        "observe": observe,
        "risk": risk,
        "end": end,
    }


def api_error(api_name, e):
    """把底层异常包装为带接口名的 RuntimeError(R4-A),由调用方 raise。

    用法::

        try:
            ...
        except SomeError as exc:
            raise api_error("analyze_stock", exc)

    返回的 RuntimeError 消息形如 ``[analyze_stock] 接口调用失败:ValueError: 坏输入``,
    原始异常挂在 ``__cause__`` 上,不丢失根因。
    """
    err = RuntimeError(f"[{api_name}] 接口调用失败:{type(e).__name__}: {e}")
    err.__cause__ = e
    return err
