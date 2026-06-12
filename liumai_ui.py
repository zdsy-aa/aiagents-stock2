# liumai_ui.py
"""六脉神剑选股页: 只读 liumai_signals.db 最新批次(多头数≥5), 含 🔄 立即重算。"""
import streamlit as st
from liumai_selector import LiumaiSelector, DISPLAY_NAMES


@st.cache_data(ttl=1800, show_spinner=False)
def _cached_picks():
    return LiumaiSelector().get_picks()


def _recompute():
    """同步对全池重算六脉并落当日批次。"""
    from datetime import datetime
    from chanlun_universe import list_universe
    from liumai_signal_db import LiumaiSignalDB
    import liumai_batch
    scan_date = datetime.now().strftime("%Y-%m-%d")
    db = LiumaiSignalDB()
    db.clear_scan(scan_date)
    universe = list_universe()
    name_board = {c: (n, b) for c, n, b in universe}
    codes = [c for c, _, _ in universe]
    return liumai_batch.scan_codes(codes, db, scan_date=scan_date, name_board=name_board)


def display_liumai_selector():
    st.markdown('<div class="ftc-section">🔱 六脉神剑选股</div>', unsafe_allow_html=True)
    st.caption("六维(MACD/KDJ/RSI/LWR/BBI/MTM)多头共振 · 选出最新交易日多头数≥5(5红以上)的股票。"
               "数据源：TDX 本地库。每日收盘后批量预计算，本页只读结果(初筛候选，请人工复核)。")

    if st.button("🔄 立即重算(全池, 较慢)", key="liumai_recompute"):
        try:
            with st.spinner("全池重算六脉中…"):
                n = _recompute()
            _cached_picks.clear()
            st.success(f"重算完成, 入库 {n} 只(多头数≥5)")
            st.rerun()
        except Exception as e:
            st.error(f"重算失败: {type(e).__name__}: {str(e)[:120]}")

    ok, df, msg = _cached_picks()
    st.info(msg)
    if not ok or df is None:
        return
    st.dataframe(df.rename(columns=DISPLAY_NAMES), width='stretch', height=460)
    st.caption("多头数=六维中多头维度个数(0-6)；得分=加权(MACD/BBI/MTM各20, KDJ/RSI各15, LWR10)；"
               "状态: ≥70强势/40-70偏多/20-40震荡/≤20偏空。各维列 1=多头 0=空头。")
