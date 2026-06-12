# combo_ui.py
"""缠论×六脉组合选股页: 只读 combo_signals.db 最新批次, 含 🔄 立即刷新。"""
import streamlit as st
from combo_selector import ComboSelector, DISPLAY_NAMES


@st.cache_data(ttl=1800, show_spinner=False)
def _cached_picks():
    return ComboSelector().get_picks()


def _recompute():
    """同步重跑组合扫描(读缠论最新买点)并落当日批次。"""
    from datetime import datetime
    from chanlun_signal_db import ChanlunSignalDB
    from combo_signal_db import ComboSignalDB
    import combo_batch
    scan_date = datetime.now().strftime("%Y-%m-%d")
    combo_db = ComboSignalDB()
    combo_db.clear_scan(scan_date)
    return combo_batch.scan(ChanlunSignalDB(), combo_db, scan_date=scan_date)


def display_combo_selector():
    st.markdown('<div class="ftc-section">🔗 缠论×六脉 组合策略</div>', unsafe_allow_html=True)
    st.caption("组合口径：出现缠论买入信号(1/2/3买)、且其信号日 ±3 交易日窗口内出现六脉神剑 5 红以上"
               "(六维多头数≥5)即选中。缠论买点取每日批量库最新批次。每日定时预计算，本页只读。")

    if st.button("🔄 立即刷新(读当日缠论买点重算)", key="combo_recompute"):
        try:
            with st.spinner("重算组合信号中…"):
                n = _recompute()
            _cached_picks.clear()
            st.success(f"刷新完成, 命中 {n} 只")
            st.rerun()
        except Exception as e:
            st.error(f"刷新失败: {type(e).__name__}: {str(e)[:120]}")

    ok, df, msg = _cached_picks()
    st.info(msg)
    if not ok or df is None:
        return
    st.dataframe(df.rename(columns=DISPLAY_NAMES), width='stretch', height=460)
    st.caption("缠论买点=最新批次内该股买入信号；六脉达标日=缠论信号日±3交易日窗口内首个六脉多头数≥5的交易日。"
               "初筛候选，请人工复核。")
