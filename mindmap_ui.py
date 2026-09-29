"""项目思维导图页:读取 data/mindmap 产物,markmap 渲染,60 秒定时刷新。

产物由宿主机 crontab 每分钟运行 tools/mindmap_generator.py 生成(挂载即时可见)。
"""
import html
import json
from pathlib import Path

import streamlit as st

MINDMAP_DIR = Path(__file__).resolve().parent / "data" / "mindmap"
MD_PATH = MINDMAP_DIR / "project_map.md"
META_PATH = MINDMAP_DIR / "meta.json"

_MARKMAP_TEMPLATE = """<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
  html, body {{ margin: 0; padding: 6px 10px; height: 100%; background: transparent; }}
  #fallback {{ display: none; color: #e06c75; font-size: 14px; padding: 12px; }}
  .markmap svg {{ width: 100%; height: 620px; background: transparent; }}
</style></head><body>
<div class="markmap"><script type="text/template">
{md}
</script></div>
<div id="fallback">脑图 JS 加载失败(CDN 不可达),请检查浏览器网络/代理后刷新本页。</div>
<script>
  setTimeout(function () {{
    if (!document.querySelector('.markmap svg')) {{
      document.getElementById('fallback').style.display = 'block';
    }}
  }}, 4000);
</script>
<script src="https://cdn.jsdelivr.net/npm/markmap-autoloader@0.18"></script>
</body></html>
"""


def _load():
    """读取产物;缺失返回 (None, None)。"""
    if not MD_PATH.exists():
        return None, None
    md = MD_PATH.read_text(encoding="utf-8")
    meta = {}
    if META_PATH.exists():
        try:
            meta = json.loads(META_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            meta = {}
    return md, meta


def display_mindmap():
    st.markdown("## 🧠 项目思维导图")
    st.caption("宿主机每分钟检测项目变更并自动重建导图;本页每 60 秒自动刷新。")
    with st.expander("📖 使用说明与图例", expanded=True):
        st.markdown(
            "- **图例**:📁 目录 = 物理结构;📦 分组节点 = 策略模块(逻辑分组);"
            "`文件 — 中文说明` = 功能注解。\n"
            "- **交互**:鼠标滚轮缩放;按住空白处拖拽平移;点击节点前的圆圈折叠/展开分支。\n"
            "- **更新机制**:宿主机 cron 每分钟检测项目变更并自动重建导图;本页每 60 秒自动刷新;"
            "项目改动最迟约 2 分钟内反映到图中。\n"
            "- **指标**:生成时间(最近一次重建)、节点数(含分组节点)、最近变更文件数(上次重建检测到的变更)、"
            "Git HEAD(当前代码版本)。"
        )

    @st.fragment(run_every=60)
    def _render():
        md, meta = _load()
        if md is None:
            st.info("导图尚未生成。宿主机 crontab 每分钟扫描项目,首次使用请等待 ≤2 分钟,"
                    "或手动执行 `tools/mindmap_generator.py --force`。")
            return
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("生成时间", meta.get("generated_at", "—"))
        c2.metric("节点数", meta.get("node_count", "—"))
        c3.metric("最近变更文件", len(meta.get("changed_files", [])))
        c4.metric("Git HEAD", (meta.get("git_head") or "—")[:8])
        st.components.v1.html(
            _MARKMAP_TEMPLATE.format(md=html.escape(md)), height=720, scrolling=True
        )

    _render()
    if st.button("🔄 立即刷新", use_container_width=True):
        st.rerun()
