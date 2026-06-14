# qizhang_predict_ui.py
"""起涨预测(观察中) 只读页：免责+诚实局限 / C4 回测结论 / 今日候选 / 实盘外战绩表。

纯展示,读 data/qizhang_picks.db。不下单/不发邮件。
"""
import logging

import pandas as pd
import streamlit as st

from qizhang_picks_db import QizhangPicksDatabase

logger = logging.getLogger(__name__)

# C4 回测结论(固化常量,来源:report/起涨回测v2_20260614_*,OOS 2024-01~2025-10)
_BACKTEST = {
    "累计": "+39.8%", "年化": "+21.0%", "Sharpe": "3.27",
    "最大回撤": "-3.1%", "超额(vs上证)": "+6.3%", "上证同期": "+33.5%",
}


@st.cache_data(ttl=1800, show_spinner=False)
def _load():
    db = QizhangPicksDatabase()
    latest = db.get_latest_pick_date()
    picks = db.get_picks_by_date(latest) if latest else pd.DataFrame()
    realized = db.get_realized_df()
    meta = db.get_latest_run_meta()
    return latest, picks, realized, meta


def display_qizhang_predict():
    st.header("📈 起涨预测（观察中）")

    # 1. 免责 + 诚实局限
    st.warning(
        "⚠️ **paper-tracking 观察，非投资建议。** 这是「起涨模型 C4 策略」的实盘外跟踪，"
        "不下单、不构成任何买卖建议。\n\n"
        "**诚实局限**：① Sharpe 受回测「槽位法」净值影响偏高，累计/超额比 Sharpe 量级更可信；"
        "② 回测仅单一 OOS 期(2024-2025 牛市)，非跨牛熊 walk-forward，换震荡/熊市表现会变；"
        "③ 未建模涨跌停/停牌不可成交，滑点仅按固定 0.2% 估算。")

    try:
        latest, picks, realized, meta = _load()
    except Exception as e:
        logger.exception("起涨预测页加载失败")
        st.info("尚无数据（日批未跑或库未生成）。")
        return

    # 2. C4 回测结论(静态)
    st.subheader("📊 C4 策略回测结论（OOS 2024-01~2025-10）")
    cols = st.columns(len(_BACKTEST))
    for col, (k, v) in zip(cols, _BACKTEST.items()):
        col.metric(k, v)
    st.caption("C4 = 移动止盈(8%回撤) + 大盘择时(上证<MA20 停开仓)；每日 top10 等权、t+1 开盘买、扣 0.2% 成本。")

    # 3. 今日候选
    st.subheader("🎯 今日候选")
    if meta and meta.get("status") == "failed":
        st.error("今日批跑失败，未产候选。")
    elif meta and int(meta.get("sh_ma20_gate") or 0) == 1:
        st.info("🛡️ 今日大盘择时＝避险（上证收盘<MA20），按 C4 规则**不开新仓**。")
    elif latest and not picks.empty:
        st.caption(f"扫描日：{latest}（共 {len(picks)} 只）")
        show = picks[["rank", "code", "name", "score", "entry_ref_price"]].copy()
        show.columns = ["排名", "代码", "名称", "模型分", "参考价(最新收盘)"]
        st.dataframe(show, hide_index=True, width="stretch")
    else:
        st.info("尚无今日候选（日批未跑）。")

    # 4. 实盘外战绩表
    st.subheader("📈 实盘外战绩（随时间生长）")
    if realized is None or realized.empty:
        st.info("样本积累中（候选需 ≥1 个完整持有窗到期后才计入战绩）。")
    else:
        n = len(realized)
        win = float((realized["realized_return"] > 0).mean())
        hit = float((realized["hit_10pct"] == 1).mean())
        avg = float(realized["realized_return"].mean())
        cum = float((1.0 + realized["realized_return"]).prod() - 1.0)
        bench = realized["bench_return"].dropna()
        bench_cum = float((1.0 + bench).prod() - 1.0) if len(bench) else 0.0
        c = st.columns(5)
        c[0].metric("已到期候选", n)
        c[1].metric("胜率", f"{win:.1%}")
        c[2].metric("命中+10%率", f"{hit:.1%}")
        c[3].metric("平均净收益", f"{avg:+.2%}")
        c[4].metric("累计 vs 上证", f"{cum:+.1%} / {bench_cum:+.1%}")
        st.caption("退出原因分布：" + "，".join(
            f"{k} {v}" for k, v in realized["exit_reason"].value_counts().items()))
