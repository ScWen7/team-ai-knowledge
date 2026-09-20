"""Text/Markdown intake with durable review-progress ledgers.

The artifact/ledger pattern is adapted from
giodra96/project-wiki@09f24a20 scripts/ingest_document.py and
scripts/review_progress.py (MIT). V0.3 intentionally supports only
UTF-8 text/Markdown; PDF/DOCX adapters remain future work.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .core import read_yaml, write_yaml, utc_now


SUPPORTED_SUFFIXES = {".txt", ".md", ".markdown"}
CHUNK_STATES = {"pending", "integrated", "skipped"}


def find_source_meta(root: Path, source_id: str) -> Path:
    for path in (root / "sources").rglob("source.yml"):
        data = read_yaml(path)
        if data.get("source_id") == source_id:
            return path
    raise KeyError(f"source id not found: {source_id}")


def _source_file(meta_path: Path, data: dict[str, Any]) -> Path:
    name = data.get("original_name")
    if not name:
        raise ValueError("source package has no original_name")
    path = meta_path.parent / str(name)
    if not path.is_file():
        raise ValueError(f"source original file missing: {path}")
    return path


def _blocks(text: str) -> list[str]:
    parts = re.split(r"(?=^#{1,6}\s)|\n\s*\n", text, flags=re.M)
    return [p.strip() for p in parts if p.strip()]


def _chunks(text: str, max_chars: int) -> list[str]:
    if max_chars < 500:
        raise ValueError("max_chars must be at least 500")
    chunks: list[str] = []
    current = ""
    for block in _blocks(text):
        if len(block) > max_chars:
            if current:
                chunks.append(current.strip())
                current = ""
            for start in range(0, len(block), max_chars):
                chunks.append(block[start:start + max_chars].strip())
            continue
        candidate = f"{current}\n\n{block}".strip() if current else block
        if current and len(candidate) > max_chars:
            chunks.append(current.strip())
            current = block
        else:
            current = candidate
    if current:
        chunks.append(current.strip())
    return chunks


def intake_source(root: Path, source_id: str, *, max_chars: int = 4000) -> Path:
    meta_path = find_source_meta(root, source_id)
    source = read_yaml(meta_path)
    path = _source_file(meta_path, source)
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValueError(f"V0.3 intake supports only: {sorted(SUPPORTED_SUFFIXES)}")
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    expected = source.get("content_sha256")
    if expected and digest != expected:
        raise ValueError("source content changed; run refresh-source before intake")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("source is not UTF-8 text") from exc
    parts = _chunks(text, max_chars)
    if not parts:
        raise ValueError("source has no extractable text")

    intake_id = f"INTAKE-{source_id}-{digest[:10].upper()}"
    root_dir = root / ".knowledge/records/intake" / intake_id
    manifest = root_dir / "manifest.json"
    if manifest.exists():
        return root_dir
    chunks_dir = root_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for i, content in enumerate(parts, 1):
        cid = f"{intake_id}-C{i:04d}"
        cpath = chunks_dir / f"{cid}.md"
        cpath.write_text(content + "\n", encoding="utf-8")
        rows.append({
            "id": cid,
            "sequence": i,
            "path": str(cpath.relative_to(root)),
            "char_count": len(content),
            "sha256": hashlib.sha256(content.encode()).hexdigest(),
        })
    root_dir.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({
        "version": 1,
        "intake_id": intake_id,
        "source_id": source_id,
        "source_sha256": digest,
        "created": utc_now(),
        "max_chars": max_chars,
        "chunks": rows,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_yaml(root_dir / "review-progress.yml", {
        "version": 1,
        "intake_id": intake_id,
        "source_id": source_id,
        "source_sha256": digest,
        "review_status": "pending",
        "chunks": [
            {"id": row["id"], "status": "pending", "note": None, "knowledge_ids": []}
            for row in rows
        ],
        "summary": {"total": len(rows), "pending": len(rows), "integrated": 0, "skipped": 0},
        "updated": utc_now(),
    })
    return root_dir


def intake_status(root: Path, intake_id: str) -> dict[str, Any]:
    path = root / ".knowledge/records/intake" / intake_id / "review-progress.yml"
    if not path.is_file():
        raise KeyError(f"intake id not found: {intake_id}")
    return read_yaml(path)


def apply_disposition(
    root: Path,
    intake_id: str,
    chunk_id: str,
    *,
    status: str,
    note: str | None = None,
    knowledge_ids: list[str] | None = None,
) -> dict[str, Any]:
    if status not in CHUNK_STATES:
        raise ValueError(f"invalid chunk status: {status}")
    if status == "skipped" and not (note and note.strip()):
        raise ValueError("skipped chunks require a note")
    path = root / ".knowledge/records/intake" / intake_id / "review-progress.yml"
    if not path.is_file():
        raise KeyError(f"intake id not found: {intake_id}")
    ledger = read_yaml(path)
    row = next((x for x in ledger.get("chunks", []) if x.get("id") == chunk_id), None)
    if row is None:
        raise KeyError(f"chunk id not found: {chunk_id}")
    row["status"] = status
    row["note"] = note
    row["knowledge_ids"] = list(dict.fromkeys(knowledge_ids or []))
    counts = {name: 0 for name in CHUNK_STATES}
    for item in ledger.get("chunks", []):
        counts[item.get("status", "pending")] = counts.get(item.get("status", "pending"), 0) + 1
    ledger["summary"] = {"total": len(ledger.get("chunks", [])), **counts}
    ledger["review_status"] = "complete" if counts.get("pending", 0) == 0 else "in-progress"
    ledger["updated"] = utc_now()
    write_yaml(path, ledger)
    return ledger


def audit_intake(root: Path, intake_id: str) -> dict[str, Any]:
    ledger = intake_status(root, intake_id)
    pending = [x["id"] for x in ledger.get("chunks", []) if x.get("status") == "pending"]
    bad_skips = [
        x["id"] for x in ledger.get("chunks", [])
        if x.get("status") == "skipped" and not (x.get("note") or "").strip()
    ]
    return {
        "intake_id": intake_id,
        "complete": not pending and not bad_skips,
        "pending": pending,
        "invalid_skips": bad_skips,
        "summary": ledger.get("summary", {}),
    }
