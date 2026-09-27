# -*- coding: utf-8 -*-
"""automation.jobs 三时段任务清单(Phase5 Task5.1)。

- ``PRE_MARKET_JOBS`` 开盘前:更新新闻(news_fetch.fetch_daily_news,网络,失败
  可重试)、盘前列表(screen_stocks("stable", raise_on_empty=False));
- ``INTRADAY_JOBS`` 盘中:信号扫描(scan_signals 对重点池 ``WATCHLIST``,池为空
  跳过,不加载 15M 确认面板);
- ``POST_MARKET_JOBS`` 收盘后:选股(screen_stocks("chanlun"/"combo",
  raise_on_empty=False)→ 风险过滤占位(Task 5.2 就绪后接)→ 分析(analyze_stock
  对候选前 ``ANALYZE_TOP_N`` 只,经 interfaces.ai_trace.trace_save 落
  prompt_version/model_version,P5-1)→ 信号记录占位(Task 5.3)。

任务函数全部是模块级薄封装,函数体内延迟 import 被封装模块,测试可
monkeypatch 被封装模块的接口函数注入假实现,不真实跑网络/发信/加载 15M 面板。
告警入口 ``alert_failures`` 的邮件发送器在调用时解析为 ``jobs.send_mail``,
测试 monkeypatch ``jobs.send_mail`` 即生效。
"""
import json
import logging
import os

from automation import JobSpec
from automation.alert import alert_failures as _alert_failures, send_mail

logger = logging.getLogger(__name__)

__all__ = ["PRE_MARKET_JOBS", "INTRADAY_JOBS", "POST_MARKET_JOBS", "ALL_JOBS",
           "alert_failures", "send_mail", "WATCHLIST", "ANALYZE_TOP_N"]

# 重点池(盘中信号扫描范围)。现有代码无统一「重点池」概念,先置空列表;
# 盘中扫描任务检测到池为空即跳过(日志说明)。接入池来源(如 stable 清单
# 或用户自选)后把代码列表写入此常量即可。
WATCHLIST = []

# 盘中扫描的组合规格名(TQ01~TQ57,经 scan_signals 解析;可扩展)。
INTRADAY_SCAN_SPECS = ("TQ01",)

# 收盘后候选进入分析的只数上限(选股结果按序截取)。
ANALYZE_TOP_N = 5

# 收盘后选股器顺序(本地库类,零参数可跑;空表以 raise_on_empty=False 跳过)。
POST_SCREEN_SELECTORS = ("chanlun", "combo")

# 收盘后选股 → 分析 之间的候选传递(选股任务写入,分析/信号记录任务读取)。
_last_candidates = []


def alert_failures(res, mail=True):
    """失败告警入口(jobs 命名空间):见 automation.alert.alert_failures。

    邮件发送器在调用时解析为 ``jobs.send_mail``,测试 monkeypatch
    ``jobs.send_mail`` 即生效;``mail=False`` 时仅日志。
    """
    return _alert_failures(res, mail=mail, _sender=send_mail)


# ---------- 开盘前 ----------

def _pre_update_news():
    """开盘前:更新新闻库(news_fetch.fetch_daily_news,网络任务,失败按 retries 重试)。"""
    from news_fetch import fetch_daily_news

    fetch_daily_news()


def _pre_screen_stable():
    """开盘前:盘前列表(screen_stocks("stable", raise_on_empty=False),空表不抛错)。"""
    from interfaces.screen import screen_stocks

    return screen_stocks("stable", raise_on_empty=False)


# ---------- 盘中 ----------

def _scan_intraday_focus_pool():
    """盘中:对重点池 WATCHLIST 扫描信号;池为空跳过(不加载 15M 确认面板)。

    面板加载(backtest.dataio.load_confirm_panel)仅池非空时进行;扫描结果当前
    仅记录命中数(信号落追踪表接入见 Task 5.3)。代码前导零归一匹配口径待
    重点池来源确定后与 interfaces.ai_trace._norm_code 对齐。
    """
    if not WATCHLIST:
        logger.info("盘中重点池为空,跳过信号扫描")
        return
    from backtest.dataio import load_confirm_panel
    from interfaces.screen import scan_signals

    panel = load_confirm_panel()
    code_col = next((c for c in ("股票代码", "代码", "code", "symbol")
                     if c in panel.columns), None)
    if code_col is None:
        raise RuntimeError("确认面板缺代码列,无法按重点池过滤")
    focus = panel[panel[code_col].astype(str).isin([str(c) for c in WATCHLIST])]
    for spec_name in INTRADAY_SCAN_SPECS:
        hits = scan_signals(spec_name, df=focus)
        logger.info("盘中扫描 %s 命中 %d 条", spec_name, len(hits))


# ---------- 收盘后 ----------

def _screen_post_market():
    """收盘后选股:chanlun/combo 本地选股器(空表不抛错)合并去重,写入候选。

    两个选股器均执行失败(异常,而非空表)时抛 RuntimeError → 任务 failed →
    告警(全局约束:数据不可用不得静默);空表(今日无信号)属正常市况,跳过分析。
    """
    global _last_candidates
    from interfaces.screen import screen_stocks

    frames, errors = [], []
    for sel in POST_SCREEN_SELECTORS:
        try:
            frames.append(screen_stocks(sel, raise_on_empty=False))
        except RuntimeError as exc:
            errors.append(f"{sel}: {exc}")
            logger.warning("收盘后选股 %s 失败: %s", sel, exc)
    if not frames and errors:
        _last_candidates = []
        raise RuntimeError("收盘后选股全部失败: " + "; ".join(errors))

    _last_candidates = []
    if not frames:
        logger.warning("收盘后选股无候选(chanlun/combo 均空),本轮跳过分析")
        return
    import pandas as pd

    candidates = pd.concat(frames, ignore_index=True)
    candidates = candidates.drop_duplicates(subset=["代码"], keep="first")
    # TODO(Task 5.2): 风险前置过滤占位(import 注释,就绪后接):
    #     from automation.risk_filter import default_risk_filter
    #     candidates = default_risk_filter()(candidates)
    _last_candidates = [str(c) for c in candidates["代码"].tolist()]
    logger.info("收盘后选股候选 %d 只: %s", len(_last_candidates), _last_candidates)


def _current_model_version():
    """当前引擎默认模型名(与 config.DEFAULT_MODEL_NAME 同源)。

    测试通道(venv-data)无 dotenv,config 导入失败时退回环境变量同口径取值。
    """
    try:
        from config import DEFAULT_MODEL_NAME
    except ImportError:  # pragma: no cover - 依赖环境决定
        DEFAULT_MODEL_NAME = os.environ.get("DEFAULT_MODEL_NAME", "deepseek-chat")
    return DEFAULT_MODEL_NAME


def _save_analysis_trace(result):
    """把 analyze_stock 的结果 dict 经 ai_trace.trace_save 落版本化记录(P5-1)。

    prompt_version = deepseek_client.PROMPT_VERSIONS 的 JSON 快照(R4-C 六模板
    版本汇总口径);model_version = 引擎默认模型名;stock_info/agents_results/
    final_decision 由接口归一化字段重建(analyze_stock 不返回原始 dict,重建值
    为接口口径,如实记录)。
    """
    from deepseek_client import PROMPT_VERSIONS
    from interfaces.ai_trace import trace_save

    trace_save(
        symbol=result.get("symbol", ""),
        name=result.get("name", ""),
        period=result.get("period", "1y"),
        stock_info={"name": result.get("name", ""),
                    "industry": result.get("industry", "")},
        agents_results={
            "technical": {"analysis": result.get("trend", "")},
            "chip": {"analysis": result.get("chip", "")},
            "fund_flow": {"analysis": result.get("capital", "")},
            "fundamental": {"analysis": result.get("industry", "")},
            "news": {"analysis": result.get("news", "")},
        },
        discussion_result=result.get("evidence", ""),
        final_decision={"rating": result.get("current_state", ""),
                        "logic": result.get("signals", "")},
        prompt_version=json.dumps(PROMPT_VERSIONS, ensure_ascii=False),
        model_version=_current_model_version(),
        input_snapshot={"source": "automation.jobs 收盘后分析",
                        "generated_at": result.get("generated_at", "")},
    )


def _analyze_post_market():
    """收盘后分析:对候选前 ANALYZE_TOP_N 只调 analyze_stock,再经 trace_save
    落 prompt_version/model_version(P5-1 接线,方案见 task-5.1-report.md)。

    引擎内部 save_analysis 已落无版本原始记录(全量字段);此处 trace_save 补记
    「自动化运行口径」的版本化记录。分析降级/失败按全局约束不静默:记录落库后
    抛 RuntimeError → 任务 failed → 告警(重试会重复落 trace,故本任务 retries=0)。
    """
    from interfaces.analyze import analyze_stock

    if not _last_candidates:
        logger.info("收盘后候选为空,跳过分析")
        return
    codes = [str(c) for c in _last_candidates][:ANALYZE_TOP_N]
    problems = []
    for code in codes:
        try:
            result = analyze_stock(code)
        except Exception as exc:  # 接口按 R4-A 不抛,防御保留
            problems.append(f"{code}: {type(exc).__name__}: {exc}")
            continue
        try:
            _save_analysis_trace(result)
        except Exception as exc:
            problems.append(f"{code}: trace_save 失败: {type(exc).__name__}: {exc}")
            continue
        if result.get("degraded"):
            problems.append(f"{code}: 分析降级({result.get('degraded_reason', '')})")
    if problems:
        raise RuntimeError("收盘后分析存在失败/降级: " + "; ".join(problems))


def _record_signals_post_market():
    """收盘后信号记录:占位任务(Task 5.3 就绪后接入 signal_tracking.record_signals)。"""
    # TODO(T5.3): from automation.signal_tracking import record_signals
    #   对收盘后选股结果逐组合落信号追踪表(组合名/代码/日期/命中 mask)。
    logger.info("收盘后信号记录为占位任务(T5.3 就绪后接线),本轮跳过")


# ---------- 三时段任务清单 ----------

PRE_MARKET_JOBS = [
    JobSpec(name="开盘前新闻更新", phase="pre_market", fn=_pre_update_news, retries=1),
    JobSpec(name="盘前列表", phase="pre_market", fn=_pre_screen_stable, retries=0),
]

INTRADAY_JOBS = [
    JobSpec(name="盘中信号扫描", phase="intraday", fn=_scan_intraday_focus_pool, retries=0),
]

POST_MARKET_JOBS = [
    JobSpec(name="收盘后选股", phase="post_market", fn=_screen_post_market, retries=0),
    JobSpec(name="收盘后分析", phase="post_market", fn=_analyze_post_market,
            depends_on=["收盘后选股"], retries=0),
    JobSpec(name="收盘后信号记录", phase="post_market", fn=_record_signals_post_market,
            depends_on=["收盘后分析"], retries=0),
]

ALL_JOBS = PRE_MARKET_JOBS + INTRADAY_JOBS + POST_MARKET_JOBS
