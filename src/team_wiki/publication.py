"""Publication and downstream adoption records.

A publication is not inferred from a frontmatter status. It is recorded only
when the target knowledge bytes are present in a real Git commit and all Reviews
linked to the CHG are resolved/dismissed.
"""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any

from .core import _rewrite_change_meta, knowledge_ref, parse_frontmatter, read_yaml, utc_now, write_yaml
from .review import find_review


ADOPTION_REQUIREMENTS = {"notice", "review-required", "must-address"}
RESOLVED_REVIEW_STATES = {"resolved", "dismissed"}


def _records(root: Path, kind: str) -> Path:
    return root / ".knowledge/records" / kind


def _change_path(root: Path, change_id: str) -> Path:
    path = next(iter((root / "changes").rglob(f"{change_id}.md")), None)
    if path is None:
        raise KeyError(f"change id not found: {change_id}")
    return path


def _git(root: Path, *args: str, text: bool = True) -> str | bytes:
    cp = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=text,
        check=False,
    )
    if cp.returncode:
        stderr = cp.stderr.strip() if text else cp.stderr.decode(errors="replace").strip()
        raise ValueError(stderr or f"git command failed: {' '.join(args)}")
    return cp.stdout


def _resolve_commit(root: Path, ref: str) -> str:
    return str(_git(root, "rev-parse", f"{ref}^{{commit}}")).strip()


def _content_at(root: Path, commit: str, path: str) -> bytes:
    raw = _git(root, "show", f"{commit}:{path}", text=False)
    assert isinstance(raw, bytes)
    return raw


def _review_blockers(root: Path, review_ids: list[str]) -> list[dict[str, str]]:
    blockers: list[dict[str, str]] = []
    for rid in review_ids:
        path = find_review(root, rid)
        if path is None:
            blockers.append({"review_id": rid, "state": "missing"})
            continue
        meta, _ = parse_frontmatter(path)
        state = str(meta.get("state", "unknown"))
        if state not in RESOLVED_REVIEW_STATES:
            blockers.append({"review_id": rid, "state": state})
    return blockers


def publication_path(root: Path, publication_id: str) -> Path:
    path = _records(root, "publications") / f"{publication_id}.yml"
    if not path.is_file():
        raise KeyError(f"publication id not found: {publication_id}")
    return path


def list_publications(root: Path, *, knowledge_id: str | None = None) -> list[dict[str, Any]]:
    base = _records(root, "publications")
    if not base.exists():
        return []
    rows = []
    for path in sorted(base.glob("PUB-*.yml")):
        data = read_yaml(path)
        if knowledge_id and data.get("knowledge_id") != knowledge_id:
            continue
        rows.append(data)
    rows.sort(key=lambda x: (x.get("published_at", ""), x.get("publication_id", "")))
    return rows


def latest_publication_for(root: Path, knowledge_id: str) -> dict[str, Any] | None:
    rows = list_publications(root, knowledge_id=knowledge_id)
    return rows[-1] if rows else None


def record_publication(
    root: Path,
    change_id: str,
    knowledge_id: str,
    *,
    published_ref: str,
    adoption_requirement: str = "notice",
    effective_at: str | None = None,
) -> Path:
    if adoption_requirement not in ADOPTION_REQUIREMENTS:
        raise ValueError(f"invalid adoption requirement: {adoption_requirement}")

    change_path = _change_path(root, change_id)
    change_meta, _ = parse_frontmatter(change_path)
    if change_meta.get("stage") not in {"proposed", "ready", "published"}:
        raise ValueError(
            f"change {change_id} is not publication-ready: stage={change_meta.get('stage')}"
        )

    blockers = _review_blockers(root, list(change_meta.get("review_ids") or []))
    if blockers:
        detail = ", ".join(f"{x['review_id']}={x['state']}" for x in blockers)
        raise ValueError(f"publication blocked by unresolved Reviews: {detail}")

    path, _meta, current_sha = knowledge_ref(root, knowledge_id)
    rel = path.relative_to(root).as_posix()
    commit = _resolve_commit(root, published_ref)
    committed_bytes = _content_at(root, commit, rel)
    committed_sha = hashlib.sha256(committed_bytes).hexdigest()
    if committed_sha != current_sha:
        raise ValueError(
            "current knowledge content is not identical to the requested published Git commit"
        )

    key = f"{knowledge_id}|{commit}|{current_sha}|{change_id}"
    publication_id = "PUB-" + hashlib.sha256(key.encode()).hexdigest()[:12].upper()
    out = _records(root, "publications") / f"{publication_id}.yml"
    if not out.exists():
        write_yaml(
            out,
            {
                "publication_id": publication_id,
                "knowledge_id": knowledge_id,
                "change_id": change_id,
                "published_ref": commit,
                "path": rel,
                "content_sha256": current_sha,
                "adoption_requirement": adoption_requirement,
                "published_at": utc_now(),
                "effective_at": effective_at,
            },
        )

    _rewrite_change_meta(
        change_path,
        {
            "stage": "published",
            "publication": {
                "publication_id": publication_id,
                "knowledge_id": knowledge_id,
                "published_ref": commit,
                "content_sha256": current_sha,
                "adoption_requirement": adoption_requirement,
                "published_at": utc_now(),
                "effective_at": effective_at,
            },
        },
    )
    return out


def record_work_adoptions(root: Path, work: dict[str, Any]) -> list[Path]:
    consumer_id = str(work.get("consumer_id") or "unknown")
    work_id = str(work["work_id"])
    out: list[Path] = []
    for item in work.get("adopted", []) or []:
        publication_id = item.get("publication_id")
        if not publication_id:
            continue
        knowledge_id = str(item["knowledge_id"])
        key = f"{work_id}|{consumer_id}|{knowledge_id}|{publication_id}"
        adoption_id = "ADOPT-" + hashlib.sha256(key.encode()).hexdigest()[:12].upper()
        path = _records(root, "adoptions") / f"{adoption_id}.yml"
        if not path.exists():
            write_yaml(
                path,
                {
                    "adoption_id": adoption_id,
                    "work_id": work_id,
                    "consumer_id": consumer_id,
                    "knowledge_id": knowledge_id,
                    "publication_id": publication_id,
                    "published_ref": item.get("published_ref"),
                    "knowledge_content_sha256": item.get("content_sha256"),
                    "used_for": item.get("used_for"),
                    "outcome": item.get("outcome"),
                    "evidence_ids": item.get("evidence_ids") or [],
                    "recorded_at": utc_now(),
                },
            )
        out.append(path)
    return out


def adoption_status(root: Path, knowledge_id: str) -> dict[str, Any]:
    publication = latest_publication_for(root, knowledge_id)
    if publication is None:
        return {
            "knowledge_id": knowledge_id,
            "publication": None,
            "adoptions": [],
            "consumer_count": 0,
        }

    base = _records(root, "adoptions")
    rows: list[dict[str, Any]] = []
    if base.exists():
        for path in sorted(base.glob("ADOPT-*.yml")):
            data = read_yaml(path)
            if (
                data.get("knowledge_id") == knowledge_id
                and data.get("publication_id") == publication["publication_id"]
            ):
                rows.append(data)

    consumers = sorted({str(x.get("consumer_id")) for x in rows})
    return {
        "knowledge_id": knowledge_id,
        "publication": publication,
        "adoptions": rows,
        "consumer_count": len(consumers),
        "consumers": consumers,
    }
