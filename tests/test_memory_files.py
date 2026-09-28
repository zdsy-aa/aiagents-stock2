# tests/test_memory_files.py
import pathlib

def test_claude_md_has_key_sections():
    t = pathlib.Path("CLAUDE.md").read_text(encoding="utf-8")
    for sec in ("项目结构", "核心逻辑", "关键路径", "运行方式", "重要约定", "已知问题"):
        assert sec in t, sec

def test_claude_memory_file_exists():
    p = pathlib.Path.home() / ".claude/projects/-home-tdxback--claude/memory/aiagents-stock-main-project.md"
    t = p.read_text(encoding="utf-8")
    assert "name: aiagents-stock-main-project" in t
    assert "type: project" in t
