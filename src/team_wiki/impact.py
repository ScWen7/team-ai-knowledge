"""Source revision impact tracking.

A stable source_id survives content revisions. When the bytes change,
V0.3 archives the previous revision, updates source metadata, locates
knowledge that explicitly cites the source, opens/reopens a Review and
creates one CHG describing the affected knowledge.
"""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any

from .core import (
    _rewrite_change_meta,
    create_change,
    index_workspace,
    iter_knowledge_files,
    parse_frontmatter,
    read_yaml,
    utc_now,
    write_yaml,
)
from .intake import find_source_meta
from .review import upsert_review


def knowledge_using_source(root: Path, source_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in iter_knowledge_files(root):
        meta, _ = parse_frontmatter(path)
        if not meta.get("id"):
            continue
        matched = False
        for item in meta.get("evidence", []) or []:
            if isinstance(item, dict) and item.get("source_id") == source_id:
                matched = True
                break
            if isinstance(item, str) and item == source_id:
                matched = True
                break
        if matched:
            rows.append({
                "repository_id": read_yaml(root / ".knowledge/config.yml").get("repository_id"),
                "knowledge_id": meta["id"],
                "path": str(path.relative_to(root)),
                "status": meta.get("status"),
            })
    return rows


def refresh_source(
    root: Path,
    source_id: str,
    new_file: Path,
    *,
    owner: str = "unassigned",
) -> dict[str, Any]:
    meta_path = find_source_meta(root, source_id)
    meta = read_yaml(meta_path)
    current_name = meta.get("original_name")
    if not current_name:
        raise ValueError("source package has no original_name")
    current_file = meta_path.parent / str(current_name)
    if not current_file.is_file():
        raise ValueError(f"source original file missing: {current_file}")
    new_bytes = new_file.read_bytes()
    new_hash = hashlib.sha256(new_bytes).hexdigest()
    old_hash = str(meta.get("content_sha256") or hashlib.sha256(current_file.read_bytes()).hexdigest())
    if new_hash == old_hash:
        return {
            "changed": False,
            "source_id": source_id,
            "content_sha256": old_hash,
            "affected": [],
            "change_id": None,
            "review_id": None,
        }

    revisions = list(meta.get("revisions") or [])
    archive_rel = Path("revisions") / old_hash[:12] / str(current_name)
    archive = meta_path.parent / archive_rel
    archive.parent.mkdir(parents=True, exist_ok=True)
    if not archive.exists():
        shutil.copy2(current_file, archive)
    old_record = {
        "sha256": old_hash,
        "archived_at": utc_now(),
        "path": archive_rel.as_posix(),
    }
    if not any(x.get("sha256") == old_hash for x in revisions if isinstance(x, dict)):
        revisions.append(old_record)

    current_file.write_bytes(new_bytes)
    meta["content_sha256"] = new_hash
    meta["updated_at"] = utc_now()
    meta["status"] = "updated"
    meta["revisions"] = revisions

    affected = knowledge_using_source(root, source_id)
    change_path = create_change(root, f"复核来源 {source_id} 更新影响", owner)
    change_meta, _ = parse_frontmatter(change_path)
    change_id = change_meta["change_id"]

    review_path = upsert_review(
        root,
        kind="confirm",
        title=f"来源 {source_id} 已更新，需要复核依赖知识",
        description="来源内容发生变化；需要确认依赖它的知识是否仍然成立、需收窄范围或需要修订。",
        owner=owner,
        scope_key=f"source:{source_id}",
        affected=affected,
        linked_changes=[change_id],
        evidence_version=new_hash,
        observation=f"source revision changed from {old_hash} to {new_hash}",
    )
    review_meta, _ = parse_frontmatter(review_path)
    review_id = review_meta["review_id"]

    _rewrite_change_meta(change_path, {
        "origin": {"work_ids": [], "source_ids": [source_id]},
        "affected": affected,
        "review_ids": [review_id],
        "evidence_ids": [],
    })
    meta["linked_changes"] = list(dict.fromkeys([*(meta.get("linked_changes") or []), change_id]))
    write_yaml(meta_path, meta)
    index_workspace(root)
    return {
        "changed": True,
        "source_id": source_id,
        "previous_sha256": old_hash,
        "content_sha256": new_hash,
        "affected": affected,
        "change_id": change_id,
        "review_id": review_id,
        "archived_revision": archive_rel.as_posix(),
    }
