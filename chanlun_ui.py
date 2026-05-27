# chanlun_ui.py
"""缠论选股页：只读 chanlun_signals.db 最新批次，展示买点/止损/离场条件。"""
import streamlit as st
from chanlun_selector import ChanlunSelector, DISPLAY_NAMES

_TYPES = ["1买", "2买", "3买"]


def display_chanlun_selector():
    st.markdown('<div class="ftc-section">🌀 缠论选股</div>', unsafe_allow_html=True)
    st.caption("严格多级别缠论（日线本级别 + 30分钟次级别确认）·"
               " 选出最近 7 个交易日出现一买/二买/三买的股票。数据源：TDX 本地库。"
               " 信号每日收盘后批量预计算，本页只读结果（初筛候选，请人工复核）。")

    picked = st.multiselect("买点类型", _TYPES, default=_TYPES)
    ok, df, msg = ChanlunSelector().get_chanlun_picks(types=picked)
    st.info(msg)
    if not ok or df is None:
        return
    st.dataframe(df.rename(columns=DISPLAY_NAMES), width='stretch', height=460)
    st.caption("止损=买点下方关键位；离场条件=出现对应缠论卖点(一卖/二卖/三卖)或跌破止损。")
