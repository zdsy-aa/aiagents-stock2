# current_strategy_ui.py —— 「📋 当前策略」只读页：按四类集中展示策略脚本名+中文解释+关键参数。
# C方案：对机器可读配置(star_thresholds.json/每日清单/共性产物)实时读真值，全部 try/except 容错。
import os
import glob
import json
import streamlit as st

from strategy_catalog import CATALOG, CATEGORIES

# 容器内路径(与 stable_ui 一致；宿主机/无文件时实时读取优雅回退为"—")
STAR_THRESH = "/app/data/profit_mining/star_thresholds.json"
WATCHLIST = "/app/data/profit_mining/每日自选股清单.csv"
COMMONALITY_DIR = "/app/data/commonality_reports"


def _read_star_thresholds():
    """读 star_thresholds.json，返回 {ok, text}。失败优雅回退。"""
    try:
        with open(STAR_THRESH, "r", encoding="utf-8") as f:
            d = json.load(f)
        tiers = "、".join(f"{k}({v.get('n_stars','?')}★)" for k, v in d.get("tiers", {}).items())
        oos = d.get("oos", ["?", "?"])
        text = (f"胜率口径 ≥{d.get('win_thresh','?')}% / 大涨 ≥{d.get('bigrise_thresh','?')}%；"
                f"训练截止 {d.get('train_end','?')}，样本外 {oos[0]}~{oos[-1]}；分层：{tiers or '—'}")
        return {"ok": True, "text": text}
    except Exception as e:
        return {"ok": False, "text": f"— (未读到 star_thresholds.json：{type(e).__name__})"}


def _read_watchlist_stat():
    """读每日自选股清单的候选数与更新时间，返回 {ok, text}。"""
    try:
        if not os.path.exists(WATCHLIST):
            raise FileNotFoundError(WATCHLIST)
        import pandas as pd
        df = pd.read_csv(WATCHLIST, encoding="utf-8-sig", dtype=str)
        import datetime
        mt = datetime.datetime.fromtimestamp(os.path.getmtime(WATCHLIST)).strftime("%Y-%m-%d %H:%M")
        return {"ok": True, "text": f"最新清单 {len(df)} 只候选，更新于 {mt}"}
    except Exception as e:
        return {"ok": False, "text": f"— (暂无每日清单：{type(e).__name__})"}


def _read_commonality_latest():
    """列出共性挖掘最近一次产物(按文件名时间戳)，返回 {ok, text}。"""
    try:
        files = glob.glob(os.path.join(COMMONALITY_DIR, "*"))
        files = [f for f in files if os.path.isfile(f)]
        if not files:
            raise FileNotFoundError(COMMONALITY_DIR)
        latest = max(files, key=os.path.getmtime)
        import datetime
        mt = datetime.datetime.fromtimestamp(os.path.getmtime(latest)).strftime("%Y-%m-%d %H:%M")
        return {"ok": True, "text": f"最近产物 {os.path.basename(latest)}（{mt}）"}
    except Exception as e:
        return {"ok": False, "text": f"— (暂无共性挖掘产物：{type(e).__name__})"}


def _render_live(key):
    """按 entry['实时'] 渲染实时区块。"""
    if key == "star":
        st.caption("🔢 实时阈值：" + _read_star_thresholds()["text"])
    elif key == "watchlist":
        st.caption("🔢 实时清单：" + _read_watchlist_stat()["text"])
    elif key == "commonality":
        st.caption("🔢 结论新鲜度：" + _read_commonality_latest()["text"])
    elif key == "plans":
        try:
            import pandas as pd
            from stable_ui import PLANS
            st.dataframe(pd.DataFrame(PLANS)[["方案", "买点", "卖点"]],
                         width="stretch", hide_index=True)
        except Exception as e:
            st.caption(f"— (未读到稳定方案：{type(e).__name__})")


def _render_entry(e):
    with st.expander(e["名称"], expanded=False):
        st.markdown("**承载脚本**：" + " ".join(f"`{s}`" for s in e["脚本"]))
        st.markdown(e["解释"])
        if e["关键参数"]:
            st.markdown("**关键可调参数**：")
            for name, where, val in e["关键参数"]:
                st.markdown(f"- **{name}** — `{where}`：{val}")
        if e["实时"]:
            _render_live(e["实时"])


def display_current_strategy():
    st.markdown('<div class="ftc-section">📋 当前策略</div>', unsafe_allow_html=True)
    st.caption("只读总览：集中查看全部 选股/买入卖出/测试盈利/找共同点 策略的承载脚本与中文说明，"
               "方便识别后自行决定修改——改完告诉我(脚本名)，由我改代码并重跑验证。前台不在线编辑。")
    for cat in CATEGORIES:
        items = [e for e in CATALOG if e["类别"] == cat]
        st.markdown(f"#### 🗂️ {cat}策略（{len(items)}）")
        for e in items:
            _render_entry(e)
        st.divider()
