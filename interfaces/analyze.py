# -*- coding: utf-8 -*-
"""Phase4 统一接口:单股分析 analyze_stock + 三情景模板生成(R4-B)。

薄封装既有分析流 views/analysis_runner.run_stock_analysis:
- 取数与 AI 团队结论全部复用该函数(其内部已 db.save_analysis 落库,本模块
  **不重复落库**);
- current_state/trend/chip/capital/industry/news/signals 从返回 dict 的
  agents_results / final_decision 提取,映射不到的填「未提供」(不编造);
- scenarios 由 build_scenarios(最终结论文本) 经 DeepSeek 一次小调用生成,
  prompt 段定义于 deepseek_client.SCENARIO_PROMPT_TEMPLATE(版本
  SCENARIO_PROMPT_VERSION,与 R4-C/4.4 联动);
- AI 调用失败(网络/超时/解析失败)→ degraded=True + degraded_reason,其余
  字段保留,不抛异常(R4-A);仅输入非法(code/period)抛 ValueError。

已知限制(薄封装不改被封装行为):run_stock_analysis 是 Streamlit 页面函数,
成功路径渲染 UI 后不返回值(仅返回 None);此时本接口以全「未提供」+ degraded
降级返回,绝不编造数据。仅当 run_stock_analysis 返回含
agents_results/discussion_result/final_decision 的 dict 时(如
analysis_runner.analyze_single_stock_for_batch 的返回形态)才可完整映射。
"""
import json
import time

from interfaces.common import Scenario

NOT_PROVIDED = "未提供"

# run_stock_analysis 依赖 streamlit/config(dotenv)/openai 等重依赖;导入失败时
# 置 None,analyze_stock 走降级路径(测试通道 venv-data 无 streamlit,即此路径)。
try:
    from views.analysis_runner import run_stock_analysis
except Exception as _exc:  # pragma: no cover - 依赖环境决定
    run_stock_analysis = None
    _RUN_IMPORT_ERROR = f"{type(_exc).__name__}: {_exc}"
else:
    _RUN_IMPORT_ERROR = ""


def _first_text(*values):
    """取第一个非空字符串,否则返回「未提供」。"""
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return NOT_PROVIDED


def _agent_analysis(agents_results, *key_hints):
    """从 agents_results 取某分析师报告文本。

    先按 run_multi_agent_analysis 的英文 key(technical/fundamental/...)
    精确匹配,再按 agent_name 中文关键词(技术/资金/...)兜底,兼容历史数据。
    """
    if not isinstance(agents_results, dict):
        return NOT_PROVIDED
    for hint in key_hints:
        item = agents_results.get(hint)
        if isinstance(item, dict):
            analysis = item.get("analysis")
            if isinstance(analysis, str) and analysis.strip():
                return analysis.strip()
    for item in agents_results.values():
        if not isinstance(item, dict):
            continue
        agent_name = str(item.get("agent_name", ""))
        if not any(hint in agent_name for hint in key_hints):
            continue
        analysis = item.get("analysis")
        if isinstance(analysis, str) and analysis.strip():
            return analysis.strip()
    return NOT_PROVIDED


def _decision_pick(final_decision, *keys):
    """从 final_decision(dict 或 str)取字段文本;str 时整体视为结论文本。"""
    if isinstance(final_decision, str) and final_decision.strip():
        return final_decision.strip()
    if isinstance(final_decision, dict):
        for key in keys:
            value = final_decision.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return NOT_PROVIDED


def _decision_text(final_decision):
    """情景生成的输入文本(最终结论文本);无文本返回空串。"""
    if isinstance(final_decision, str) and final_decision.strip():
        return final_decision.strip()
    if isinstance(final_decision, dict):
        text = final_decision.get("decision_text")
        if isinstance(text, str) and text.strip():
            return text.strip()
        return json.dumps(final_decision, ensure_ascii=False)
    return ""


def _extract_json(text):
    """从 LLM 回复中提取首个 { ... } JSON 对象(同 deepseek_client.final_decision 手法)。"""
    if not isinstance(text, str):
        return None
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except (ValueError, TypeError):
        return None


def _call_scenario_llm(analysis_text):
    """调用 DeepSeek 生成三情景 JSON(独立函数,便于测试 monkeypatch)。

    复用 deepseek_client.DeepSeekClient 的既有 client 创建与 call_api 模式
    (与 ai_agents.StockAnalysisAgents 相同的默认实例化方式)。
    """
    from deepseek_client import DeepSeekClient, SCENARIO_PROMPT_TEMPLATE

    client = DeepSeekClient()
    messages = [
        {"role": "system", "content": "你是一名专业的交易情景规划师,只输出严格 JSON。"},
        {"role": "user", "content": SCENARIO_PROMPT_TEMPLATE.format(analysis_text=analysis_text)},
    ]
    return client.call_api(messages, temperature=0.3, max_tokens=2000)


def build_scenarios(analysis_text):
    """基于最终结论文本生成 上涨/震荡/下跌 三情景(R4-B 字段)。

    - 解析/校验失败(非 JSON、缺 scenarios、字段不合法)返回 []。
    - LLM 调用异常(网络/超时)不在此吞掉:向上抛,由 analyze_stock 按
      R4-A 转成 degraded 降级。
    """
    if not isinstance(analysis_text, str) or not analysis_text.strip():
        return []
    response = _call_scenario_llm(analysis_text)
    data = _extract_json(response)
    if not isinstance(data, dict):
        return []
    items = data.get("scenarios")
    if not isinstance(items, list) or not items:
        return []
    scenarios = []
    for item in items:
        if not isinstance(item, dict):
            return []
        try:
            scenarios.append(Scenario(
                name=str(item.get("name") or ""),
                trigger=str(item.get("trigger") or ""),
                confirm=str(item.get("confirm") or ""),
                target=str(item.get("target") or ""),
                invalidate=str(item.get("invalidate") or ""),
                observe=str(item.get("observe") or ""),
                risk=str(item.get("risk") or ""),
                end=str(item.get("end") or ""),
            ))
        except (ValueError, TypeError):
            return []  # 任一情景字段非法视为整体解析失败
    return scenarios


def analyze_stock(code, period="1y", with_ai=True):
    """单股分析统一接口,返回 dict(键集 = interfaces.common.ANALYSIS_KEYS)。

    Args:
        code: 股票代码(如 "600000");非字符串或空 → ValueError。
        period: 数据周期,默认 "1y"。
        with_ai: True 时额外调用 DeepSeek 生成三情景(R4-B);False 时
            scenarios=[] 且不发起情景 LLM 调用(run_stock_analysis 内部自身的
            AI 分析不受此参数控制——薄封装不改被封装行为)。

    Returns:
        dict(ANALYSIS_KEYS)。取数/AI 失败时 degraded=True + degraded_reason
        说明原因,其余字段保留(映射不到填「未提供」),不抛异常(R4-A)。
    """
    if not isinstance(code, str) or not code.strip():
        raise ValueError(f"股票代码非法:{code!r},应为非空字符串")
    if not isinstance(period, str) or not period.strip():
        raise ValueError(f"周期非法:{period!r},应为非空字符串")

    result = {
        "symbol": code.strip(),
        "name": NOT_PROVIDED,
        "period": period,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "current_state": NOT_PROVIDED,
        "trend": NOT_PROVIDED,
        "chip": NOT_PROVIDED,
        "capital": NOT_PROVIDED,
        "industry": NOT_PROVIDED,
        "news": NOT_PROVIDED,
        "signals": NOT_PROVIDED,
        "scenarios": [],
        "evidence": NOT_PROVIDED,
        "degraded": False,
        "degraded_reason": "",
    }
    reasons = []

    def _degrade(message):
        result["degraded"] = True
        reasons.append(message)

    # 1. 取数 + AI 团队分析(复用 run_stock_analysis,其内部已落库,此处不重复)
    stock_info = {}
    agents_results = {}
    discussion_result = ""
    final_decision = ""
    if run_stock_analysis is None:
        _degrade(f"run_stock_analysis 不可用(views.analysis_runner 导入失败:{_RUN_IMPORT_ERROR})")
    else:
        raw = None
        try:
            raw = run_stock_analysis(code.strip(), period)
        except Exception as exc:
            _degrade(f"run_stock_analysis 调用失败:{type(exc).__name__}: {exc}")
        if isinstance(raw, dict):
            if raw.get("success") is False:
                _degrade(f"run_stock_analysis 分析失败: {raw.get('error', '未知错误')}")
            if isinstance(raw.get("stock_info"), dict):
                stock_info = raw["stock_info"]
            if isinstance(raw.get("agents_results"), dict):
                agents_results = raw["agents_results"]
            if isinstance(raw.get("discussion_result"), str):
                discussion_result = raw["discussion_result"]
            final_decision = raw.get("final_decision", "")
        else:
            _degrade("run_stock_analysis 未返回结构化结果(其运行于 Streamlit 上下文时不返回值)")

    # 2. 字段映射(映射不到填「未提供」,不编造)
    result["name"] = _first_text(stock_info.get("name"))
    result["current_state"] = _decision_pick(final_decision, "rating")
    result["signals"] = _decision_pick(final_decision, "logic", "rating")
    result["evidence"] = _first_text(discussion_result)
    result["trend"] = _agent_analysis(agents_results, "technical", "技术")
    result["chip"] = _agent_analysis(agents_results, "chip", "筹码")
    result["capital"] = _agent_analysis(agents_results, "fund_flow", "资金")
    result["industry"] = _first_text(
        _agent_analysis(agents_results, "fundamental", "基本面"),
        stock_info.get("industry"),
    )
    result["news"] = _agent_analysis(agents_results, "news", "新闻")

    # 3. 情景模板(A/B/C,一次小调用;失败降级不抛,R4-A)
    if with_ai:
        analysis_text = _decision_text(final_decision)
        if analysis_text:
            try:
                result["scenarios"] = build_scenarios(analysis_text)
            except Exception as exc:
                _degrade(f"情景生成失败:{type(exc).__name__}: {exc}")
            else:
                if not result["scenarios"]:
                    _degrade("情景生成解析失败(LLM 输出无法解析为三情景 JSON)")
        else:
            _degrade("无最终结论文本,未生成情景")

    if result["degraded"]:
        result["degraded_reason"] = "; ".join(reasons)
    return result
