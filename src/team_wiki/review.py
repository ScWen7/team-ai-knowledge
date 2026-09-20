"""Persistent knowledge-review records.

The stable-id and preserve/resurface behavior is inspired by
nashsu/llm_wiki@e8082119 src/stores/review-store.ts (GPLv3).
This implementation adds repository scope, evidence versions,
history, explicit reopen semantics, and Git-file persistence.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from .core import parse_frontmatter, utc_now


KINDS = {"contradiction", "duplicate", "missing-page", "confirm", "suggestion"}
STATES = {"open", "in-progress", "blocked", "resolved", "dismissed"}


def _normalize_title(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold())


def review_id_for(kind: str, title: str, scope_key: str = "team") -> str:
    if kind not in KINDS:
        raise ValueError(f"invalid review kind: {kind}")
    key = f"{kind}::{scope_key}::{_normalize_title(title)}"
    return "REV-" + hashlib.sha256(key.encode()).hexdigest()[:10].upper()


def find_review(root: Path, review_id: str) -> Path | None:
    base = root / "changes/reviews"
    if not base.exists():
        return None
    return next(iter(base.rglob(f"{review_id}.md")), None)


def _write(path: Path, meta: dict[str, Any], body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n" + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False).rstrip()
        + "\n---\n" + body.lstrip("\n"),
        encoding="utf-8",
    )


def _uniq_dicts(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in items:
        key = yaml.safe_dump(item, allow_unicode=True, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def upsert_review(
    root: Path,
    *,
    kind: str,
    title: str,
    description: str,
    owner: str = "unassigned",
    scope_key: str = "team",
    affected: list[dict[str, Any]] | None = None,
    linked_changes: list[str] | None = None,
    evidence_version: str | None = None,
    observation: str | None = None,
) -> Path:
    rid = review_id_for(kind, title, scope_key)
    existing = find_review(root, rid)
    now = utc_now()
    affected = affected or []
    linked_changes = linked_changes or []

    if existing:
        meta, body = parse_frontmatter(existing)
        previous_evidence = meta.get("evidence_version")
        history = list(meta.get("history") or [])
        if meta.get("state") in {"resolved", "dismissed"} and evidence_version and evidence_version != previous_evidence:
            history.append({
                "at": now,
                "event": "reopened",
                "reason": "new-evidence-version",
                "from_evidence_version": previous_evidence,
                "to_evidence_version": evidence_version,
            })
            meta["state"] = "open"
            meta["resolution"] = None
        meta["description"] = description or meta.get("description", "")
        meta["owner"] = owner or meta.get("owner", "unassigned")
        meta["affected"] = _uniq_dicts([*(meta.get("affected") or []), *affected])
        meta["linked_changes"] = list(dict.fromkeys([*(meta.get("linked_changes") or []), *linked_changes]))
        if evidence_version:
            meta["evidence_version"] = evidence_version
        observations = list(meta.get("observations") or [])
        if observation:
            item = {"at": now, "text": observation, "evidence_version": evidence_version}
            if item not in observations:
                observations.append(item)
        meta["observations"] = observations
        meta["history"] = history
        meta["updated"] = now
        _write(existing, meta, body)
        return existing

    date = datetime.now()
    path = root / "changes/reviews" / f"{date.year:04d}" / f"{date.month:02d}" / f"{rid}.md"
    meta = {
        "review_id": rid,
        "kind": kind,
        "state": "open",
        "title": title,
        "description": description,
        "owner": owner,
        "scope_key": scope_key,
        "created": now,
        "updated": now,
        "affected": affected,
        "linked_changes": linked_changes,
        "evidence_version": evidence_version,
        "observations": ([{"at": now, "text": observation, "evidence_version": evidence_version}] if observation else []),
        "resolution": None,
        "history": [{"at": now, "event": "created"}],
    }
    body = f"""# {title}

## 问题

{description}

## 处理说明

待确认。
"""
    _write(path, meta, body)
    return path


def resolve_review(
    root: Path,
    review_id: str,
    *,
    action: str,
    note: str,
    evidence_version: str | None = None,
    dismiss: bool = False,
) -> Path:
    path = find_review(root, review_id)
    if not path:
        raise KeyError(f"review id not found: {review_id}")
    meta, body = parse_frontmatter(path)
    now = utc_now()
    meta["state"] = "dismissed" if dismiss else "resolved"
    meta["resolution"] = {
        "action": action,
        "note": note,
        "at": now,
        "evidence_version": evidence_version or meta.get("evidence_version"),
    }
    if evidence_version:
        meta["evidence_version"] = evidence_version
    meta.setdefault("history", []).append({"at": now, "event": meta["state"], "action": action})
    meta["updated"] = now
    _write(path, meta, body)
    return path


def list_reviews(root: Path, *, state: str | None = None) -> list[dict[str, Any]]:
    if state and state not in STATES:
        raise ValueError(f"invalid review state: {state}")
    rows: list[dict[str, Any]] = []
    base = root / "changes/reviews"
    if not base.exists():
        return rows
    for path in sorted(base.rglob("REV-*.md")):
        meta, _ = parse_frontmatter(path)
        if state and meta.get("state") != state:
            continue
        rows.append({
            "review_id": meta.get("review_id", path.stem),
            "kind": meta.get("kind"),
            "state": meta.get("state"),
            "title": meta.get("title", path.stem),
            "owner": meta.get("owner"),
            "path": str(path.relative_to(root)),
            "evidence_version": meta.get("evidence_version"),
        })
    return rows
