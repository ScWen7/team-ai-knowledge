"""Candidate knowledge and safe Knowledge Patch Plans.

V0.5 intentionally does not ask deterministic code to infer semantic meaning.
The current Agent / domain owner supplies the candidate statement and its
comparison to existing knowledge. This module validates evidence grounding,
captures an optimistic-concurrency base, creates CHG/Review records, and
safely applies an Agent-produced full Markdown revision.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml

from .core import (
    _rewrite_change_meta,
    create_change,
    index_workspace,
    knowledge_ref,
    parse_frontmatter,
    read_yaml,
    utc_now,
    write_yaml,
)
from .evidence import list_bindings, read_evidence
from .review import upsert_review


COMPARISONS = {"new", "adds", "narrows", "contradicts", "duplicates"}
ACTIONS = {
    "new": "create",
    "adds": "update",
    "narrows": "update",
    "contradicts": "review",
    "duplicates": "no-change",
}
KNOWLEDGE_TYPES = {"rule", "concept", "decision", "guide", "pitfall", "process", "analysis"}


def _records(root: Path, kind: str) -> Path:
    return root / ".knowledge/records" / kind


def candidate_path(root: Path, candidate_id: str) -> Path:
    path = _records(root, "candidates") / f"{candidate_id}.yml"
    if not path.is_file():
        raise KeyError(f"candidate id not found: {candidate_id}")
    return path


def patch_plan_path(root: Path, plan_id: str) -> Path:
    path = _records(root, "patch-plans") / f"{plan_id}.yml"
    if not path.is_file():
        raise KeyError(f"patch plan id not found: {plan_id}")
    return path


def create_candidate(
    root: Path,
    *,
    proposed_id: str,
    title: str,
    knowledge_type: str,
    statement: str,
    owner: str = "unassigned",
    scope: str = "team",
) -> Path:
    if knowledge_type not in KNOWLEDGE_TYPES:
        raise ValueError(f"invalid knowledge type: {knowledge_type}")
    if not proposed_id.strip():
        raise ValueError("proposed_id is required")
    if not statement.strip():
        raise ValueError("candidate statement is required")
    key = f"{proposed_id}|{title}|{knowledge_type}|{statement}|{scope}"
    candidate_id = "CAND-" + hashlib.sha256(key.encode()).hexdigest()[:12].upper()
    path = _records(root, "candidates") / f"{candidate_id}.yml"
    if not path.exists():
        write_yaml(path, {
            "candidate_id": candidate_id,
            "proposed_id": proposed_id,
            "title": title,
            "knowledge_type": knowledge_type,
            "statement": statement,
            "scope": scope,
            "owner": owner,
            "status": "proposed",
            "created": utc_now(),
            "patch_plan_ids": [],
        })
    return path


def candidate_context(root: Path, candidate_id: str) -> dict[str, Any]:
    candidate = read_yaml(candidate_path(root, candidate_id))
    bindings = list_bindings(root, target_id=candidate_id)
    evidence = []
    for binding in bindings:
        current = read_evidence(root, binding["evidence_id"], corrected=True)
        evidence.append({
            "binding_id": binding["binding_id"],
            "evidence_id": binding["evidence_id"],
            "relation": binding["relation"],
            "note": binding.get("note", ""),
            "source_id": current["source_id"],
            "source_revision": current["source_revision"],
            "evidence_sha256": current["current_sha256"],
            "locator": current["locator"],
            "text": current["current_text"],
        })
    return {"candidate": candidate, "evidence": evidence}


def _safe_wiki_target(root: Path, relative_path: str) -> Path:
    rel = Path(relative_path)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError("target_path must be repository-relative")
    target = (root / rel).resolve()
    wiki = (root / "wiki").resolve()
    if not target.is_relative_to(wiki):
        raise ValueError("patch plan target must be inside wiki/")
    if target.suffix.lower() != ".md":
        raise ValueError("patch plan target must be a Markdown file")
    return target


def create_patch_plan(
    root: Path,
    candidate_id: str,
    *,
    comparison: str,
    summary: str,
    owner: str = "unassigned",
    target_knowledge_id: str | None = None,
    target_path: str | None = None,
) -> Path:
    if comparison not in COMPARISONS:
        raise ValueError(f"invalid comparison: {comparison}")
    ctx = candidate_context(root, candidate_id)
    candidate = ctx["candidate"]
    evidence = ctx["evidence"]
    if not evidence:
        raise ValueError("candidate must bind at least one evidence chunk before planning")

    action = ACTIONS[comparison]
    proposed_id = str(candidate["proposed_id"])
    target: dict[str, Any]

    if comparison == "new":
        if target_knowledge_id and target_knowledge_id != proposed_id:
            raise ValueError("new knowledge target id must match candidate proposed_id")
        if not target_path:
            raise ValueError("new knowledge requires target_path")
        path = _safe_wiki_target(root, target_path)
        if path.exists():
            raise ValueError(f"new knowledge target already exists: {target_path}")
        target = {
            "knowledge_id": proposed_id,
            "path": str(path.relative_to(root)),
            "base_sha256": None,
        }
    else:
        if not target_knowledge_id:
            raise ValueError(f"{comparison} comparison requires target_knowledge_id")
        path, meta, digest = knowledge_ref(root, target_knowledge_id)
        target = {
            "knowledge_id": target_knowledge_id,
            "path": str(path.relative_to(root)),
            "base_sha256": digest,
            "base_status": meta.get("status"),
            "base_title": meta.get("title"),
        }

    evidence_ids = [row["evidence_id"] for row in evidence]
    source_ids = sorted({row["source_id"] for row in evidence})
    evidence_version = hashlib.sha256(
        "|".join(sorted(f"{row['evidence_id']}:{row['evidence_sha256']}" for row in evidence)).encode()
    ).hexdigest()

    key = (
        f"{candidate_id}|{comparison}|{target['knowledge_id']}|"
        f"{target.get('base_sha256')}|{summary}|{evidence_version}"
    )
    plan_id = "PLAN-" + hashlib.sha256(key.encode()).hexdigest()[:12].upper()
    path = _records(root, "patch-plans") / f"{plan_id}.yml"
    if path.exists():
        return path

    change_id = None
    review_id = None
    if action != "no-change":
        change = create_change(root, f"Knowledge Patch Plan {plan_id}: {candidate['title']}", owner)
        change_meta, _ = parse_frontmatter(change)
        change_id = change_meta["change_id"]
        affected = []
        if comparison != "new":
            affected.append({
                "repository_id": read_yaml(root / ".knowledge/config.yml").get("repository_id"),
                "knowledge_id": target["knowledge_id"],
                "content_sha256": target.get("base_sha256"),
            })
        _rewrite_change_meta(change, {
            "origin": {"work_ids": [], "source_ids": source_ids},
            "affected": affected,
            "evidence_ids": evidence_ids,
            "patch_plan_ids": [plan_id],
        })

    if comparison == "contradicts":
        review = upsert_review(
            root,
            kind="contradiction",
            title=f"候选 {candidate_id} 与知识 {target['knowledge_id']} 冲突",
            description=summary,
            owner=owner,
            scope_key=f"knowledge:{target['knowledge_id']}",
            affected=[{
                "repository_id": read_yaml(root / ".knowledge/config.yml").get("repository_id"),
                "knowledge_id": target["knowledge_id"],
                "path": target["path"],
            }],
            linked_changes=[change_id] if change_id else [],
            evidence_version=evidence_version,
            observation=f"candidate={candidate_id}; comparison=contradicts",
        )
        review_meta, _ = parse_frontmatter(review)
        review_id = review_meta["review_id"]

    write_yaml(path, {
        "plan_id": plan_id,
        "status": "proposed" if action in {"create", "update"} else action,
        "action": action,
        "candidate_id": candidate_id,
        "comparison": comparison,
        "summary": summary,
        "owner": owner,
        "created": utc_now(),
        "target": target,
        "evidence": [
            {
                "binding_id": row["binding_id"],
                "evidence_id": row["evidence_id"],
                "relation": row["relation"],
                "source_id": row["source_id"],
                "source_revision": row["source_revision"],
                "evidence_sha256": row["evidence_sha256"],
            }
            for row in evidence
        ],
        "evidence_version": evidence_version,
        "change_id": change_id,
        "review_id": review_id,
        "applied": None,
    })

    candidate_path_obj = candidate_path(root, candidate_id)
    candidate_record = read_yaml(candidate_path_obj)
    candidate_record["patch_plan_ids"] = list(dict.fromkeys([
        *(candidate_record.get("patch_plan_ids") or []),
        plan_id,
    ]))
    candidate_record["status"] = "planned"
    write_yaml(candidate_path_obj, candidate_record)
    index_workspace(root)
    return path


def patch_plan_context(root: Path, plan_id: str) -> dict[str, Any]:
    plan = read_yaml(patch_plan_path(root, plan_id))
    ctx = candidate_context(root, plan["candidate_id"])
    target = plan["target"]
    target_content = None
    stale = False
    if plan["action"] == "update":
        path = root / target["path"]
        if path.exists():
            target_content = path.read_text(encoding="utf-8")
            current_sha = hashlib.sha256(path.read_bytes()).hexdigest()
            stale = current_sha != target.get("base_sha256")
        else:
            stale = True
    return {
        "plan": plan,
        "candidate": ctx["candidate"],
        "evidence": ctx["evidence"],
        "target_content": target_content,
        "stale": stale,
        "instruction": (
            "Current Agent should draft the complete target Markdown using the evidence and plan. "
            "Do not claim publication; plan-apply only updates the contribution worktree."
        ),
    }


def apply_patch_plan(root: Path, plan_id: str, content_file: Path) -> Path:
    path = patch_plan_path(root, plan_id)
    plan = read_yaml(path)
    if plan.get("action") not in {"create", "update"}:
        raise ValueError(f"patch plan action cannot be applied: {plan.get('action')}")
    if plan.get("status") == "applied":
        target = root / plan["target"]["path"]
        return target

    target = _safe_wiki_target(root, plan["target"]["path"])
    proposed = content_file.read_text(encoding="utf-8")
    temp = content_file
    meta, _ = parse_frontmatter(temp)
    expected_id = plan["target"]["knowledge_id"]
    if meta.get("id") != expected_id:
        raise ValueError(
            f"proposed Markdown id must be {expected_id}, got {meta.get('id')}"
        )

    if plan["action"] == "update":
        if not target.is_file():
            raise ValueError(f"target knowledge missing: {plan['target']['path']}")
        current_sha = hashlib.sha256(target.read_bytes()).hexdigest()
        if current_sha != plan["target"].get("base_sha256"):
            raise ValueError("patch plan is stale: target knowledge changed since plan creation")
    else:
        if target.exists():
            raise ValueError(f"new target already exists: {plan['target']['path']}")

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(proposed, encoding="utf-8")
    applied_sha = hashlib.sha256(target.read_bytes()).hexdigest()
    plan["status"] = "applied"
    plan["applied"] = {
        "at": utc_now(),
        "path": str(target.relative_to(root)),
        "content_sha256": applied_sha,
    }
    write_yaml(path, plan)

    candidate_record_path = candidate_path(root, plan["candidate_id"])
    candidate = read_yaml(candidate_record_path)
    candidate["status"] = "applied"
    write_yaml(candidate_record_path, candidate)

    if plan.get("change_id"):
        change_path = next(
            iter((root / "changes").rglob(f"{plan['change_id']}.md")),
            None,
        )
        if change_path:
            _rewrite_change_meta(change_path, {
                "stage": "proposed",
                "patch_plan_ids": [plan_id],
            })
    index_workspace(root)
    return target
