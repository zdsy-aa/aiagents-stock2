# chanlun_ui.py
"""缠论选股页：只读 chanlun_signals.db，按扫描日期选批次(默认最新)，展示买点(含理由)与其后首个卖点(含理由)。"""
import streamlit as st
from chanlun_selector import ChanlunSelector, DISPLAY_NAMES

_TYPES = ["1买", "2买", "3买"]


# 缠论信号每日收盘后批量预计算、当天只读，故缓存读取结果，避免每次多选交互都重开
# SQLite 查询。TTL 30 分钟远短于「每日 20:00 更新一次」，不会读到跨日陈旧数据。
@st.cache_data(ttl=1800, show_spinner=False)
def _cached_picks(types_key: tuple, scan_date: str):
    return ChanlunSelector().get_chanlun_picks(types=list(types_key), scan_date=scan_date)


def display_chanlun_selector():
    st.markdown('<div class="ftc-section">🌀 缠论选股</div>', unsafe_allow_html=True)
    st.caption("严格多级别缠论（日线本级别 + 30分钟次级别确认）·"
               " 选出最近 7 个交易日出现一买/二买/三买的股票。数据源：TDX 本地库。"
               " 信号每日收盘后批量预计算，本页只读结果（初筛候选，请人工复核）。")

    dates = ChanlunSelector().list_dates()
    if not dates:
        st.info("暂无缠论买点信号（批量扫描尚未运行）")
        return

    col1, col2 = st.columns([2, 1])
    with col1:
        picked = st.multiselect("买点类型", _TYPES, default=_TYPES)
    with col2:
        scan_date = st.selectbox("扫描日期", dates, index=0)  # 倒序，默认最新

    ok, df, msg = _cached_picks(tuple(picked), scan_date)
    st.info(msg)
    if not ok or df is None:
        return
    st.dataframe(df.rename(columns=DISPLAY_NAMES), width='stretch', height=460)
    st.caption("买入理由=该买点的缠论依据(背驰/回踩/突破，含次级别确认)；止损=买点下方关键位"
               "(买点前最近中枢下沿与买点价×0.98取低)。卖点=该买点之后出现的首个缠论卖点"
               "(一卖/二卖/三卖)，含信号日期与卖出理由；尚未出现则留空。")
