# chanlun_ui.py
"""缠论选股页：①批量选股(只读 chanlun_signals.db 批次，买点+配对卖点)；
②个股信号查询(实时跑引擎，列单股全历史全部买卖点)。两模式顶部 radio 切换、互不影响。"""
import streamlit as st
from chanlun_selector import ChanlunSelector, DISPLAY_NAMES

_TYPES = ["1买", "2买", "3买"]


# 缠论信号每日收盘后批量预计算、当天只读，故缓存读取结果，避免每次多选交互都重开
# SQLite 查询。TTL 30 分钟远短于「每日 20:00 更新一次」，不会读到跨日陈旧数据。
@st.cache_data(ttl=1800, show_spinner=False)
def _cached_picks(types_key: tuple, scan_date: str):
    return ChanlunSelector().get_chanlun_picks(types=list(types_key), scan_date=scan_date)


# 单股查询为实时计算(加载2000根30分钟K线+分析)，较重，按规整后代码缓存。TTL 同批量。
# 先 _normalize 再缓存，使 sh600519 / 600519 命中同一条目，避免重复计算。
@st.cache_data(ttl=1800, show_spinner="计算中…")
def _cached_single(code: str):
    from chanlun_single import query_stock_signals, _normalize
    return query_stock_signals(_normalize(code))


def _display_single_stock():
    from chanlun_single import DISPLAY_NAMES as SINGLE_NAMES
    st.caption("输入单只股票代码，实时计算该股全历史所有缠论买卖点（1/2/3买 + 1/2/3卖，"
               "日线本级别 + 30分钟次级别确认）。与批量选股相互独立。")
    code = st.text_input("股票代码", placeholder="如 600519 或 sh600519",
                         key="chanlun_single_code")
    if not code.strip():
        st.info("请输入股票代码后查询")
        return
    ok, df, msg = _cached_single(code.strip())
    st.info(msg)
    if not ok or df is None:
        return
    st.dataframe(df.rename(columns=SINGLE_NAMES), width='stretch', height=460)
    st.caption("信号参考价=买卖点当根收盘/极值价；止损位仅买点给出（买点前最近中枢下沿 ZD 与 价×0.98 取低）。"
               "缠论理由含背驰/回踩/突破依据及次级别确认。全历史范围取决于本地日线长度（最多 500 根）。")


def display_chanlun_selector():
    st.markdown('<div class="ftc-section">🌀 缠论选股</div>', unsafe_allow_html=True)

    mode = st.radio("功能", ["批量选股", "个股信号查询"], horizontal=True,
                    label_visibility="collapsed", key="chanlun_mode")
    if mode == "个股信号查询":
        _display_single_stock()
        return

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
