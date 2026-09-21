"""Project-side knowledge consumption governance.

V0.7 keeps team knowledge authoritative while letting each project pin exact
Publication versions. Project paths never store the local path to the team
knowledge checkout; callers provide that authorized checkout when comparing,
reading or reporting adoption.
"""
from __future__ import annotations

import hashlib
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .core import ALLOWED_OUTCOMES, git_info, read_yaml, short_hash, utc_now, write_yaml
from .publication import (
    latest_publication_for,
    list_publications,
    record_work_adoptions,
)


DECISIONS = {"accept", "defer"}
PHASES = {"start", "release"}


def _config_path(root: Path) -> Path:
    return root / ".knowledge/config.yml"


def _lock_path(root: Path) -> Path:
    return root / ".knowledge/knowledge.lock.yml"


def _runs_dir(root: Path) -> Path:
    return root / ".knowledge/runs"


def _decision_dir(root: Path) -> Path:
    return root / ".knowledge/records/update-decisions"


def _work_path(root: Path, work_id: str) -> Path:
    path = _runs_dir(root) / f"{work_id}.yml"
    if not path.is_file():
        raise KeyError(f"project work not found: {work_id}")
    return path


def _sha_file(path: Path) -> str:
    if not path.is_file():
        return hashlib.sha256(b"").hexdigest()
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_lock_sha(root: Path) -> str:
    return _sha_file(_lock_path(root))


def _team_repository_id(team_root: Path) -> str:
    config = read_yaml(team_root / ".knowledge/config.yml")
    rid = config.get("repository_id")
    if not rid:
        raise ValueError("team knowledge repository_id is missing")
    return str(rid)


def _project_config(root: Path) -> dict[str, Any]:
    path = _config_path(root)
    if not path.is_file():
        raise ValueError("project is not initialized for team-wiki")
    config = read_yaml(path)
    if config.get("profile") != "project":
        raise ValueError("project .knowledge/config.yml profile must be project")
    if not config.get("repository_id"):
        raise ValueError("project repository_id is required")
    return config


def _source_config(root: Path) -> dict[str, Any]:
    config = _project_config(root)
    sources = config.get("knowledge_sources") or []
    if len(sources) != 1:
        raise ValueError("V0.7 project profile requires exactly one team knowledge source")
    source = sources[0]
    if not source.get("repository_id"):
        raise ValueError("knowledge source repository_id is required")
    ids = source.get("knowledge_ids") or []
    if not ids:
        raise ValueError("knowledge source must explicitly list knowledge_ids")
    return source


def init_project(
    root: Path,
    *,
    project_id: str,
    team_repository_id: str,
    knowledge_ids: list[str],
) -> None:
    ids = list(dict.fromkeys(str(x).strip() for x in knowledge_ids if str(x).strip()))
    if not ids:
        raise ValueError("at least one knowledge_id is required")

    (root / ".knowledge/records/update-decisions").mkdir(parents=True, exist_ok=True)
    (root / ".knowledge/runs").mkdir(parents=True, exist_ok=True)
    (root / ".knowledge/cache").mkdir(parents=True, exist_ok=True)

    config_path = _config_path(root)
    if config_path.exists():
        existing = read_yaml(config_path)
        if existing.get("profile") != "project":
            raise ValueError("existing .knowledge/config.yml is not a project profile")
        if existing.get("repository_id") != project_id:
            raise ValueError("existing project repository_id differs from requested project_id")
    else:
        write_yaml(
            config_path,
            {
                "version": 1,
                "repository_id": project_id,
                "profile": "project",
                "language": "zh-CN",
                "knowledge_sources": [
                    {
                        "repository_id": team_repository_id,
                        "knowledge_ids": ids,
                    }
                ],
            },
        )

    lock_path = _lock_path(root)
    if not lock_path.exists():
        write_yaml(
            lock_path,
            {
                "version": 1,
                "project_id": project_id,
                "source_repository_id": team_repository_id,
                "updated_at": utc_now(),
                "entries": {},
            },
        )

    local = root / ".knowledge/local.yml"
    if not local.exists():
        local.write_text(
            "# 本机路径映射；不要提交\nrepositories: {}\n",
            encoding="utf-8",
        )

    gitignore = root / ".gitignore"
    existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    needed = [".knowledge/local.yml", ".knowledge/runs/", ".knowledge/cache/"]
    missing = [x for x in needed if x not in existing.splitlines()]
    if missing:
        text = existing
        if text and not text.endswith("\n"):
            text += "\n"
        text += "\n".join(missing) + "\n"
        gitignore.write_text(text, encoding="utf-8")


def _verify_team_source(project_root: Path, team_root: Path) -> dict[str, Any]:
    source = _source_config(project_root)
    actual = _team_repository_id(team_root)
    expected = str(source["repository_id"])
    if actual != expected:
        raise ValueError(
            f"team knowledge repository mismatch: expected {expected}, got {actual}"
        )
    return source


def _publication_entry(publication: dict[str, Any]) -> dict[str, Any]:
    return {
        "publication_id": publication["publication_id"],
        "published_ref": publication["published_ref"],
        "content_sha256": publication["content_sha256"],
        "path": publication["path"],
        "adoption_requirement": publication["adoption_requirement"],
        "published_at": publication.get("published_at"),
        "effective_at": publication.get("effective_at"),
        "change_id": publication.get("change_id"),
        "locked_at": utc_now(),
    }


def _latest_effective_publication(
    team_root: Path,
    knowledge_id: str,
) -> dict[str, Any] | None:
    rows = list_publications(team_root, knowledge_id=knowledge_id)
    effective = [row for row in rows if _effective(row)]
    return effective[-1] if effective else None


def lock_latest(
    project_root: Path,
    team_root: Path,
    *,
    knowledge_ids: list[str] | None = None,
) -> Path:
    source = _verify_team_source(project_root, team_root)
    tracked = list(source.get("knowledge_ids") or [])
    ids = list(dict.fromkeys(knowledge_ids or tracked))
    unknown = [kid for kid in ids if kid not in tracked]
    if unknown:
        raise ValueError(f"knowledge ids are not declared by project: {unknown}")

    lock_path = _lock_path(project_root)
    lock = read_yaml(lock_path)
    entries = dict(lock.get("entries") or {})

    missing: list[str] = []
    for kid in ids:
        publication = _latest_effective_publication(team_root, kid)
        if publication is None:
            missing.append(kid)
            continue
        entries[kid] = _publication_entry(publication)

    if missing:
        raise ValueError(f"no Publication exists for: {missing}")

    lock["entries"] = entries
    lock["updated_at"] = utc_now()
    write_yaml(lock_path, lock)
    return lock_path


def _effective(publication: dict[str, Any]) -> bool:
    value = publication.get("effective_at")
    if not value:
        return True
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) >= parsed.astimezone(timezone.utc)
    except Exception:
        # Invalid effective_at is governance-significant: treat it as effective
        # rather than silently weakening an update.
        return True


def _decision_id(
    project_id: str,
    knowledge_id: str,
    from_publication_id: str | None,
    to_publication_id: str,
) -> str:
    key = (
        f"{project_id}|{knowledge_id}|{from_publication_id}|"
        f"{to_publication_id}"
    )
    return "UPD-" + hashlib.sha256(key.encode()).hexdigest()[:12].upper()


def _decision_path(root: Path, decision_id: str) -> Path:
    return _decision_dir(root) / f"{decision_id}.yml"


def _decision_for(
    root: Path,
    knowledge_id: str,
    from_publication_id: str | None,
    to_publication_id: str,
) -> dict[str, Any] | None:
    project_id = str(_project_config(root)["repository_id"])
    did = _decision_id(
        project_id, knowledge_id, from_publication_id, to_publication_id
    )
    path = _decision_path(root, did)
    return read_yaml(path) if path.is_file() else None


def project_status(project_root: Path, team_root: Path) -> dict[str, Any]:
    source = _verify_team_source(project_root, team_root)
    config = _project_config(project_root)
    lock = read_yaml(_lock_path(project_root))
    entries = dict(lock.get("entries") or {})
    rows: list[dict[str, Any]] = []

    for kid in source.get("knowledge_ids") or []:
        latest = latest_publication_for(team_root, kid)
        locked = entries.get(kid)

        if latest is None:
            rows.append(
                {
                    "knowledge_id": kid,
                    "state": "no-publication",
                    "locked": locked,
                    "latest": None,
                    "effective": True,
                    "decision": None,
                }
            )
            continue

        is_effective = _effective(latest)
        if locked is None:
            state = "unlocked" if is_effective else "scheduled-unlocked"
            rows.append(
                {
                    "knowledge_id": kid,
                    "state": state,
                    "locked": None,
                    "latest": latest,
                    "effective": is_effective,
                    "decision": None,
                }
            )
            continue

        if locked.get("publication_id") == latest.get("publication_id"):
            rows.append(
                {
                    "knowledge_id": kid,
                    "state": "current",
                    "locked": locked,
                    "latest": latest,
                    "effective": is_effective,
                    "decision": None,
                }
            )
            continue

        decision = _decision_for(
            project_root,
            kid,
            locked.get("publication_id"),
            str(latest["publication_id"]),
        )
        if not is_effective:
            state = "scheduled"
        elif decision and decision.get("decision") == "defer":
            state = "deferred"
        else:
            state = "update-available"

        rows.append(
            {
                "knowledge_id": kid,
                "state": state,
                "locked": locked,
                "latest": latest,
                "effective": is_effective,
                "decision": decision,
            }
        )

    return {
        "project_id": config["repository_id"],
        "source_repository_id": source["repository_id"],
        "lock_sha256": _canonical_lock_sha(project_root),
        "rows": rows,
    }


def project_gate(
    project_root: Path,
    team_root: Path,
    *,
    phase: str,
) -> dict[str, Any]:
    if phase not in PHASES:
        raise ValueError(f"invalid gate phase: {phase}")

    status = project_status(project_root, team_root)
    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    for row in status["rows"]:
        state = row["state"]
        latest = row.get("latest")
        requirement = (
            latest.get("adoption_requirement")
            if isinstance(latest, dict)
            else None
        )

        item = {
            "knowledge_id": row["knowledge_id"],
            "state": state,
            "requirement": requirement,
            "locked_publication_id": (
                row["locked"].get("publication_id")
                if isinstance(row.get("locked"), dict)
                else None
            ),
            "latest_publication_id": (
                latest.get("publication_id")
                if isinstance(latest, dict)
                else None
            ),
        }

        if state in {"current"}:
            continue
        if state == "scheduled":
            warnings.append({**item, "reason": "new Publication is not effective yet; locked version remains active"})
            continue
        if state == "scheduled-unlocked":
            blockers.append({**item, "reason": "project has no locked Publication to use before the scheduled version becomes effective"})
            continue
        if state in {"unlocked", "no-publication"}:
            blockers.append({**item, "reason": "project has no usable locked Publication"})
            continue
        if state == "deferred":
            warnings.append({**item, "reason": "review-required update explicitly deferred"})
            continue
        if state == "update-available":
            if requirement == "notice":
                warnings.append({**item, "reason": "new notice-level Publication available"})
            elif requirement == "review-required":
                if phase == "release":
                    blockers.append(
                        {
                            **item,
                            "reason": "review-required update must be accepted or explicitly deferred before release",
                        }
                    )
                else:
                    warnings.append(
                        {
                            **item,
                            "reason": "review-required update must be handled before release",
                        }
                    )
            elif requirement == "must-address":
                blockers.append(
                    {
                        **item,
                        "reason": "must-address update requires lock upgrade",
                    }
                )
            else:
                blockers.append(
                    {
                        **item,
                        "reason": f"unknown adoption requirement: {requirement}",
                    }
                )

    return {
        "phase": phase,
        "ok": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "status": status,
    }


def handle_update(
    project_root: Path,
    team_root: Path,
    knowledge_id: str,
    *,
    decision: str,
    reason: str,
) -> dict[str, Any]:
    if decision not in DECISIONS:
        raise ValueError(f"invalid update decision: {decision}")
    source = _verify_team_source(project_root, team_root)
    if knowledge_id not in (source.get("knowledge_ids") or []):
        raise ValueError(f"knowledge is not declared by project: {knowledge_id}")

    lock_path = _lock_path(project_root)
    lock = read_yaml(lock_path)
    entries = dict(lock.get("entries") or {})
    locked = entries.get(knowledge_id)
    latest = latest_publication_for(team_root, knowledge_id)
    if latest is None:
        raise ValueError(f"no Publication exists for: {knowledge_id}")
    if locked and locked.get("publication_id") == latest.get("publication_id"):
        return {
            "knowledge_id": knowledge_id,
            "decision": "already-current",
            "publication_id": latest["publication_id"],
        }
    if not _effective(latest):
        raise ValueError("latest Publication is not effective yet")

    requirement = str(latest.get("adoption_requirement"))
    from_pub = locked.get("publication_id") if locked else None
    to_pub = str(latest["publication_id"])
    project_id = str(_project_config(project_root)["repository_id"])
    did = _decision_id(project_id, knowledge_id, from_pub, to_pub)

    if decision == "defer":
        if requirement == "must-address":
            raise ValueError("must-address updates cannot be deferred")
        if not reason.strip():
            raise ValueError("defer requires a reason")
        record = {
            "decision_id": did,
            "project_id": project_id,
            "knowledge_id": knowledge_id,
            "from_publication_id": from_pub,
            "to_publication_id": to_pub,
            "requirement": requirement,
            "decision": "defer",
            "reason": reason,
            "decided_at": utc_now(),
        }
        write_yaml(_decision_path(project_root, did), record)
        return record

    # accept upgrades the shared lock to the exact latest Publication.
    entries[knowledge_id] = _publication_entry(latest)
    lock["entries"] = entries
    lock["updated_at"] = utc_now()
    write_yaml(lock_path, lock)

    record = {
        "decision_id": did,
        "project_id": project_id,
        "knowledge_id": knowledge_id,
        "from_publication_id": from_pub,
        "to_publication_id": to_pub,
        "requirement": requirement,
        "decision": "accept",
        "reason": reason,
        "decided_at": utc_now(),
        "new_lock_sha256": _canonical_lock_sha(project_root),
    }
    write_yaml(_decision_path(project_root, did), record)
    return record


def prepare_project_work(
    project_root: Path,
    team_root: Path,
    *,
    goal: str,
) -> Path:
    gate = project_gate(project_root, team_root, phase="start")
    if not gate["ok"]:
        details = "; ".join(
            f"{x['knowledge_id']}: {x['reason']}" for x in gate["blockers"]
        )
        raise ValueError(f"project start gate blocked: {details}")

    config = _project_config(project_root)
    lock = read_yaml(_lock_path(project_root))
    lock_sha = _canonical_lock_sha(project_root)
    wid = "PW-" + short_hash(
        f"{config['repository_id']}|{goal}|{lock_sha}|{utc_now()}".encode(),
        10,
    )
    path = _runs_dir(project_root) / f"{wid}.yml"
    write_yaml(
        path,
        {
            "work_id": wid,
            "consumer_id": config["repository_id"],
            "goal": goal,
            "state": "active",
            "created": utc_now(),
            "project_git": git_info(project_root),
            "knowledge_lock_sha256": lock_sha,
            "knowledge_lock": lock,
            "start_gate": {
                "warnings": gate["warnings"],
            },
            "adopted": [],
        },
    )
    return path


def _git_show(team_root: Path, commit: str, path: str) -> bytes:
    cp = subprocess.run(
        ["git", "-C", str(team_root), "show", f"{commit}:{path}"],
        capture_output=True,
        check=False,
    )
    if cp.returncode:
        raise ValueError(
            cp.stderr.decode(errors="replace").strip()
            or f"cannot read {path} at {commit}"
        )
    return cp.stdout


def project_context(
    project_root: Path,
    team_root: Path,
    work_id: str,
    knowledge_id: str,
) -> dict[str, Any]:
    _verify_team_source(project_root, team_root)
    work = read_yaml(_work_path(project_root, work_id))
    entries = dict((work.get("knowledge_lock") or {}).get("entries") or {})
    entry = entries.get(knowledge_id)
    if entry is None:
        raise ValueError(
            f"knowledge {knowledge_id} was not locked when {work_id} started"
        )
    data = _git_show(
        team_root,
        str(entry["published_ref"]),
        str(entry["path"]),
    )
    digest = hashlib.sha256(data).hexdigest()
    if digest != entry.get("content_sha256"):
        raise ValueError(
            f"locked Publication content hash mismatch for {knowledge_id}"
        )
    return {
        "work_id": work_id,
        "knowledge_id": knowledge_id,
        "publication_id": entry["publication_id"],
        "published_ref": entry["published_ref"],
        "content_sha256": digest,
        "adoption_requirement": entry.get("adoption_requirement"),
        "path": entry["path"],
        "content": data.decode("utf-8"),
    }


def project_adopt(
    project_root: Path,
    work_id: str,
    knowledge_id: str,
    *,
    used_for: str,
) -> dict[str, Any]:
    path = _work_path(project_root, work_id)
    work = read_yaml(path)
    entries = dict((work.get("knowledge_lock") or {}).get("entries") or {})
    entry = entries.get(knowledge_id)
    if entry is None:
        raise ValueError(
            f"knowledge {knowledge_id} was not locked when {work_id} started"
        )

    adopted = work.setdefault("adopted", [])
    item = next(
        (x for x in adopted if x.get("knowledge_id") == knowledge_id),
        None,
    )
    if item is None:
        item = {
            "knowledge_id": knowledge_id,
            "publication_id": entry["publication_id"],
            "published_ref": entry["published_ref"],
            "content_sha256": entry["content_sha256"],
            "adoption_requirement": entry.get("adoption_requirement"),
            "used_for": used_for,
            "outcome": "not-verified",
            "evidence_ids": [],
            "observations": [],
        }
        adopted.append(item)
    else:
        item["used_for"] = used_for
    write_yaml(path, work)
    return item


def project_observe(
    project_root: Path,
    work_id: str,
    knowledge_id: str,
    *,
    outcome: str,
    note: str,
    evidence_ids: list[str] | None = None,
) -> dict[str, Any]:
    if outcome not in ALLOWED_OUTCOMES:
        raise ValueError(f"invalid outcome: {outcome}")
    path = _work_path(project_root, work_id)
    work = read_yaml(path)
    item = next(
        (
            x
            for x in work.get("adopted", [])
            if x.get("knowledge_id") == knowledge_id
        ),
        None,
    )
    if item is None:
        raise ValueError(
            f"knowledge {knowledge_id} was not adopted in {work_id}"
        )
    ids = list(dict.fromkeys(evidence_ids or []))
    item["outcome"] = outcome
    item["evidence_ids"] = list(
        dict.fromkeys([*(item.get("evidence_ids") or []), *ids])
    )
    item.setdefault("observations", []).append(
        {
            "at": utc_now(),
            "outcome": outcome,
            "note": note,
            "evidence_ids": ids,
        }
    )
    write_yaml(path, work)
    return item


def finalize_project_work(
    project_root: Path,
    team_root: Path,
    work_id: str,
) -> dict[str, Any]:
    path = _work_path(project_root, work_id)
    work = read_yaml(path)

    current_lock_sha = _canonical_lock_sha(project_root)
    if current_lock_sha != work.get("knowledge_lock_sha256"):
        raise ValueError(
            "knowledge.lock changed after task start; start a new Work to avoid mixing versions"
        )

    gate = project_gate(project_root, team_root, phase="release")
    if not gate["ok"]:
        details = "; ".join(
            f"{x['knowledge_id']}: {x['reason']}" for x in gate["blockers"]
        )
        raise ValueError(f"project release gate blocked: {details}")

    adoption_paths = record_work_adoptions(team_root, work)
    work["state"] = "finalized"
    work["finalized"] = utc_now()
    work["release_gate"] = {"warnings": gate["warnings"]}
    work["reported_adoption_ids"] = [p.stem for p in adoption_paths]
    write_yaml(path, work)
    return {
        "work_id": work_id,
        "state": "finalized",
        "adoption_ids": [p.stem for p in adoption_paths],
        "warnings": gate["warnings"],
    }
