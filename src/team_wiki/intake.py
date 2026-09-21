"""Structured evidence intake for UTF-8 text and Markdown.

The durable review-progress pattern remains adapted from project-wiki.
V0.4 adds a WeKnora-inspired evidence contract: source revision,
processing profile/version, structured locators, immutable parser output,
and explicit index state. It does not copy WeKnora implementation code.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .core import read_yaml, write_yaml, utc_now


SUPPORTED_SUFFIXES = {".txt", ".md", ".markdown"}
CHUNK_STATES = {"pending", "integrated", "skipped"}
PARSER_NAME = "team-wiki-text"
PARSER_VERSION = "0.4.0"


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


@dataclass(frozen=True)
class Block:
    text: str
    start: int
    end: int
    heading_path: tuple[str, ...]


@dataclass(frozen=True)
class EvidenceChunk:
    text: str
    start: int
    end: int
    heading_path: tuple[str, ...]


def _blocks(text: str) -> list[Block]:
    lines = text.splitlines(keepends=True)
    offset = 0
    heading_stack: list[str] = []
    current_lines: list[str] = []
    current_start: int | None = None
    current_heading: tuple[str, ...] = ()

    out: list[Block] = []

    def flush(end_offset: int) -> None:
        nonlocal current_lines, current_start, current_heading
        if current_start is None:
            return
        content = "".join(current_lines).strip()
        if content:
            out.append(Block(content, current_start, end_offset, current_heading))
        current_lines = []
        current_start = None

    for line in lines:
        stripped = line.strip()
        heading = re.match(r"^(#{1,6})\s+(.+?)\s*$", stripped)
        if heading:
            flush(offset)
            level = len(heading.group(1))
            title = heading.group(2).strip()
            heading_stack[:] = heading_stack[: level - 1]
            heading_stack.append(title)
            current_heading = tuple(heading_stack)
            current_start = offset
            current_lines = [line]
        elif stripped == "":
            flush(offset)
            current_heading = tuple(heading_stack)
        else:
            if current_start is None:
                current_start = offset
                current_heading = tuple(heading_stack)
            current_lines.append(line)
        offset += len(line)
    flush(len(text))
    return out


def _chunks(text: str, max_chars: int) -> list[EvidenceChunk]:
    if max_chars < 500:
        raise ValueError("max_chars must be at least 500")
    chunks: list[EvidenceChunk] = []
    current_text = ""
    current_start: int | None = None
    current_end = 0
    current_heading: tuple[str, ...] = ()

    def flush() -> None:
        nonlocal current_text, current_start, current_end, current_heading
        if current_start is None or not current_text.strip():
            return
        chunks.append(
            EvidenceChunk(
                current_text.strip(),
                current_start,
                current_end,
                current_heading,
            )
        )
        current_text = ""
        current_start = None

    for block in _blocks(text):
        if len(block.text) > max_chars:
            flush()
            for start in range(0, len(block.text), max_chars):
                part = block.text[start : start + max_chars].strip()
                if not part:
                    continue
                relative = block.text.find(part, start)
                char_start = block.start + max(relative, start)
                chunks.append(
                    EvidenceChunk(
                        part,
                        char_start,
                        min(block.end, char_start + len(part)),
                        block.heading_path,
                    )
                )
            continue

        if current_start is None:
            current_start = block.start
            current_end = block.end
            current_heading = block.heading_path
            current_text = block.text
            continue

        same_section = current_heading == block.heading_path
        candidate = f"{current_text}\n\n{block.text}".strip()
        if same_section and len(candidate) <= max_chars:
            current_text = candidate
            current_end = block.end
        else:
            flush()
            current_start = block.start
            current_end = block.end
            current_heading = block.heading_path
            current_text = block.text

    flush()
    return chunks


def _logical_path(source: dict[str, Any]) -> str | None:
    origin = source.get("origin") or {}
    if isinstance(origin, dict):
        value = origin.get("logical_path")
        return str(value) if value else None
    return None


def intake_source(root: Path, source_id: str, *, max_chars: int = 4000) -> Path:
    meta_path = find_source_meta(root, source_id)
    source = read_yaml(meta_path)
    path = _source_file(meta_path, source)
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValueError(f"V0.4 intake supports only: {sorted(SUPPORTED_SUFFIXES)}")
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
    processing_id = f"PROC-{source_id}-{digest[:10].upper()}-{PARSER_VERSION.replace('.', '')}"
    root_dir = root / ".knowledge/records/intake" / intake_id
    manifest = root_dir / "manifest.json"
    if manifest.exists():
        return root_dir

    chunks_dir = root_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    logical_path = _logical_path(source)

    for i, chunk in enumerate(parts, 1):
        cid = f"{intake_id}-C{i:04d}"
        evidence_id = f"EVD-{source_id}-{digest[:8].upper()}-{i:04d}"
        cpath = chunks_dir / f"{cid}.md"
        cpath.write_text(chunk.text + "\n", encoding="utf-8")
        rows.append(
            {
                "id": cid,
                "evidence_id": evidence_id,
                "sequence": i,
                "path": str(cpath.relative_to(root)),
                "char_count": len(chunk.text),
                "sha256": hashlib.sha256(chunk.text.encode()).hexdigest(),
                "source_id": source_id,
                "source_revision": digest,
                "processing_id": processing_id,
                "index_state": "not-indexed",
                "locator": {
                    "logical_path": logical_path,
                    "heading_path": list(chunk.heading_path),
                    "char_start": chunk.start,
                    "char_end": chunk.end,
                    "sequence": i,
                },
            }
        )

    root_dir.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps(
            {
                "version": 2,
                "intake_id": intake_id,
                "source_id": source_id,
                "source_revision": digest,
                "processing_id": processing_id,
                "created": utc_now(),
                "parser": {"name": PARSER_NAME, "version": PARSER_VERSION},
                "effective_config": {
                    "strategy": "heading-aware",
                    "max_chars": max_chars,
                    "preserve_heading_path": True,
                },
                "chunks": rows,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    write_yaml(
        root_dir / "processing.yml",
        {
            "version": 1,
            "processing_id": processing_id,
            "source_id": source_id,
            "source_revision": digest,
            "state": "completed",
            "parser": {"name": PARSER_NAME, "version": PARSER_VERSION},
            "effective_config": {
                "strategy": "heading-aware",
                "max_chars": max_chars,
                "preserve_heading_path": True,
            },
            "coverage": {
                "input_chars": len(text),
                "chunk_count": len(rows),
                "warnings": [],
            },
            "completed": utc_now(),
        },
    )

    write_yaml(
        root_dir / "review-progress.yml",
        {
            "version": 2,
            "intake_id": intake_id,
            "source_id": source_id,
            "source_revision": digest,
            "processing_id": processing_id,
            "review_status": "pending",
            "chunks": [
                {
                    "id": row["id"],
                    "evidence_id": row["evidence_id"],
                    "status": "pending",
                    "note": None,
                    "knowledge_ids": [],
                }
                for row in rows
            ],
            "summary": {
                "total": len(rows),
                "pending": len(rows),
                "integrated": 0,
                "skipped": 0,
            },
            "updated": utc_now(),
        },
    )

    source["status"] = "parsed"
    source["latest_intake_id"] = intake_id
    source["latest_processing_id"] = processing_id
    source["latest_processed_revision"] = digest
    source["updated_at"] = utc_now()
    write_yaml(meta_path, source)
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
        x["id"]
        for x in ledger.get("chunks", [])
        if x.get("status") == "skipped" and not (x.get("note") or "").strip()
    ]
    processing_path = root / ".knowledge/records/intake" / intake_id / "processing.yml"
    processing = read_yaml(processing_path) if processing_path.is_file() else {}
    return {
        "intake_id": intake_id,
        "complete": not pending and not bad_skips and processing.get("state") == "completed",
        "pending": pending,
        "invalid_skips": bad_skips,
        "summary": ledger.get("summary", {}),
        "processing": processing,
    }


def source_pipeline_status(root: Path, source_id: str) -> dict[str, Any]:
    meta_path = find_source_meta(root, source_id)
    source = read_yaml(meta_path)
    result: dict[str, Any] = {
        "source_id": source_id,
        "acquisition": {
            "state": "acquired",
            "content_sha256": source.get("content_sha256"),
            "origin": source.get("origin"),
        },
        "processing": {"state": "not-started"},
        "evidence": {"state": "not-ready", "count": 0},
        "indexing": {"state": "not-configured", "counts": {}},
        "knowledge_change": {
            "state": "linked" if source.get("linked_changes") else "none",
            "change_ids": source.get("linked_changes") or [],
        },
    }
    intake_id = source.get("latest_intake_id")
    if not intake_id:
        return result
    intake_root = root / ".knowledge/records/intake" / str(intake_id)
    processing_path = intake_root / "processing.yml"
    manifest_path = intake_root / "manifest.json"
    ledger_path = intake_root / "review-progress.yml"
    if processing_path.is_file():
        processing = read_yaml(processing_path)
        result["processing"] = {
            "state": processing.get("state"),
            "processing_id": processing.get("processing_id"),
            "parser": processing.get("parser"),
            "effective_config": processing.get("effective_config"),
            "coverage": processing.get("coverage"),
        }
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        chunks = manifest.get("chunks", [])
        result["evidence"] = {
            "state": "ready" if chunks else "not-ready",
            "count": len(chunks),
            "source_revision": manifest.get("source_revision"),
        }
        counts: dict[str, int] = {}
        for row in chunks:
            state = row.get("index_state", "unknown")
            counts[state] = counts.get(state, 0) + 1
        result["indexing"] = {
            "state": "ready" if counts and all(k == "indexed" for k in counts) else "not-indexed",
            "counts": counts,
        }
    if ledger_path.is_file():
        ledger = read_yaml(ledger_path)
        result["evidence"]["review_status"] = ledger.get("review_status")
        result["evidence"]["review_summary"] = ledger.get("summary")
    return result
