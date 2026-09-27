# backtest/report.py
"""回测报告生成(Phase3 Task3.5):单策略报告与 57 信号整表报告。

- gen_report(strategy, out_dir, df=None) -> str(文件路径):
    单策略 Markdown 报告,六段:策略逻辑/参数/进出场条件/回测结果(引擎
    12 键指标,训练段 年<=2024 / 测试段 年>=2025)/版本历史(versioning.
    param_history)/已知问题。文件名 回测报告_<策略>_<ts>.md。
- gen_report_57(out_dir, df=None) -> str(文件路径):
    57 信号整表报告 —— 对每个可用 spec 在确认面板上分别跑训练/测试段
    run_backtest,表列:信号/训练胜率/测试胜率/训练支持/测试支持/平均收益/
    最大回撤/连续亏损/盈亏比/涨跌占比/过拟合标志(|训练胜率-测试胜率| > 0.10,
    复用 param_test.overfit_flag,控制器裁决同口径)。文件名
    回测报告_57信号_<ts>.md。
- df=None 时载入 load_confirm_panel()(v1,15,115,796 行,解包 ~60s,57×2 段
  回测 ~1-2 分钟,实测 ~3-4 分钟);测试一律传合成 df,不跑真面板(控制器裁决:
  报告生成只跑一次)。
- 涨跌占比:TQ51~TQ57 的上涨/下跌占比需 v2 面板的下跌标签,v1 基座上 spec
  无法表达,统一标「见 tq_confirm_top10 文件头」,不编造数字(控制器裁决)。
- out_dir 缺省用 DEFAULT_REPORT_DIR(仓库根 report/,不存在则创建;目录已
  存在则直接用)。
"""
import math
import time
from pathlib import Path

from backtest import versioning
from backtest.combo_engine import build_57_specs
from backtest.dataio import load_confirm_panel, split_train_test
from backtest.engine import run_backtest
from backtest.param_test import overfit_flag

DEFAULT_REPORT_DIR = Path(__file__).resolve().parent.parent / "report"
TQ51_57 = {f"TQ{i:02d}" for i in range(51, 58)}
TQ51_57_NOTE = "见 tq_confirm_top10 文件头"

# 引擎 12 键 -> (指标名, 格式):int=整数 / pct=百分率 / ret=带符号百分率 / ratio=盈亏比
_METRIC_ROWS = [
    ("命中数(支持)", "n", "int"),
    ("盈利次数", "wins", "int"),
    ("胜率", "win_rate", "pct"),
    ("平均收益", "avg_ret", "ret"),
    ("最大收益", "max_ret", "ret"),
    ("最大回撤", "max_drawdown", "pct"),
    ("年化收益(20日持仓近似)", "annual_ret", "pct"),
    ("盈亏比", "profit_loss_ratio", "ratio"),
    ("最大连续亏损", "max_consec_loss", "int"),
    ("收益标准差", "ret_std", "ret"),
]


def _fmt(x, kind):
    """指标值格式化:None/NaN -> 「—」,inf 盈亏比 -> 「∞」。

    注意盈亏比需先于非有限值拦截:引擎在测试段无负收益亏损行时输出 inf
    (avg_loss <= 0 且 avg_win > 0),inf 是有效语义(无亏损),不是缺值。
    """
    if x is None:
        return "—"
    if kind == "int":
        return str(int(x))
    if kind == "ratio":
        if math.isnan(x):
            return "—"
        return "∞" if math.isinf(x) else f"{x:.2f}"
    if isinstance(x, float) and not math.isfinite(x):
        return "—"
    if kind == "pct":
        return f"{x * 100:.1f}%"
    if kind == "ret":
        return f"{x * 100:+.2f}%"
    return str(x)


def _fmt_params(params):
    if not params:
        return "无版本记录(尚未 bump_version)"
    return "\n".join(f"- {k} = {v}" for k, v in params.items())


def _fmt_conds(conds, prefix=""):
    """进出场条件渲染(嵌套 or_group 递归,组内标 (OR))。"""
    lines = []
    for c in conds:
        if "or_group" in c:
            lines.extend(_fmt_conds(c["or_group"], prefix="(OR) "))
        else:
            lines.append(f"- {prefix}{c['col']} {c['op']} {c['value']}")
    return lines


def _fmt_history(hist):
    if not hist:
        return "无版本记录"
    lines = []
    for v in hist:
        lines.append(f"- {v['version']}(创建于 {v.get('created_at', '')})"
                     f"参数: {v.get('params')}")
    return "\n".join(lines)


def _known_issues(spec, strategy):
    issues = []
    if spec.get("unavailable"):
        issues.append(f"spec 不可用(conds 置空): {spec.get('reason', '面板缺列')}")
    if strategy in TQ51_57:
        issues.append("TQ51~TQ57 手工映射:4日窗口事件列确认面板不可表达,"
                      f"spec 取同日近似;涨跌占比见 tq_confirm_top10 文件头"
                      f"(标「{TQ51_57_NOTE}」,不编造)。")
    return "\n".join(f"- {i}" for i in issues) if issues else "无"


def _find_spec(specs, strategy):
    for s in specs:
        if s["name"] == strategy:
            return s
    raise KeyError(f"未知策略: {strategy}(57 规格中不存在)")


def _load_train_test(df):
    """面板 -> (训练段, 测试段);df=None 时载入确认面板(真面板路径,测试不传)。"""
    if df is None:
        df = load_confirm_panel()
    return split_train_test(df)


def _out_dir(path):
    p = Path(path) if path else DEFAULT_REPORT_DIR
    p.mkdir(parents=True, exist_ok=True)
    return p


def gen_report(strategy, out_dir=None, df=None):
    """单策略回测报告 -> 文件路径(回测报告_<策略>_<ts>.md)。"""
    out = _out_dir(out_dir)
    specs = build_57_specs()
    spec = _find_spec(specs, strategy)
    train, test = _load_train_test(df)
    r_tr = run_backtest(spec, train)
    r_te = run_backtest(spec, test)
    hist = versioning.param_history(strategy)
    ts = time.strftime("%Y%m%d_%H%M%S")
    ts_full = time.strftime("%Y-%m-%d %H:%M:%S")

    latest_params = hist[-1].get("params", {}) if hist else {}
    lines = [
        f"# 回测报告:{strategy}",
        "",
        f"- 生成时间: {ts_full}",
        f"- 策略名: {strategy}",
        "",
        "## 策略逻辑",
        spec.get("raw", spec.get("name", "")),
        "",
        "## 参数",
        _fmt_params(latest_params),
        "",
        "## 进出场条件",
    ]
    lines += _fmt_conds(spec.get("conds") or []) or ["- (无显式条件)"]
    lines += ["",
              "## 回测结果",
              "",
              ("- 切分口径: 训练段 年<=2024 / 测试段 年>=2025"
               "(dataio.split_train_test)。"),
              "- spec 不可用(面板缺列)时回测无命中行,各指标取中性值。"
              if spec.get("unavailable") else "- 指标来自统一回测引擎 run_backtest。",
              "",
              "| 指标 | 训练段 | 测试段 |",
              "| --- | --- | --- |"]
    for label, key, kind in _METRIC_ROWS:
        lines.append(f"| {label} | {_fmt(r_tr.get(key), kind)}"
                     f" | {_fmt(r_te.get(key), kind)} |")
    lines += ["",
              "## 版本历史",
              _fmt_history(hist),
              "",
              "## 已知问题",
              _known_issues(spec, strategy),
              ""]
    path = out / f"回测报告_{strategy}_{ts}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)


def _render_57_md(rows, ts_full, n_avail, n_total):
    lines = [
        "# 57 信号回测报告(整表)",
        "",
        f"- 生成时间: {ts_full}",
        "- 数据基座: 确认面板 confirm_panel.npz(15,115,796 行日K × 168 布尔位"
        "压缩列 + 17 连续列 + 标签,dataio.load_confirm_panel)。",
        "- 切分口径: 训练段 年<=2024 / 测试段 年>=2025(dataio.split_train_test)。",
        f"- 可用 spec: {n_avail}/{n_total}(缺列 spec 各指标标「—」)。",
        "- 平均收益/最大回撤/连续亏损/盈亏比 取测试段(样本外)口径。",
        "",
        "| 信号 | 训练胜率 | 测试胜率 | 训练支持 | 测试支持 | 平均收益 |"
        " 最大回撤 | 连续亏损 | 盈亏比 | 涨跌占比 | 过拟合标志 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for name, r_tr, r_te in rows:
        if r_tr is None or r_te is None:
            cells = [name] + ["—"] * 10
        else:
            flag = "是" if overfit_flag(r_tr["win_rate"], r_te["win_rate"]) else "否"
            cells = [name,
                     _fmt(r_tr["win_rate"], "pct"), _fmt(r_te["win_rate"], "pct"),
                     str(r_tr["n"]), str(r_te["n"]),
                     _fmt(r_te["avg_ret"], "ret"),
                     _fmt(r_te["max_drawdown"], "pct"),
                     str(r_te["max_consec_loss"]),
                     _fmt(r_te["profit_loss_ratio"], "ratio"),
                     TQ51_57_NOTE if name in TQ51_57 else "—",
                     flag]
        lines.append("| " + " | ".join(cells) + " |")
    lines += ["",
              "## 说明",
              "",
              f"- 涨跌占比: TQ51~TQ57 需 v2 面板的下跌标签,v1 基座上 spec 无法"
              f"表达,标「{TQ51_57_NOTE}」,不编造数字。",
              "- 过拟合标志: |训练胜率 - 测试胜率| > 0.10 时标「是」"
              "(param_test.overfit_flag 同口径,严格大于)。",
              "- 不可用信号(面板缺列,conds 置空)各指标标「—」。",
              ""]
    return "\n".join(lines)


def gen_report_57(out_dir=None, df=None):
    """57 信号整表回测报告 -> 文件路径(回测报告_57信号_<ts>.md)。

    真面板实测约 3-4 分钟(解包 ~60s + 57×2 段回测);测试传合成 df。
    """
    out = _out_dir(out_dir)
    specs = build_57_specs()
    train, test = _load_train_test(df)
    rows = []
    n_avail = 0
    for spec in specs:
        name = spec["name"]
        if spec.get("unavailable"):
            rows.append((name, None, None))
            continue
        rows.append((name, run_backtest(spec, train), run_backtest(spec, test)))
        n_avail += 1
    ts = time.strftime("%Y%m%d_%H%M%S")
    ts_full = time.strftime("%Y-%m-%d %H:%M:%S")
    md = _render_57_md(rows, ts_full, n_avail, len(specs))
    path = out / f"回测报告_57信号_{ts}.md"
    path.write_text(md, encoding="utf-8")
    return str(path)


__all__ = ["gen_report", "gen_report_57", "DEFAULT_REPORT_DIR"]
