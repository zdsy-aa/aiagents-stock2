# -*- coding: utf-8 -*-
"""项目资产说明文档校验(Phase6 Task6.2)。

校验 docs/项目资产说明.md 的八大类章节与真实路径引用:
- 章节存在性(代码/指标/策略/数据/配置/脚本/文档/回测结果/已知问题)
- 引用 Phase 1 资产清单与 Phase 2~5 四大包的真实路径
"""
import pathlib


def test_asset_doc_eight_sections():
    t = pathlib.Path("docs/项目资产说明.md").read_text(encoding="utf-8")
    for sec in ("代码", "指标", "策略", "数据", "配置", "脚本", "文档", "回测结果", "已知问题"):
        assert f"## {sec}" in t or f"# {sec}" in t, sec


def test_asset_doc_references_real_paths():
    t = pathlib.Path("docs/项目资产说明.md").read_text(encoding="utf-8")
    for p in ("indicators/", "backtest/", "interfaces/", "automation/", "docs/ASSETS.md"):
        assert p in t
