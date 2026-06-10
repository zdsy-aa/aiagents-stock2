#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 把 data/profit_mining/每日自选股清单.csv 渲染成"文档式"邮件并推送:
#   正文=HTML文档(概览+三档清单含信号日期列+选股逻辑+操作纪律),附件=同内容 Markdown 文档(.md)。
#   复用 send_mail.py 同款 .env 163 SMTP(465 隐式SSL)。附件/文档结构复用 export_watchlist_md。
# 用法:
#   push_watchlist.py [--to a@x.com,b@y.com] [--dry] [--csv <路径>] [--out <html预览路径>]
#   --dry  只渲染(配合 --out 写HTML预览),不发信。
import sys, os, smtplib, ssl, html, datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from email.header import Header
from email.utils import formataddr

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # 便于 import 同目录 export_watchlist_md
import export_watchlist_md as EXP
import export_watchlist_xlsx as XLS   # openpyxl 仅在 build 时才 import,顶层导入安全

# 宿主直跑读宿主 .env；容器内(docker exec,盘中脚本)宿主路径不存在→回退 /app/.env
ENV_PATH = next((p for p in ("/home/tdxback/aiagents-stock/.env", "/app/.env") if os.path.exists(p)),
                "/home/tdxback/aiagents-stock/.env")
DEFAULT_CSV = "/home/tdxback/aiagents-stock/data/profit_mining/每日自选股清单.csv"

# 邮件正文 HTML 表格列(与文档一致,含信号日期)
SHOW = [("精选", "精选"), ("星级", "星级"), ("可入状态", "可入"), ("优先级", "优先级"), ("命中规则", "规则"),
        ("股票代码", "代码"), ("股票名称", "名称"), ("买点类型", "买点"),
        ("信号日期", "信号日期"), ("买入价", "买入价"), ("扫描日价", "扫描价"), ("止损价", "止损价"),
        ("止盈价", "止盈价"), ("预估胜率", "胜率%"), ("量比", "量比"), ("资金确认", "资金"),
        ("中枢底部", "中枢底"), ("获利盘%", "获利盘%"), ("大盘环境", "大盘")]


def load_env(path):
    cfg = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip().strip('"').strip("'")
    return cfg


def _esc(v):
    return html.escape(str(v if v is not None else ""))


def _table(rows):
    th = "".join(f'<th style="padding:6px 9px;border-bottom:2px solid #c9b896;'
                 f'text-align:left;font-size:13px;color:#5a4a2a;white-space:nowrap;">{_esc(t)}</th>'
                 for _, t in SHOW)
    trs = []
    for r in rows:
        tier = r.get("精选", "")
        bg = "#fff8e6" if tier == "★★核心" else ("#fffdf5" if tier == "★精选" else "#ffffff")
        tds = []
        for col, _ in SHOW:
            val = r.get(col, "")
            style = "padding:5px 9px;border-bottom:1px solid #eee;font-size:13px;white-space:nowrap;"
            if col == "精选" and tier:
                style += "font-weight:700;color:#b8860b;"
            if col == "可入状态":
                style += "font-weight:700;"
                style += ("color:#1e7e34;" if val in ("可入", "尾窗")
                          else "color:#999;")
            if col == "股票名称":
                style += "font-weight:600;"
            if col == "止损价":
                style += "font-weight:700;color:#c0392b;"
            if col == "止盈价":
                style += "font-weight:700;color:#1e7e34;"
            tds.append(f'<td style="{style}">{_esc(val)}</td>')
        trs.append(f'<tr style="background:{bg};">' + "".join(tds) + "</tr>")
    return (f'<table style="border-collapse:collapse;width:100%;font-family:'
            f'-apple-system,Segoe UI,Microsoft YaHei,sans-serif;">'
            f"<thead><tr>{th}</tr></thead><tbody>{''.join(trs)}</tbody></table>")


def render_html(rows):
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

    def section(title, sub, rs):
        if not rs:
            return ""
        return (f'<h3 style="margin:22px 0 8px;color:#4a3a1a;font-size:16px;">{title}'
                f'<span style="font-weight:400;color:#998;font-size:13px;"> {sub}</span></h3>'
                + _table(rs))

    summary = (
        f'<div style="background:#f6f1e4;border-left:4px solid #c9a84a;padding:12px 16px;'
        f'border-radius:4px;margin-bottom:8px;font-size:14px;color:#4a3a1a;line-height:1.7;">'
        f'<b>扫描日期 {_esc(scan)}</b>　共 <b>{len(rows)}</b> 只'
        f'（A抄底 {nA} / B抢筹 {nB}）<br>'
        f'精选 <b style="color:#b8860b;">{nSel}</b> 只，其中 ★★核心 <b style="color:#b8860b;">{nCore}</b> 只'
        f'　|　资金确认 {nZ}　|　中枢底部 {nZS}<br>'
        f'<span style="color:#888;font-size:12px;">已剔除获利盘&gt;70%、大盘空头/危险已空仓。</span>'
        f'</div>')

    logic = (
        '<h3 style="margin:24px 0 6px;color:#4a3a1a;font-size:16px;">选股逻辑</h3>'
        '<div style="font-size:13px;color:#555;line-height:1.9;">'
        '<b>基础集 A∪B</b>：A 稳健抄底 = 极限抄底（极度超跌反弹）+ 量比≥1.3；'
        'B 主力抢筹 = 尖刺金叉（筹码爆破线上穿堡垒线）。过滤：剔获利盘&gt;70%、大盘空头/危险空仓。<br>'
        '<b>精选★层</b>（样本外 +10~12pt / 全历史滚动 8/9 regime 超基线）：'
        '★精选 = 基础集 ∩ 1买 ∩ 非陷阱（剔「相对强弱≥0」或「大盘多头」）；'
        '★★核心 = ★精选 ∩ 量能金叉。</div>')

    discipline = (
        '<h3 style="margin:20px 0 6px;color:#4a3a1a;font-size:16px;">操作纪律</h3>'
        '<ul style="font-size:13px;color:#555;line-height:1.8;margin:0;padding-left:20px;">'
        '<li>优先级：★★核心 &gt; ★精选 &gt; 普通；同档优先 1买、A∪B 双命中、有资金确认/中枢底部者。</li>'
        '<li><b style="color:#c0392b;">止损(硬纪律)</b>：跌破「止损价」当日即出场，止损价 = max(买入价×0.92, 信号前5日结构低点×0.99) 取更近者；<b>即使当日仍命中买点也照砍</b>(买点是进场理由非持有理由)。</li>'
        '<li><b style="color:#1e7e34;">止盈</b>：达「止盈价」(买入价×1.3) 分批了结，或 +20~30% 移动止盈；遇缠论卖点 + 斐波全多头 / 二连板优先了结。</li>'
        '<li>再买入：止损后勿在同一波下跌中反复抄底；待该股重新触发新买点(1买优先/非陷阱)且大盘非空头危险再进。</li>'
        '<li>择时：大盘转空头/危险一律空仓（系统性危机会使超跌反弹失效，硬约束）。</li>'
        '<li>仓位：稳健组合宜分散（并发 20~30 风险调整收益最优，Sharpe≈1.5/回撤≈-4%）。</li></ul>')

    note = (
        '<p style="color:#999;font-size:12px;margin-top:24px;border-top:1px solid #eee;padding-top:10px;">'
        '⚠ 本清单为提升度/样本外回测口径的研究性参考，非投资建议。附件为同内容 Markdown 与 Excel 文档。<br>'
        f'生成时间 {now}　来源 daily_watchlist.py（稳定组合 A∪B + 精选★层）</p>')

    body = (f'<div style="max-width:920px;margin:0 auto;padding:16px;color:#333;">'
            f'<h2 style="color:#3a2e15;border-bottom:2px solid #c9a84a;padding-bottom:8px;">'
            f'🛡️ 每日稳定选股清单</h2>'
            f'{summary}'
            f'{section("★★ 核心精选", f"({nCore}只 · 1买+非陷阱+量能金叉，优先关注)", core)}'
            f'{section("★ 精选", f"({len(sel)}只 · 1买+非陷阱)", sel)}'
            f'{section("其余命中", f"({len(rest)}只 · 满足A∪B但非1买精选层)", rest)}'
            f'{logic}{discipline}{note}</div>')
    return body, scan, len(rows), nSel, nCore


def main():
    args = sys.argv[1:]
    to_override, dry, csv_path, out_html, slot = None, False, DEFAULT_CSV, None, None
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--to":
            to_override = args[i + 1]; i += 2
        elif a == "--dry":
            dry = True; i += 1
        elif a == "--csv":
            csv_path = args[i + 1]; i += 2
        elif a == "--out":
            out_html = args[i + 1]; i += 2
        elif a == "--slot":
            slot = args[i + 1]; i += 2
        else:
            print(f"未知参数 {a}", file=sys.stderr); sys.exit(2)

    rows = EXP.read_rows(csv_path)          # 复用:按字符串读+zfill(6)保留前导0
    if not rows:
        print("清单为空，跳过推送", file=sys.stderr); sys.exit(1)
    body, scan, n, nSel, nCore = render_html(rows)
    md_text = EXP.render_md(rows)[0]        # 附件:同内容 Markdown 文档
    xlsx_bytes = None                       # 附件:同内容 Excel 文档(openpyxl 缺失则降级跳过)
    try:
        xlsx_bytes = XLS.build_xlsx_bytes(rows)
    except Exception as e:
        print(f"⚠ 生成 Excel 附件失败(本次只附 md): {e}", file=sys.stderr)
    if slot:
        nNew = sum(1 for r in rows if r.get("变化标记", "").startswith("🆕"))
        nChg = sum(1 for r in rows if r.get("变化标记", "").startswith("⤴"))
        subject = f"🛡️盘中选股 {scan} {slot} 时段 / 新出{nNew} 变动{nChg} / 共{n}只"
    else:
        subject = f"【每日选股】{scan} 精选{nSel}只(核心{nCore}) / 共{n}只"

    if slot:
        disclaimer = (
            '<div style="background:#fdecea;border-left:4px solid #d9534f;padding:12px 16px;'
            'border-radius:4px;margin-bottom:12px;font-size:14px;color:#a33;line-height:1.7;">'
            '⚠️ <b>盘中临时态提示</b>：本清单基于<b>未收盘实时 bar</b>，信号为<b>临时态</b>，'
            '随价格变动/收盘后可能消失，仅供盘中参考，非投资建议。</div>')
        hi = [r for r in rows if r.get("变化标记", "")]
        banner = ""
        if hi:
            items = "".join(
                f"<li>{html.escape(r['变化标记'])} <b>{html.escape(str(r.get('股票名称','')))}</b>"
                f" {html.escape(str(r.get('股票代码','')))} · {html.escape(str(r.get('可入状态','')))}"
                f" · {html.escape(str(r.get('买点类型','')))}</li>"
                for r in hi)
            banner = (f"<h3>本时段新增/变动（{len(hi)}）</h3><ul>{items}</ul><hr>")
        body = disclaimer + banner + body   # disclaimer always on top

    if out_html:
        with open(out_html, "w", encoding="utf-8") as f:
            f.write(f"<!doctype html><meta charset='utf-8'><title>{html.escape(subject)}</title>" + body)
        print(f"HTML 预览已写 -> {out_html}")
    if dry:
        print(f"[--dry] 主题: {subject}")
        xinfo = f"，xlsx {len(xlsx_bytes)}字节" if xlsx_bytes else "，xlsx 未生成"
        print(f"[--dry] 行数 {n}；附件md {len(md_text)}字符{xinfo}；未发信。")
        return

    c = load_env(ENV_PATH)
    if c.get("EMAIL_ENABLED", "true").lower() not in ("true", "1", "yes"):
        print("EMAIL_ENABLED 非 true，跳过发信"); return
    server = c.get("SMTP_SERVER", "smtp.163.com")
    port = int(c.get("SMTP_PORT", "465"))
    sender = c["EMAIL_FROM"]
    passwd = c["EMAIL_PASSWORD"]
    to_raw = to_override if to_override else c["EMAIL_TO"]
    tos = [x.strip() for x in to_raw.replace(";", ",").split(",") if x.strip()]

    msg = MIMEMultipart()
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = formataddr(("每日选股", sender))
    msg["To"] = ",".join(tos)
    msg.attach(MIMEText(body, "html", "utf-8"))
    att = MIMEApplication(md_text.encode("utf-8"), _subtype="markdown")
    att.add_header("Content-Disposition", "attachment",
                   filename=("utf-8", "", f"每日稳定选股清单_{scan}.md"))
    msg.attach(att)
    if xlsx_bytes:                          # Excel 附件(xlsx)
        xatt = MIMEApplication(
            xlsx_bytes, _subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        xatt.add_header("Content-Disposition", "attachment",
                        filename=("utf-8", "", f"每日稳定选股清单_{scan}.xlsx"))
        msg.attach(xatt)

    ctx = ssl.create_default_context()
    if port == 465:
        smtp = smtplib.SMTP_SSL(server, port, context=ctx, timeout=25)
    else:
        smtp = smtplib.SMTP(server, port, timeout=25); smtp.starttls(context=ctx)
    with smtp:
        smtp.login(sender, passwd)
        smtp.sendmail(sender, tos, msg.as_string())
    atts = "md" + ("+xlsx" if xlsx_bytes else "")
    print(f"邮件已发送(正文HTML+{atts}附件) -> {tos}（{subject}）")


if __name__ == "__main__":
    main()
