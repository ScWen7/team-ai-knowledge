"""Evidence-layer helpers for parsed chunks, corrections and knowledge bindings.

V0.4 keeps parser output immutable. Human corrections are stored as
separate records and resolved at read time, so reparsing never silently
erases a verified correction.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .core import read_yaml, write_yaml, utc_now


RELATIONS = {"supports", "limits", "contradicts", "relevant"}


def _intake_roots(root: Path):
    base = root / ".knowledge/records/intake"
    if not base.exists():
        return []
    return [p for p in base.iterdir() if p.is_dir()]


def find_evidence(root: Path, evidence_id: str) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    for intake_root in _intake_roots(root):
        manifest = intake_root / "manifest.json"
        if not manifest.is_file():
            continue
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        for row in payload.get("chunks", []):
            if row.get("evidence_id") == evidence_id:
                return intake_root, payload, row
    raise KeyError(f"evidence id not found: {evidence_id}")


def _correction_dir(root: Path) -> Path:
    return root / ".knowledge/records/evidence-corrections"


def list_corrections(root: Path, evidence_id: str) -> list[dict[str, Any]]:
    base = _correction_dir(root)
    if not base.exists():
        return []
    rows = []
    for path in sorted(base.glob("CORR-*.yml")):
        data = read_yaml(path)
        if data.get("evidence_id") == evidence_id:
            rows.append(data)
    rows.sort(key=lambda x: x.get("created", ""))
    return rows


def read_evidence(root: Path, evidence_id: str, *, corrected: bool = True) -> dict[str, Any]:
    intake_root, manifest, row = find_evidence(root, evidence_id)
    raw_path = root / row["path"]
    raw_text = raw_path.read_text(encoding="utf-8").rstrip("\n")
    corrections = list_corrections(root, evidence_id)
    current_text = raw_text
    current_sha = hashlib.sha256(raw_text.encode()).hexdigest()
    if corrected and corrections:
        latest = corrections[-1]
        text_path = root / latest["text_path"]
        current_text = text_path.read_text(encoding="utf-8").rstrip("\n")
        current_sha = latest["new_sha256"]
    return {
        "evidence_id": evidence_id,
        "source_id": row["source_id"],
        "source_revision": row["source_revision"],
        "processing_id": row["processing_id"],
        "locator": row["locator"],
        "raw_sha256": row["sha256"],
        "raw_text": raw_text,
        "current_sha256": current_sha,
        "current_text": current_text,
        "correction_ids": [x["correction_id"] for x in corrections],
        "index_state": row.get("index_state", "not-indexed"),
        "intake_id": manifest["intake_id"],
    }


def correct_evidence(
    root: Path,
    evidence_id: str,
    *,
    new_text: str,
    reason: str,
    verified_by: str,
) -> Path:
    if not reason.strip():
        raise ValueError("correction reason is required")
    if not verified_by.strip():
        raise ValueError("verified_by is required")
    current = read_evidence(root, evidence_id, corrected=True)
    new_text = new_text.rstrip("\n")
    new_sha = hashlib.sha256(new_text.encode()).hexdigest()
    if new_sha == current["current_sha256"]:
        corrections = list_corrections(root, evidence_id)
        if corrections:
            path = _correction_dir(root) / f"{corrections[-1]['correction_id']}.yml"
            return path
        raise ValueError("new correction text is identical to raw evidence")

    key = f"{evidence_id}|{current['current_sha256']}|{new_sha}|{reason}|{verified_by}"
    correction_id = "CORR-" + hashlib.sha256(key.encode()).hexdigest()[:12].upper()
    base = _correction_dir(root)
    base.mkdir(parents=True, exist_ok=True)
    text_path = base / f"{correction_id}.md"
    meta_path = base / f"{correction_id}.yml"
    if not text_path.exists():
        text_path.write_text(new_text + "\n", encoding="utf-8")
    if not meta_path.exists():
        write_yaml(meta_path, {
            "correction_id": correction_id,
            "evidence_id": evidence_id,
            "created": utc_now(),
            "verified_by": verified_by,
            "reason": reason,
            "previous_sha256": current["current_sha256"],
            "new_sha256": new_sha,
            "text_path": str(text_path.relative_to(root)),
            "source_id": current["source_id"],
            "source_revision": current["source_revision"],
            "processing_id": current["processing_id"],
        })
    return meta_path


def _binding_dir(root: Path) -> Path:
    return root / ".knowledge/records/evidence-bindings"


def bind_evidence(
    root: Path,
    evidence_id: str,
    *,
    target_kind: str,
    target_id: str,
    relation: str,
    note: str = "",
) -> Path:
    if relation not in RELATIONS:
        raise ValueError(f"invalid evidence relation: {relation}")
    if target_kind not in {"knowledge", "change", "review", "candidate"}:
        raise ValueError(f"invalid target kind: {target_kind}")
    current = read_evidence(root, evidence_id, corrected=True)
    key = f"{evidence_id}|{target_kind}|{target_id}|{relation}"
    binding_id = "BIND-" + hashlib.sha256(key.encode()).hexdigest()[:12].upper()
    path = _binding_dir(root) / f"{binding_id}.yml"
    if not path.exists():
        write_yaml(path, {
            "binding_id": binding_id,
            "evidence_id": evidence_id,
            "target_kind": target_kind,
            "target_id": target_id,
            "relation": relation,
            "note": note,
            "created": utc_now(),
            "source_id": current["source_id"],
            "source_revision": current["source_revision"],
            "evidence_sha256": current["current_sha256"],
        })
    return path


def list_bindings(
    root: Path,
    *,
    evidence_id: str | None = None,
    target_id: str | None = None,
) -> list[dict[str, Any]]:
    base = _binding_dir(root)
    if not base.exists():
        return []
    rows = []
    for path in sorted(base.glob("BIND-*.yml")):
        data = read_yaml(path)
        if evidence_id and data.get("evidence_id") != evidence_id:
            continue
        if target_id and data.get("target_id") != target_id:
            continue
        rows.append(data)
    return rows
