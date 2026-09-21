"""Explicit dependency impact for Knowledge, Analysis and Overview pages.

Impact is intentionally based only on declared dependencies. "related" links,
graph similarity and common sources are not treated as obligations to review.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .core import parse_frontmatter, read_yaml
from .review import upsert_review


def _nodes(root: Path) -> dict[str, dict[str, Any]]:
    nodes: dict[str, dict[str, Any]] = {}
    wiki = root / "wiki"
    if not wiki.exists():
        return nodes

    for path in wiki.rglob("*.md"):
        if path.name in {"INDEX.md", "PURPOSE.md"}:
            continue
        meta, _ = parse_frontmatter(path)
        dependencies: list[str] = []

        for item in meta.get("depends_on", []) or []:
            if isinstance(item, str):
                dependencies.append(item)

        for item in meta.get("references", []) or []:
            if (
                isinstance(item, dict)
                and item.get("relation") == "depends_on"
                and item.get("id")
            ):
                dependencies.append(str(item["id"]))

        if not dependencies and not meta.get("id"):
            continue

        if meta.get("id"):
            node_id = str(meta["id"])
            node_kind = str(meta.get("type", "knowledge"))
        elif path.name == "OVERVIEW.md":
            node_id = "VIEW:" + path.relative_to(root).as_posix()
            node_kind = "overview"
        else:
            node_id = "VIEW:" + path.relative_to(root).as_posix()
            node_kind = "view"

        nodes[node_id] = {
            "id": node_id,
            "kind": node_kind,
            "title": meta.get("title") or path.stem,
            "path": str(path.relative_to(root)),
            "status": meta.get("status"),
            "depends_on": sorted(set(dependencies)),
        }
    return nodes


def dependency_impact(
    root: Path,
    knowledge_id: str,
    *,
    transitive: bool = True,
) -> dict[str, Any]:
    nodes = _nodes(root)
    reverse: dict[str, list[str]] = {}
    for node_id, node in nodes.items():
        for dep in node["depends_on"]:
            reverse.setdefault(dep, []).append(node_id)

    direct_ids = sorted(set(reverse.get(knowledge_id, [])))
    visited: set[str] = set()
    queue = [(node_id, 1) for node_id in direct_ids]
    affected: list[dict[str, Any]] = []

    while queue:
        node_id, depth = queue.pop(0)
        if node_id in visited:
            continue
        visited.add(node_id)
        node = nodes.get(node_id)
        if not node:
            continue
        affected.append({**node, "depth": depth})
        if transitive:
            for child in sorted(set(reverse.get(node_id, []))):
                if child not in visited:
                    queue.append((child, depth + 1))

    return {
        "knowledge_id": knowledge_id,
        "direct": [row for row in affected if row["depth"] == 1],
        "affected": affected,
        "count": len(affected),
    }


def open_dependency_review(
    root: Path,
    knowledge_id: str,
    *,
    content_sha256: str,
    change_id: str | None,
    owner: str,
) -> tuple[str | None, dict[str, Any]]:
    impact = dependency_impact(root, knowledge_id, transitive=True)
    if not impact["affected"]:
        return None, impact

    repository_id = read_yaml(root / ".knowledge/config.yml").get("repository_id")
    affected = [
        {
            "repository_id": repository_id,
            "knowledge_id": row["id"] if not row["id"].startswith("VIEW:") else None,
            "view_id": row["id"] if row["id"].startswith("VIEW:") else None,
            "path": row["path"],
            "kind": row["kind"],
            "depth": row["depth"],
        }
        for row in impact["affected"]
    ]
    review_path = upsert_review(
        root,
        kind="confirm",
        title=f"知识 {knowledge_id} 已修改，需要复核显式依赖",
        description=(
            "目标知识内容已变化；以下页面通过 depends_on / "
            "references.relation=depends_on 显式依赖它，需要确认是否仍然成立。"
        ),
        owner=owner,
        scope_key=f"dependency:{knowledge_id}",
        affected=affected,
        linked_changes=[change_id] if change_id else [],
        evidence_version=content_sha256,
        observation=f"knowledge content changed: {knowledge_id}@{content_sha256}",
    )
    meta, _ = parse_frontmatter(review_path)
    return str(meta["review_id"]), impact
