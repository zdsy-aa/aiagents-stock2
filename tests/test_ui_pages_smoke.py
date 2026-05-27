# tests/test_ui_pages_smoke.py
from streamlit.testing.v1 import AppTest


def _home_text():
    at = AppTest.from_file("app.py", default_timeout=120).run()
    assert not at.exception, at.exception
    # 收集所有 markdown / 文本元素
    chunks = []
    for el in at.markdown:
        chunks.append(str(el.value))
    return "\n".join(chunks)


def test_learning_video_section_removed():
    text = _home_text()
    assert "学习视频合集" not in text
    assert "新手必看干货" not in text
    # 加固：expander 内的 B站合集内容与链接也应消失
    assert "B站干货合集" not in text
    assert "股票知识讲解合集" not in text
    assert "投资认知提升合集" not in text
