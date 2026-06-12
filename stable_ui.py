# stable_ui.py —— 稳定选股页：展示经样本外验证的买卖方案 + 今日选股清单。
# 方案来自 data/profit_mining 的研究结论(极限抄底/尖刺金叉/过热顶卖点，均经walk-forward验证)。
import os
import sqlite3
import streamlit as st
import pandas as pd

WATCHLIST = "/app/data/profit_mining/每日自选股清单.csv"
HISTDIR = "/app/data/profit_mining/watchlist_history"   # 按扫描日期的历史选股记录
SIGDB = "/app/data/chanlun_signals.db"

# ── 方案目录（每条规则均经样本外检验，胜率为2025测试段口径）──
PLANS = [
    {
        "方案": "稳健抄底 (核心A)",
        "方案详细说明": "缠论买点处于极度超跌反弹且温和放量。震荡/中性市、尤其1买最佳。"
                  "样本外(2025)胜率82%，超基线+37pt。本质=抄在恐慌底。",
        "买点": "缠论买点 + 极限抄底 + 量比≥1.3（+机构净买资金确认）",
        "买点说明": "极限抄底=20日跌≥15%或60日跌≥25%，且RSI6≤20，且当日止跌(阳线长下影或收盘多方占比>0.7)；"
                "量比≥1.3=当日量/前5日均量(实测最优阈值，1买优先，距60日高点越低越好)。"
                "【全量信号库研究·2026-06-01加分项】当日机构净买(资金强度>0)→有资金承接，盈利覆盖更广(缠论买点叠加后提升度↑至1.15)，清单已打“资金确认”标。",
        "卖点": "缠论卖点 + 过热顶(均线全多头/连板) 或 强势顶(相对强弱≥5+六脉红灯+MA20上行) / +25~30%移动止盈",
        "卖点说明": "出现过热顶优先了结：①连续涨停 或 均线5/13/34/55/89/144/233全多头排列(原样本外好卖率80%)；"
                "②【全量信号库研究新增·提升度1.5~1.68，全表最高】相对强弱≥5(显著强于大盘)+六脉红灯≥5+MA20上行/多周期做多权重偏多——"
                "此类强势过热后30日内回落≥10%概率最高；或+20%保本、+25~30%移动止盈分批，勿死等下一买点。",
    },
    {
        "方案": "主力抢筹 (核心B)",
        "方案详细说明": "筹码爆破线上穿堡垒线=主力快速抢筹。1买样本外胜率82%，与抄底挑不同的票(互补)。",
        "买点": "缠论买点(1买) + 尖刺金叉",
        "买点说明": "尖刺金叉=由换手率重建的筹码分布中，当日获利增量(爆破线)上穿+10%以内获利(堡垒线)，"
                "代表资金集中抢筹。优先1买。",
        "卖点": "同核心A(过热顶了结 / 移动止盈)",
        "卖点说明": "同核心A。",
    },
    {
        "方案": "稳定组合 (A∪B，★推荐)",
        "方案详细说明": "抄底∪抢筹并集，覆盖最广(历史信号1191)、样本外胜率78%、超基线+33pt。"
                  "兼顾胜率与覆盖，作为主用规则。",
        "买点": "(极限抄底+量比≥1.3) 或 (尖刺金叉)，1买优先（机构净买/中枢底部 加分排序）",
        "买点说明": "满足核心A或核心B任一即入选；剔除获利盘>70%/筹码集中的票(上方抛压大)。"
                "【全量信号库研究】叠加“机构净买”资金确认 与 缠论“中枢极限底/底部回升”结构者优先排序(清单含资金确认/中枢底部标)。",
        "卖点": "缠论卖点+过热顶/强势顶 / 移动止盈",
        "卖点说明": "同核心A（含强势顶：相对强弱≥5+六脉红灯+MA20上行）。",
    },
]

# ── 纪律/适用条件 ──
NOTES = [
    ("适用市场", "只在 震荡市 / 多头市 且 大盘非空头·非危险 时执行；大盘空头/危险 → 空仓(规则在此环境无效)。"),
    ("观察窗口", "信号匹配用 ±0~±1 交易日更纯(胜率76%)，±2 提高召回但精度略降。"),
    ("反向过滤", "命中则放弃：获利盘>70%、筹码集中、贴近前高(距60日高点≥0.9)、纳财等打板形态。"),
    ("资金面确认", "【全量信号库研究·2026-06-01】机构净买(资金强度>0)是买卖两端最普适的共性信号，几乎所有买卖点组的共同特征榜首；"
                "买点叠加它盈利覆盖更广，本页作为加分排序而非硬过滤(覆盖约80%、单列提升度~1.08，不宜当硬门槛)。"),
    ("卖点强势顶", "【全量信号库研究】缠论卖点中“相对强弱≥5+六脉红灯+MA20上行/做多权重偏多”这组强势过热确认，"
                "提升度1.5~1.68为全研究最高——卖在强势耗尽处。注意此为241.9万事件的提升度口径，非walk-forward样本外胜率，作锦上添花用。"),
    ("仓位/预期", "分散(并发10-20、单仓5-10%)；真实前瞻胜率预期65-80%，勿用样本内复杂三联(会回落到55%)。"),
]


def _list_scan_dates():
    """历史选股记录里所有扫描日期(倒序，最新在前)。"""
    import glob
    dates = []
    for fp in glob.glob(f"{HISTDIR}/每日自选股清单_*.csv"):
        d = os.path.basename(fp).replace("每日自选股清单_", "").replace(".csv", "")
        dates.append(d)
    return sorted(set(dates), reverse=True)


def _selected_by_date(scan_date):
    """读指定扫描日期的选股记录。scan_date=None 读 latest。返回 (df 或 None, 提示)。"""
    path = WATCHLIST if not scan_date else f"{HISTDIR}/每日自选股清单_{scan_date}.csv"
    if os.path.exists(path):
        try:
            df = pd.read_csv(path, encoding="utf-8-sig", dtype={"股票代码": str})
            tag = f"扫描日期 {scan_date}" if scan_date else \
                f"最新(更新于 {pd.Timestamp(os.path.getmtime(path), unit='s'):%Y-%m-%d %H:%M})"
            return df, f"{tag}，共 {len(df)} 只(规则:稳定组合 A∪B=极限抄底+量比≥1.3 或 尖刺金叉；已剔除获利盘>70%、大盘非空头/危险，1买优先)。"
        except Exception as e:
            return None, f"读取记录失败: {type(e).__name__}"
    return None, "该日期暂无记录。点上方按钮生成今日清单(读最近缠论买点批次)。"


def _recompute_watchlist():
    import sys
    sys.path.insert(0, "/app/data/profit_mining")
    import importlib
    dw = importlib.import_module("daily_watchlist")
    dw.main()


def display_stable_selector():
    st.markdown('<div class="ftc-section">🛡️ 稳定选股（经样本外验证的买卖策略）</div>', unsafe_allow_html=True)
    st.caption("基于全历史缠论买点研究：经 walk-forward 样本外检验的稳健规则(抄底/抢筹/过热顶)；"
               "并融入2026-06-01全量信号库(241.9万事件)共同特征挖掘结论——买点加“机构净买”资金确认、卖点补“强势顶”(相对强弱≥5+六脉红灯+MA20上行，提升度全表最高)。"
               "下表为方案与买卖说明，可直接照用；底部为今日符合规则的候选股。")

    # 方案表
    st.markdown("**📋 策略方案与买卖说明**")
    plan_df = pd.DataFrame(PLANS)[["方案", "方案详细说明", "买点", "买点说明", "卖点", "卖点说明"]]
    st.dataframe(plan_df, width='stretch', height=300, hide_index=True)

    with st.expander("📌 适用条件 / 纪律（务必遵守）", expanded=False):
        for k, v in NOTES:
            st.markdown(f"- **{k}**：{v}")

    st.divider()
    # 选股记录(按扫描日期保留历史)
    st.markdown("**🎯 选股记录（稳定组合规则，按扫描日期保留）**")
    st.caption("提示：每日 20:00 缠论批量后自动生成并按扫描日期存档(本页只读)；手动刷新需重抓换手率算尖刺金叉，约数分钟。")
    hist_dates = _list_scan_dates()
    pick = st.selectbox(f"📅 按扫描日期查看历史记录（共 {len(hist_dates)} 天存档）",
                        ["最新"] + hist_dates, index=0, key="stable_date")
    if st.button("🔄 生成/刷新今日清单(读最近缠论买点批次)", key="stable_recompute"):
        try:
            with st.spinner("按稳定规则筛选中(含筹码计算，约数分钟)…"):
                _recompute_watchlist()
            st.success("刷新完成")
            st.rerun()
        except Exception as e:
            st.error(f"刷新失败: {type(e).__name__}: {str(e)[:120]}")

    scan_date = None if pick == "最新" else pick
    df, msg = _selected_by_date(scan_date)
    st.info(msg)
    if df is not None and len(df):
        # 可入状态：旧记录无此列则补“—”（历史 CSV 不回填）
        if "可入状态" not in df.columns:
            df["可入状态"] = "—"
        # 前置列（更醒目）：可入状态 + 星级/预估胜率/大涨率。整体已按层主键+层内星数倒序排好
        front = [c for c in ["可入状态", "星级", "预估胜率", "大涨率"] if c in df.columns]
        df = df[front + [c for c in df.columns if c not in front]]
        st.caption("🟢 **可入状态=在该扫描日，这条信号是否仍可按原计划进场**（以扫描日收盘价判定，"
                   "价格类优先于窗口类）：**可入**=信号日起≤1交易日且价格仍在区间(最纯)；**尾窗**=第2个交易日(±2，精度略降)；"
                   "**已过窗**=超过2交易日；**已涨过**=收盘较买入价高出>5%(追高，性价比差)；"
                   "**已破止损**=收盘跌破止损价；**已止盈**=收盘已达止盈价；**—**=旧记录未记此列。")
        if "星级" in df.columns:
            st.caption("⭐ **星级=经样本外(2024~2025.10)验证的上涨概率分档**，越多星该层内越易涨（"
                       "核心5★：★≈68%→★★★★★≈85%；精选2★：★≈73%/★★≈81%，主口径30日内涨幅≥4%）。"
                       "“预估胜率/大涨率”为该档样本外胜率(≥4%)/大涨率(≥10%)，是历史验证值、非未来保证。")
        st.dataframe(df, width='stretch', height=420, hide_index=True)
        st.caption("初筛候选，请结合大盘环境与个股基本面人工复核；买卖执行参照上方方案说明。")
