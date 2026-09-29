"""Install the always-on agent instructions into a repository's AGENTS.md.

Only the marked block is owned by team-wiki; every other line is preserved.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import core

BEGIN = "<!-- team-wiki:begin -->"
END = "<!-- team-wiki:end -->"

_BASELINE = (
    "1. 开工前运行 `team-wiki project-rules . <团队库路径>`，完整读取项目订阅的共同底线；"
    "不得用搜索排名替代。\n"
)
_NO_BASELINE = "1. 本仓库未订阅团队底线；如项目另有规则入口，先读取它。\n"


def _block(has_baseline: bool) -> str:
    return f"""{BEGIN}
## 知识库使用约定

开工前：
{_BASELINE if has_baseline else _NO_BASELINE}2. 按任务运行 `team-wiki search . "<问题>"`，只采信状态与适用范围匹配的结果；核对原文后再使用。
3. 没有找到时明确说明“未找到”，不要凭印象补全。`warning:` 表示有文件被跳过，需告知负责人。

收工前：
- 本次是否产生可复用的决策、踩坑或对已有知识的修正？有：写入所属项目文档的原位置，写明适用条件与证据，随代码一并提交审核；没有：说明“无需沉淀”。
- 已有知识与实际不符：在原文件提出修改并说明依据，不静默覆盖。
- 检索没找到本应存在的知识，或命中了错误知识：把问题和期望文档追加到 `.knowledge/eval.yml`。
{END}
"""


def _has_baseline(root: Path) -> bool:
    path = root / ".knowledge/config.yml"
    if not path.is_file() or path.is_symlink():
        return False
    try:
        return bool(core.read_yaml(path).get("knowledge_sources"))
    except Exception:
        return False


def setup_agent_entry(root: Path, *, apply: bool = False) -> dict[str, Any]:
    root = root.resolve()
    target = root / "AGENTS.md"
    if target.is_symlink():
        raise ValueError("AGENTS.md must not be a symlink")
    block = _block(_has_baseline(root))
    current = target.read_text(encoding="utf-8") if target.is_file() else ""
    start, stop = current.find(BEGIN), current.find(END)
    if (start == -1) != (stop == -1) or (start != -1 and stop < start):
        raise ValueError("AGENTS.md has an unbalanced team-wiki marker; fix it manually")
    if start != -1:
        updated = current[:start] + block + current[stop + len(END):].lstrip("\n")
        if not updated.endswith("\n"):
            updated += "\n"
    elif current:
        updated = current.rstrip("\n") + "\n\n" + block
    else:
        updated = block
    changed = updated != current
    if apply and changed:
        target.write_text(updated, encoding="utf-8")
    return {"path": "AGENTS.md", "changed": changed, "applied": bool(apply and changed),
            "created": not current and changed}
