"""Multi-source candidate aggregation without automatic semantic inference.

A batch is a work artifact. The current Agent/domain owner supplies the merged
statement. Deterministic code verifies candidate compatibility, carries forward
all evidence bindings, records conflicts in evidence relations, and creates one
merged Candidate that can use the existing Patch Plan workflow.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .candidate import candidate_context, candidate_path, create_candidate
from .core import read_yaml, utc_now, write_yaml
from .evidence import bind_evidence


def _records(root: Path) -> Path:
    return root / ".knowledge/records/candidate-batches"


def batch_path(root: Path, batch_id: str) -> Path:
    path = _records(root) / f"{batch_id}.yml"
    if not path.is_file():
        raise KeyError(f"candidate batch not found: {batch_id}")
    return path


def create_candidate_batch(
    root: Path,
    candidate_ids: list[str],
    *,
    title: str,
    merged_statement: str,
    owner: str = "unassigned",
    scope: str = "team",
) -> Path:
    ids = list(dict.fromkeys(candidate_ids))
    if len(ids) < 2:
        raise ValueError("candidate batch requires at least two candidates")
    if not merged_statement.strip():
        raise ValueError("merged_statement is required")

    contexts = [candidate_context(root, cid) for cid in ids]
    records = [ctx["candidate"] for ctx in contexts]
    proposed_ids = {str(x["proposed_id"]) for x in records}
    knowledge_types = {str(x["knowledge_type"]) for x in records}
    scopes = {str(x.get("scope", "team")) for x in records}
    if len(proposed_ids) != 1:
        raise ValueError("all candidates in a batch must share proposed_id")
    if len(knowledge_types) != 1:
        raise ValueError("all candidates in a batch must share knowledge_type")
    if len(scopes) != 1 or (scope and scope not in scopes):
        raise ValueError("all candidates in a batch must share scope")

    proposed_id = next(iter(proposed_ids))
    knowledge_type = next(iter(knowledge_types))

    merged_candidate = create_candidate(
        root,
        proposed_id=proposed_id,
        title=title,
        knowledge_type=knowledge_type,
        statement=merged_statement,
        owner=owner,
        scope=scope,
    )
    merged = read_yaml(merged_candidate)
    merged_id = merged["candidate_id"]

    evidence_map: dict[str, dict[str, Any]] = {}
    for ctx in contexts:
        for item in ctx["evidence"]:
            eid = item["evidence_id"]
            row = evidence_map.setdefault(
                eid,
                {
                    "evidence_id": eid,
                    "source_id": item["source_id"],
                    "source_revision": item["source_revision"],
                    "evidence_sha256": item["evidence_sha256"],
                    "relations": [],
                    "candidate_ids": [],
                },
            )
            relation = str(item["relation"])
            if relation not in row["relations"]:
                row["relations"].append(relation)
            cid = str(ctx["candidate"]["candidate_id"])
            if cid not in row["candidate_ids"]:
                row["candidate_ids"].append(cid)
            bind_evidence(
                root,
                eid,
                target_kind="candidate",
                target_id=merged_id,
                relation=relation,
                note=f"carried from batch candidate {cid}",
            )

    if not evidence_map:
        raise ValueError("candidate batch must contain grounded evidence")

    evidence_conflicts = [
        {
            "evidence_id": eid,
            "relations": sorted(row["relations"]),
            "candidate_ids": sorted(row["candidate_ids"]),
        }
        for eid, row in evidence_map.items()
        if len(set(row["relations"])) > 1
    ]

    key = (
        "|".join(sorted(ids))
        + f"|{merged_id}|{merged_statement}|"
        + "|".join(sorted(evidence_map))
    )
    batch_id = "BATCH-" + hashlib.sha256(key.encode()).hexdigest()[:12].upper()
    path = _records(root) / f"{batch_id}.yml"
    if not path.exists():
        write_yaml(
            path,
            {
                "batch_id": batch_id,
                "candidate_ids": ids,
                "merged_candidate_id": merged_id,
                "proposed_id": proposed_id,
                "knowledge_type": knowledge_type,
                "scope": scope,
                "title": title,
                "merged_statement": merged_statement,
                "owner": owner,
                "created": utc_now(),
                "evidence": sorted(evidence_map.values(), key=lambda x: x["evidence_id"]),
                "evidence_conflicts": evidence_conflicts,
                "status": "merged",
            },
        )

    for cid in ids:
        cpath = candidate_path(root, cid)
        record = read_yaml(cpath)
        record["batch_ids"] = list(
            dict.fromkeys([*(record.get("batch_ids") or []), batch_id])
        )
        write_yaml(cpath, record)

    merged["batch_ids"] = list(
        dict.fromkeys([*(merged.get("batch_ids") or []), batch_id])
    )
    merged["source_candidate_ids"] = ids
    write_yaml(merged_candidate, merged)
    return path


def batch_context(root: Path, batch_id: str) -> dict[str, Any]:
    batch = read_yaml(batch_path(root, batch_id))
    candidates = [candidate_context(root, cid) for cid in batch["candidate_ids"]]
    merged = candidate_context(root, batch["merged_candidate_id"])
    return {
        "batch": batch,
        "candidates": candidates,
        "merged_candidate": merged,
        "requires_semantic_review": bool(batch.get("evidence_conflicts")),
    }
