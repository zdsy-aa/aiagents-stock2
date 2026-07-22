#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 把 data/profit_mining/每日自选股清单.csv 渲染成结构化 Markdown 文档(分档+摘要+选股逻辑+纪律)。
#   纯标准库,无 pandas。与 push_watchlist.py 同源数据,这里出可读 .md(非邮件HTML)。
# 用法: export_watchlist_md.py [--csv <路径>] [--out <md路径>]   省略 --out 则打到 stdout。
import sys, csv, datetime

DEFAULT_CSV = "/home/tdxback/aiagents-stock/data/profit_mining/每日自选股清单.csv"

# (CSV列名, 表头) 按展示顺序
SHOW = [("精选", "精选"), ("星级", "星级"), ("可入状态", "可入"), ("优先级", "优先级"), ("命中规则", "规则"),
        ("股票代码", "代码"), ("股票名称", "名称"), ("板块", "板块"),
        ("买点类型", "买点"), ("信号日期", "信号日期"),
        ("买入价", "买入价"), ("扫描日价", "扫描价"), ("止损价", "止损价"), ("止盈价", "止盈价"),
        ("预估胜率", "胜率%"), ("量比", "量比"), ("资金确认", "资金"), ("中枢底部", "中枢底"),
        ("获利盘%", "获利盘%"), ("大盘环境", "大盘")]


def read_rows(path):
    with open(path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["股票代码"] = str(r.get("股票代码", "")).zfill(6)
    return rows


def _md_table(rows):
    head = "| " + " | ".join(t for _, t in SHOW) + " |"
    sep = "|" + "|".join("---" for _ in SHOW) + "|"
    body = []
    for r in rows:
        cells = []
        for col, _ in SHOW:
            v = r.get(col, "")
            cells.append(str(v) if v not in (None, "") else "")
        body.append("| " + " | ".join(cells) + " |")
    return "\n".join([head, sep] + body)


def render_md(rows):
    scan = rows[0].get("扫描日期", "") if rows else ""
    nA = sum(1 for r in rows if "A" in r.get("命中规则", ""))
    nB = sum(1 for r in rows if "B" in r.get("命中规则", ""))
    nCore = sum(1 for r in rows if r.get("精选") == "★★核心")
    nSel = sum(1 for r in rows if r.get("精选"))
    nZ = sum(1 for r in rows if r.get("资金确认"))
    nZS = sum(1 for r in rows if r.get("中枢底部"))
    core = [r for r in rows if r.get("精选") == "★★核心"]
    sel = [r for r in rows if r.get("精选") == "★精选"]
    rest = [r for r in rows if not r.get("精选")]
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    L = [f"# 🛡️ 每日稳定选股清单 — {scan}", "",
         f"> 扫描日期 **{scan}**　生成时间 {now}　来源 `daily_watchlist.py`（稳定组合 A∪B + 精选★层）", "",
         "## 一、今日概览", "",
         f"- **命中 {len(rows)} 只**：A 抄底 {nA} / B 抢筹 {nB}",
         f"- **精选 {nSel} 只**，其中 **★★核心 {nCore} 只**（优先关注）",
         f"- 资金确认（机构净买）{nZ} 只　|　中枢底部 {nZS} 只",
         "- 已剔除「获利盘 > 70%」、大盘空头/危险已空仓", ""]

    def section(title, sub, rs):
        if not rs:
            return []
        return [f"### {title}", f"_{sub}_", "", _md_table(rs), ""]

    L += ["## 二、分档清单", ""]
    L += section("★★ 核心精选", f"{nCore} 只 · 1买 + 非陷阱 + 量能金叉，最高优先", core)
    L += section("★ 精选", f"{len(sel)} 只 · 1买 + 非陷阱", sel)
    L += section("其余命中", f"{len(rest)} 只 · 满足 A∪B 但非 1买精选层", rest)

    L += [
        "## 三、选股逻辑", "",
        "**基础集 A∪B（稳定组合）**", "",
        "- **A 稳健抄底**：极限抄底（极度超跌反弹）+ 量比 ≥ 1.3",
        "- **B 主力抢筹**：尖刺金叉（筹码爆破线上穿堡垒线，需换手率重建筹码）",
        "- 过滤：剔除获利盘 > 70%；大盘空头/危险（SID > 2）空仓", "",
        "**精选★层（样本外验证 +10~12pt / 2024-25，全历史滚动 8/9 regime 超基线）**", "",
        "- **★精选**：基础集 ∩ 1买 ∩ 非陷阱（剔「相对强弱 ≥ 0」或「大盘多头」——极限抄底=震荡市超跌反弹，转强反失效）",
        "- **★★核心**：★精选 再叠「量能金叉」（1买内 +4.8pt）",
        "- 排序：精选档 > 1买 > A∪B > 资金确认 > 中枢底部 > 量比", "",
        "## 四、操作纪律", "",
        "- **优先级**：★★核心 > ★精选 > 普通；同档优先 1买、A∪B 双命中、有资金确认/中枢底部者。",
        "- **止损（硬纪律）**：跌破「止损价」当日即出场。止损价 = max(买入价×0.92, 信号前5日结构低点×0.99)，取更近者。**即使当日仍命中买点条件也照砍**——买点是进场理由，不是持有理由。",
        "- **止盈**：达「止盈价」(买入价×1.3) 分批了结，或 +20~30% 移动止盈；遇缠论卖点 + 斐波全多头 / 二连板优先了结。",
        "- **再买入**：止损后勿在同一波下跌中反复抄底（接飞刀）；待该股重新触发新买点（1买优先 / 非陷阱）且大盘非空头危险时再进。",
        "- **择时**：大盘转空头/危险一律空仓（2008/2015 系统性危机会使超跌反弹失效，硬约束）。",
        "- **仓位**：稳健组合宜分散（并发 20~30 时风险调整收益最优，Sharpe≈1.5/回撤≈-4%）。", "",
        "---", "",
        "> ⚠ 本清单为提升度/样本外回测口径的研究性参考，非投资建议。盈亏自负。"]
    return "\n".join(L), scan, len(rows), nSel, nCore


def main():
    args = sys.argv[1:]
    csv_path, out = DEFAULT_CSV, None
    i = 0
    while i < len(args):
        if args[i] == "--csv":
            csv_path = args[i + 1]; i += 2
        elif args[i] == "--out":
            out = args[i + 1]; i += 2
        else:
            print(f"未知参数 {args[i]}", file=sys.stderr); sys.exit(2)
    rows = read_rows(csv_path)
    if not rows:
        print("清单为空", file=sys.stderr); sys.exit(1)
    md, scan, n, nSel, nCore = render_md(rows)
    if out:
        with open(out, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"已写 Markdown 文档 -> {out}（{scan} 共{n}只/精选{nSel}/核心{nCore}）")
    else:
        print(md)


if __name__ == "__main__":
    main()
