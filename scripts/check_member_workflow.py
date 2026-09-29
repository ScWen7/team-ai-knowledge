#!/usr/bin/env python3
"""Run a synthetic member workflow without writing to any real project.

This validates file/tool interactions, not an LLM answer, actual approval,
nontechnical usability, or the willingness of a real team to adopt the tool.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from team_wiki.agent_entry import setup_agent_entry
from team_wiki.connections import connected_query
from team_wiki.core import init_team, index_workspace
from team_wiki.project import init_project


def write(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def main() -> None:
    with TemporaryDirectory(prefix="team-wiki-member-check-") as directory:
        base = Path(directory)
        project, other, team = base / "project", base / "other", base / "team"
        init_team(team, "sample-team")
        original = write(project, "docs/README.md", "# 构建缓存排查\n适用：示例环境 A；先核对依赖实际版本。\n")
        initial = original.read_bytes()
        init_project(project, project_id="sample-project", team_root=team)
        setup_agent_entry(project, apply=True)
        first = connected_query(project, "构建缓存排查")
        assert first["complete"] and first["sources"][0]["results"][0]["path"] == "docs/README.md"
        assert original.read_bytes() == initial

        # Stand in for a reviewed human/Agent edit using explicit sample text;
        # the toolkit does not invent or approve this conclusion.
        shared = write(team, "wiki/technical/build.md", "# 构建缓存排查\n适用：示例环境 A；先核对依赖实际版本。\n来源：sample-project/docs/README.md（示例）。\n")
        index_workspace(team)
        init_project(other, project_id="sample-consumer", team_root=team)
        reused = connected_query(other, "构建缓存排查")
        assert reused["complete"] and reused["sources"][1]["results"][0]["path"] == "wiki/technical/build.md"
        shared.write_text(shared.read_text(encoding="utf-8") + "反例：示例环境 B 不适用；依据：示例测试记录。\n", encoding="utf-8")
        corrected = connected_query(other, "示例环境")
        assert corrected["sources"][1]["results"][0]["path"] == "wiki/technical/build.md"
        assert "不适用" in shared.read_text(encoding="utf-8")
        assert original.read_bytes() == initial
        assert not (team / "changes").exists()
        assert not (project / ".knowledge/runs").exists()
        print(json.dumps({"ok": True, "synthetic": True,
                          "checks": ["原位README可检索", "初始化不改正文", "跨库经验可发现",
                                     "修正原文下次可读", "不要求管理记录"],
                          "not_proven": ["真实成员愿意使用", "AI回答质量", "业务审核已完成"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
