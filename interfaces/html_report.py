# -*- coding: utf-8 -*-
"""Phase4 HTML 报告模板(interfaces.html_report):中文、内联 CSS、单文件双击可开。

gen_report(kind, payload, out_dir=None) -> str(HTML 文件路径)

- kind ∈ {"analysis", "candidates", "backtest"},其他抛 ValueError(R4-A 输入非法);
  payload 必须为 dict,否则抛 ValueError。文件名 `{kind}_报告_<ts>_<ms>.html`
  (ts = %Y%m%d_%H%M%S,ms = 3 位毫秒,防同秒覆盖,P5-2),out_dir 缺省用仓库根
  report/(不存在则创建)。
- 样式参考项目 ui_theme 配色(冷灰底 #f0f2f5、白底卡片、浅灰边框、圆角、
  表格斑马纹、涨红跌绿),全部内联于单文件 <style>,无外链资源,双击即开。
- 三种模板:
    * analysis   渲染 interfaces.common.ANALYSIS_KEYS 全部字段(键值表)+
                 scenarios 情景表(每情景一行,列按 SCENARIO_FIELDS;上涨/震荡/
                 下跌情景名以涨红/震荡橙/跌绿标注);degraded 为真时顶部降级横幅。
    * candidates 渲染 SCREEN_RESULT_COLS = [代码, 名称, 信号, 得分, 备注] 表格。
    * backtest   渲染 Phase 3 报告同款十列:信号/训练胜率/测试胜率/训练支持/
                 测试支持/平均收益/最大回撤/连续亏损/盈亏比/过拟合标志。
- 周报/月报模板留 Phase 5(定时任务驱动),本任务不做。
"""
import html
import time
from pathlib import Path

from interfaces.common import ANALYSIS_KEYS, SCENARIO_FIELDS, SCREEN_RESULT_COLS

__all__ = ["gen_report", "KINDS", "BACKTEST_COLS", "DEFAULT_REPORT_DIR"]

KINDS = ("analysis", "candidates", "backtest")
DEFAULT_REPORT_DIR = Path(__file__).resolve().parent.parent / "report"

# 回测报告十列(Phase 3 gen_report_57 同款,涨跌占比列 v1 面板不可表达,不放)。
BACKTEST_COLS = ("信号", "训练胜率", "测试胜率", "训练支持", "测试支持",
                 "平均收益", "最大回撤", "连续亏损", "盈亏比", "过拟合标志")

_ANALYSIS_LABELS = {
    "symbol": "代码", "name": "名称", "period": "周期",
    "generated_at": "生成时间", "current_state": "当前状态",
    "trend": "趋势", "chip": "筹码", "capital": "资金",
    "industry": "行业", "news": "新闻", "signals": "信号",
    "scenarios": "情景", "evidence": "依据",
    "degraded": "降级", "degraded_reason": "降级原因",
}

_SCENARIO_LABELS = {
    "name": "情景", "trigger": "触发条件", "confirm": "确认",
    "target": "目标位", "invalidate": "失效条件",
    "observe": "观察", "risk": "风险", "end": "结束",
}

# ui_theme 配色:冷灰底 / 白卡片 / 浅灰边框 / 主文字 / 次要文字 / 主色 / 涨红跌绿
_CSS = """
body { background:#f0f2f5; color:#1a1d23; margin:0; padding:24px;
       font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; }
.container { max-width:1080px; margin:0 auto; }
.card { background:#ffffff; border:1px solid #e8eaed; border-radius:14px;
        padding:18px 24px; margin:12px 0; box-shadow:0 1px 3px rgba(0,0,0,.04); }
h1 { font-size:1.3rem; font-weight:800; margin:0 0 4px; color:#1a1d23; }
h2 { font-size:1.02rem; font-weight:700; margin:16px 0 8px; color:#1a1d23; }
.meta { color:#8b919e; font-size:.8rem; margin-bottom:4px; }
table { width:100%; border-collapse:collapse; margin:8px 0; font-size:.87rem; }
th { background:#f0f4fe; color:#1e3a8a; font-weight:700; }
th, td { border:1px solid #e8eaed; padding:8px 12px; text-align:left;
         vertical-align:top; word-break:break-all; }
tr:nth-child(even) td { background:#f8f9fb; }
.kv td:first-child { width:120px; color:#8b919e; white-space:nowrap;
                     background:#fafbfc; }
.badge-up { color:#e12c43; font-weight:800; }
.badge-mid { color:#f08c2e; font-weight:800; }
.badge-dn { color:#0fa958; font-weight:800; }
.banner-degraded { background:#fff4e5; border:1px solid #f08c2e; color:#8a4b0d;
                   border-radius:10px; padding:10px 14px; margin:10px 0; }
.footer { color:#8b919e; font-size:.75rem; text-align:center; margin-top:18px; }
"""


def _esc(v):
    """值 -> 转义后的安全文本;列表拼接;None/空 -> 「—」;数字转字符串。"""
    if v is None:
        return "—"
    if isinstance(v, (list, tuple)):
        return html.escape("; ".join(str(x) for x in v if x not in (None, ""))) or "—"
    s = str(v)
    return html.escape(s) if s != "" else "—"


def _cell(v):
    return f"<td>{_esc(v)}</td>"


def _scenario_badge(name):
    """情景名徽标:上涨红 / 下跌绿 / 其余橙(A股涨红跌绿)。"""
    if "上涨" in str(name):
        return f'<span class="badge-up">{_esc(name)}</span>'
    if "下跌" in str(name):
        return f'<span class="badge-dn">{_esc(name)}</span>'
    return f'<span class="badge-mid">{_esc(name)}</span>'


def _page(title, body, generated_at):
    """整页 HTML:内联 CSS 单文件,中文 lang,双击可开。"""
    return "\n".join([
        "<!DOCTYPE html>",
        '<html lang="zh-CN">',
        "<head>",
        '  <meta charset="utf-8">',
        '  <meta name="viewport" content="width=device-width, initial-scale=1">',
        f"  <title>{_esc(title)}</title>",
        f"  <style>{_CSS}</style>",
        "</head>",
        "<body>",
        '  <div class="container">',
        f'    <div class="card"><h1>{_esc(title)}</h1>'
        f'<div class="meta">生成时间:{html.escape(generated_at)}</div></div>',
        body,
        '    <div class="footer">由 interfaces.html_report 生成(内联样式,'
        "单文件可直接双击打开)</div>",
        "  </div>",
        "</body>",
        "</html>",
        "",
    ])


def _render_analysis(payload):
    """analysis 模板:ANALYSIS_KEYS 键值表 + scenarios 情景表 + 降级横幅。"""
    body = []
    if payload.get("degraded"):
        body.append('    <div class="banner-degraded">【降级提示】结果已降级:'
                    f'{_esc(payload.get("degraded_reason") or "原因未提供")}</div>')
    body.append('    <div class="card"><h2>分析字段</h2><table class="kv">')
    for key in ANALYSIS_KEYS:
        if key == "scenarios":
            continue  # 单独渲染情景表
        body.append(f"      <tr><td>{_ANALYSIS_LABELS.get(key, key)}</td>"
                    f"{_cell(payload.get(key))}</tr>")
    body.append("    </table></div>")
    scenarios = payload.get("scenarios") or []
    body.append('    <div class="card"><h2>情景推演(A/B/C)</h2><table>')
    body.append("      <tr>" + "".join(
        f"<th>{_SCENARIO_LABELS[f]}</th>" for f in SCENARIO_FIELDS) + "</tr>")
    for sc in scenarios:
        if not isinstance(sc, dict):
            continue
        cells = [_scenario_badge(sc.get("name")) if f == "name"
                 else _esc(sc.get(f)) for f in SCENARIO_FIELDS]
        body.append("      <tr>" + "".join(f"<td>{c}</td>" for c in cells)
                    + "</tr>")
    body.append("    </table></div>")
    return "\n".join(body)


def _render_candidates(payload):
    """candidates 模板:SCREEN_RESULT_COLS 五列表。"""
    rows = payload.get("rows") or []
    body = ['    <div class="card"><h2>候选列表</h2>'
            f'<div class="meta">共 {len(rows)} 条</div><table>']
    body.append("      <tr>" + "".join(f"<th>{c}</th>"
                                       for c in SCREEN_RESULT_COLS) + "</tr>")
    for row in rows:
        if not isinstance(row, dict):
            continue
        body.append("      <tr>" + "".join(_cell(row.get(c))
                                           for c in SCREEN_RESULT_COLS) + "</tr>")
    body.append("    </table></div>")
    return "\n".join(body)


def _render_backtest(payload):
    """backtest 模板:Phase 3 报告同款十列表。"""
    rows = payload.get("rows") or []
    body = ['    <div class="card"><h2>回测结果</h2>'
            f'<div class="meta">共 {len(rows)} 条 · 切分口径:训练段 年&lt;=2024 / '
            "测试段 年&gt;=2025(backtest.dataio.split_train_test)</div><table>"]
    body.append("      <tr>" + "".join(f"<th>{c}</th>"
                                       for c in BACKTEST_COLS) + "</tr>")
    for row in rows:
        if not isinstance(row, dict):
            continue
        body.append("      <tr>" + "".join(_cell(row.get(c))
                                           for c in BACKTEST_COLS) + "</tr>")
    body.append("    </table></div>")
    return "\n".join(body)


_RENDERERS = {
    "analysis": _render_analysis,
    "candidates": _render_candidates,
    "backtest": _render_backtest,
}


def _default_title(kind, payload):
    if kind == "analysis":
        symbol = payload.get("symbol")
        name = payload.get("name")
        if symbol and name:
            return f"{symbol} {name} 分析报告"
    return {"analysis": "分析报告", "candidates": "候选列表",
            "backtest": "回测报告"}[kind]


def gen_report(kind, payload, out_dir=None):
    """生成 HTML 报告 -> 文件路径(见模块 docstring)。

    payload 为 dict,各模板所需键见对应 _render_* 函数;缺失键渲染为「—」。
    """
    if kind not in KINDS:
        raise ValueError(f"未知报告类型: {kind!r},应为 {KINDS} 之一")
    if not isinstance(payload, dict):
        raise ValueError(f"payload 应为 dict,收到 {type(payload).__name__}")
    out = Path(out_dir) if out_dir else DEFAULT_REPORT_DIR
    out.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    ms = f"{int(time.time() * 1000) % 1000:03d}"   # P5-2:同秒不覆盖
    ts_full = time.strftime("%Y-%m-%d %H:%M:%S")
    title = payload.get("title") or _default_title(kind, payload)
    doc = _page(title, _RENDERERS[kind](payload), ts_full)
    path = out / f"{kind}_报告_{ts}_{ms}.html"
    path.write_text(doc, encoding="utf-8")
    return str(path)
