# views/top_nav.py
"""顶部水平主导航：5 大类 + 当前页标题。点大类→落地其首个子页(分析=首页)。"""
import streamlit as st

from views.nav_model import NAV, all_flags, current_category, category_default_flag


def _go(flag):
    for f in all_flags():
        st.session_state.pop(f, None)
    if flag:
        st.session_state[flag] = True
    st.rerun()


def render_top_nav():
    """主区顶端渲染 5 大类导航 + 当前页标题。"""
    cur = current_category()
    st.markdown('<div class="topnav-bar"></div>', unsafe_allow_html=True)
    cols = st.columns(len(NAV))
    for i, (cat, icon, _pages) in enumerate(NAV):
        with cols[i]:
            if st.button(f"{icon} {cat}", key=f"topnav_{cat}", width='stretch',
                         type=("primary" if cat == cur else "secondary")):
                _go(category_default_flag(cat))

    # 当前页标题（分明）
    title = "🏠 股票分析-日"
    for _, _, pages in NAV:
        for label, flag, _ in pages:
            if flag and st.session_state.get(flag):
                title = label
    st.markdown(f'<div class="topnav-title">{title}</div>', unsafe_allow_html=True)
