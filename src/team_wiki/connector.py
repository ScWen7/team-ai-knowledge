"""Local Git source connector with checkpointed incremental sync.

The connector does not store absolute local repository paths in shared state.
A sync caller supplies the authorized local checkout path. Checkpoints advance
only after all detected events are processed. Partial source mutations remain
idempotent and are recorded in a sync-run ledger.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
import shutil
from pathlib import Path, PurePosixPath
from typing import Any

from .core import (
    _find_source_package,
    _rewrite_change_meta,
    create_change,
    index_workspace,
    parse_frontmatter,
    read_yaml,
    register_source,
    utc_now,
    write_yaml,
)
from .impact import knowledge_using_source, refresh_source
from .intake import SUPPORTED_SUFFIXES, intake_source
from .review import upsert_review


def _connector_id(value: str) -> str:
    value = value.strip()
    if not value or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for ch in value):
        raise ValueError("connector_id may contain only letters, numbers, - and _")
    return value


def _state_path(root: Path, connector_id: str) -> Path:
    return root / ".knowledge/records/connectors" / f"{_connector_id(connector_id)}.yml"


def _run_dir(root: Path) -> Path:
    return root / ".knowledge/records/connector-runs"


def _safe_include(path: str) -> str:
    pure = PurePosixPath(path)
    if pure.is_absolute() or ".." in pure.parts:
        raise ValueError(f"invalid include path: {path}")
    value = pure.as_posix().strip("/")
    return value or "."


def create_git_connector(
    root: Path,
    connector_id: str,
    *,
    repository_id: str,
    include_paths: list[str],
    logical_root: str | None = None,
    auto_intake: bool = False,
) -> Path:
    connector_id = _connector_id(connector_id)
    if not repository_id.strip():
        raise ValueError("repository_id is required")
    paths = list(dict.fromkeys(_safe_include(x) for x in include_paths or ["."]))
    path = _state_path(root, connector_id)
    if path.exists():
        raise ValueError(f"connector already exists: {connector_id}")
    write_yaml(path, {
        "version": 1,
        "connector_id": connector_id,
        "type": "git",
        "repository_id": repository_id,
        "include_paths": paths,
        "logical_root": logical_root,
        "auto_intake": bool(auto_intake),
        "checkpoint": None,
        "tracked": {},
        "retired": {},
        "created": utc_now(),
        "updated": utc_now(),
        "last_sync": None,
    })
    return path


def connector_status(root: Path, connector_id: str) -> dict[str, Any]:
    path = _state_path(root, connector_id)
    if not path.is_file():
        raise KeyError(f"connector not found: {connector_id}")
    return read_yaml(path)


def _git(repo: Path, *args: str, text: bool = True) -> str | bytes:
    cp = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=text,
        check=False,
    )
    if cp.returncode:
        stderr = cp.stderr.strip() if text else cp.stderr.decode(errors="replace").strip()
        raise ValueError(stderr or f"git command failed: {' '.join(args)}")
    return cp.stdout


def _head(repo: Path) -> str:
    return str(_git(repo, "rev-parse", "HEAD")).strip()


def _ensure_repo(repo: Path) -> None:
    if not repo.is_dir():
        raise ValueError(f"repository path not found: {repo}")
    inside = str(_git(repo, "rev-parse", "--is-inside-work-tree")).strip()
    if inside != "true":
        raise ValueError(f"not a Git worktree: {repo}")


def _list_paths(repo: Path, commit: str, include_paths: list[str]) -> list[str]:
    args = ["ls-tree", "-r", "--name-only", "-z", commit]
    if include_paths != ["."]:
        args += ["--", *include_paths]
    raw = _git(repo, *args, text=False)
    assert isinstance(raw, bytes)
    return [os.fsdecode(x) for x in raw.split(b"\0") if x]


def _in_scope(path: str, include_paths: list[str]) -> bool:
    if include_paths == ["."]:
        return True
    pure = PurePosixPath(path)
    for base in include_paths:
        prefix = PurePosixPath(base)
        if pure == prefix or prefix in pure.parents:
            return True
    return False


def _diff_events(repo: Path, old: str, new: str, include_paths: list[str]) -> list[dict[str, Any]]:
    # Diff the whole tree first. Applying pathspecs before rename detection can
    # turn "renamed out of monitored scope" into a false delete.
    raw = _git(repo, "diff", "--name-status", "-M", "-z", old, new, text=False)
    assert isinstance(raw, bytes)
    fields = [os.fsdecode(x) for x in raw.split(b"\0") if x]
    out: list[dict[str, Any]] = []
    i = 0
    while i < len(fields):
        status = fields[i]
        i += 1
        kind = status[0]
        if kind in {"R", "C"}:
            if i + 1 >= len(fields):
                raise ValueError("unexpected git rename diff output")
            old_path, new_path = fields[i], fields[i + 1]
            i += 2
            old_in = _in_scope(old_path, include_paths)
            new_in = _in_scope(new_path, include_paths)
            if old_in and new_in:
                out.append({"kind": "rename", "status": status, "old_path": old_path, "path": new_path})
            elif old_in and not new_in:
                out.append({"kind": "scope-remove", "status": status, "old_path": old_path, "path": new_path})
            elif not old_in and new_in:
                out.append({"kind": "add", "status": status, "path": new_path, "from_path": old_path})
        else:
            if i >= len(fields):
                raise ValueError("unexpected git diff output")
            path = fields[i]
            i += 1
            if not _in_scope(path, include_paths):
                continue
            mapping = {"A": "add", "M": "modify", "D": "delete", "T": "modify"}
            if kind in mapping:
                out.append({"kind": mapping[kind], "status": status, "path": path})
    return out


def _blob(repo: Path, commit: str, path: str) -> bytes:
    raw = _git(repo, "show", f"{commit}:{path}", text=False)
    assert isinstance(raw, bytes)
    return raw


def _logical_path(connector: dict[str, Any], path: str) -> str:
    root = connector.get("logical_root")
    return f"{str(root).rstrip('/')}/{path}" if root else path


def _source_meta(root: Path, source_id: str) -> tuple[Path, dict[str, Any]]:
    pkg = _find_source_package(root, source_id)
    if pkg is None:
        raise KeyError(f"source id not found: {source_id}")
    meta = pkg / "source.yml"
    return meta, read_yaml(meta)


def _write_temp_blob(data: bytes, upstream_path: str) -> Path:
    directory = Path(tempfile.mkdtemp(prefix="team-wiki-git-"))
    name = Path(upstream_path).name or "source"
    path = directory / name
    path.write_bytes(data)
    return path


def _cleanup_temp_blob(path: Path) -> None:
    shutil.rmtree(path.parent, ignore_errors=True)


def _initial_add(
    root: Path,
    connector: dict[str, Any],
    repo: Path,
    commit: str,
    path: str,
) -> str:
    data = _blob(repo, commit, path)
    temp = _write_temp_blob(data, path)
    try:
        pkg = register_source(
            root,
            temp,
            title=Path(path).stem,
            connector_id=connector["connector_id"],
            upstream_id=f"{connector['repository_id']}:{path}",
            logical_path=_logical_path(connector, path),
        )
        meta = read_yaml(pkg / "source.yml")
        source_id = meta["source_id"]
        if connector.get("auto_intake") and Path(path).suffix.lower() in SUPPORTED_SUFFIXES:
            intake_source(root, source_id)
        return source_id
    finally:
        _cleanup_temp_blob(temp)


def _refresh(
    root: Path,
    connector: dict[str, Any],
    repo: Path,
    commit: str,
    path: str,
    source_id: str,
    owner: str,
) -> dict[str, Any]:
    data = _blob(repo, commit, path)
    temp = _write_temp_blob(data, Path(path).suffix)
    try:
        result = refresh_source(root, source_id, temp, owner=owner)
        meta_path, meta = _source_meta(root, source_id)
        origin = dict(meta.get("origin") or {})
        origin["connector_id"] = connector["connector_id"]
        origin["upstream_id"] = f"{connector['repository_id']}:{path}"
        origin["logical_path"] = _logical_path(connector, path)
        meta["origin"] = origin
        write_yaml(meta_path, meta)
        if connector.get("auto_intake") and Path(path).suffix.lower() in SUPPORTED_SUFFIXES:
            intake_source(root, source_id)
        return result
    finally:
        temp.unlink(missing_ok=True)


def _rename(
    root: Path,
    connector: dict[str, Any],
    repo: Path,
    commit: str,
    old_path: str,
    new_path: str,
    source_id: str,
    owner: str,
) -> dict[str, Any]:
    meta_path, meta = _source_meta(root, source_id)
    origin = dict(meta.get("origin") or {})
    origin["connector_id"] = connector["connector_id"]
    origin["upstream_id"] = f"{connector['repository_id']}:{new_path}"
    origin["logical_path"] = _logical_path(connector, new_path)
    meta["origin"] = origin
    meta.setdefault("origin_history", []).append({
        "at": utc_now(),
        "event": "rename",
        "from": old_path,
        "to": new_path,
        "commit": commit,
    })
    write_yaml(meta_path, meta)
    return _refresh(root, connector, repo, commit, new_path, source_id, owner)


def _delete(
    root: Path,
    connector: dict[str, Any],
    commit: str,
    path: str,
    source_id: str,
    owner: str,
) -> dict[str, Any]:
    meta_path, meta = _source_meta(root, source_id)
    if meta.get("deleted_upstream_commit") == commit:
        return {
            "source_id": source_id,
            "change_id": meta.get("deletion_change_id"),
            "review_id": meta.get("deletion_review_id"),
            "affected": knowledge_using_source(root, source_id),
        }

    affected = knowledge_using_source(root, source_id)
    change_id = None
    review_id = None
    if affected:
        change = create_change(root, f"复核已删除来源 {source_id}", owner)
        change_meta, _ = parse_frontmatter(change)
        change_id = change_meta["change_id"]
        review = upsert_review(
            root,
            kind="confirm",
            title=f"来源 {source_id} 已从 Git 上游删除",
            description="上游 Git diff 明确报告删除；需要确认依赖知识是否仍有其他有效依据。",
            owner=owner,
            scope_key=f"source:{source_id}",
            affected=affected,
            linked_changes=[change_id],
            evidence_version=f"deleted:{commit}",
            observation=f"git path deleted at {commit}: {path}",
        )
        review_meta, _ = parse_frontmatter(review)
        review_id = review_meta["review_id"]
        _rewrite_change_meta(change, {
            "origin": {"work_ids": [], "source_ids": [source_id]},
            "affected": affected,
            "review_ids": [review_id],
            "evidence_ids": [],
        })

    meta["status"] = "deleted-upstream"
    meta["deleted_at"] = utc_now()
    meta["deleted_upstream_commit"] = commit
    if change_id:
        meta["deletion_change_id"] = change_id
    if review_id:
        meta["deletion_review_id"] = review_id
    write_yaml(meta_path, meta)
    return {
        "source_id": source_id,
        "change_id": change_id,
        "review_id": review_id,
        "affected": affected,
    }


def sync_git_connector(
    root: Path,
    connector_id: str,
    repo_path: Path,
    *,
    owner: str = "unassigned",
) -> dict[str, Any]:
    state_path = _state_path(root, connector_id)
    if not state_path.is_file():
        raise KeyError(f"connector not found: {connector_id}")
    connector = read_yaml(state_path)
    if connector.get("type") != "git":
        raise ValueError("connector is not a git connector")

    repo = repo_path.resolve()
    _ensure_repo(repo)
    head = _head(repo)
    old = connector.get("checkpoint")
    tracked = dict(connector.get("tracked") or {})
    retired = dict(connector.get("retired") or {})
    include_paths = list(connector.get("include_paths") or ["."])

    if old == head:
        return {
            "connector_id": connector_id,
            "checkpoint": head,
            "changed": False,
            "events": [],
        }

    if old:
        # Verify the old checkpoint is still known locally before calculating a diff.
        _git(repo, "cat-file", "-e", f"{old}^{{commit}}")
        events = _diff_events(repo, str(old), head, include_paths)
    else:
        events = [{"kind": "add", "status": "A", "path": p} for p in _list_paths(repo, head, include_paths)]

    run_key = f"{connector_id}|{old}|{head}"
    run_id = "SYNC-" + hashlib.sha256(run_key.encode()).hexdigest()[:12].upper()
    run_path = _run_dir(root) / f"{run_id}.yml"
    run = {
        "sync_id": run_id,
        "connector_id": connector_id,
        "from_checkpoint": old,
        "to_checkpoint": head,
        "state": "applying",
        "created": utc_now(),
        "events": events,
        "processed": [],
        "error": None,
    }
    write_yaml(run_path, run)

    new_tracked = dict(tracked)
    counts = {"add": 0, "modify": 0, "rename": 0, "delete": 0, "scope-remove": 0}
    try:
        for event in events:
            kind = event["kind"]
            if kind == "add":
                path = event["path"]
                source_id = _initial_add(root, connector, repo, head, path)
                new_tracked[path] = source_id
                detail = {"kind": kind, "path": path, "source_id": source_id}
            elif kind == "modify":
                path = event["path"]
                source_id = new_tracked.get(path)
                if source_id is None:
                    source_id = _initial_add(root, connector, repo, head, path)
                    new_tracked[path] = source_id
                    detail = {"kind": "add-recovered", "path": path, "source_id": source_id}
                else:
                    result = _refresh(root, connector, repo, head, path, source_id, owner)
                    detail = {"kind": kind, "path": path, "source_id": source_id, "refresh": result}
            elif kind == "rename":
                old_path = event["old_path"]
                path = event["path"]
                source_id = new_tracked.get(old_path)
                if source_id is None:
                    source_id = _initial_add(root, connector, repo, head, path)
                    detail = {"kind": "rename-recovered-as-add", "old_path": old_path, "path": path, "source_id": source_id}
                else:
                    result = _rename(root, connector, repo, head, old_path, path, source_id, owner)
                    detail = {"kind": kind, "old_path": old_path, "path": path, "source_id": source_id, "refresh": result}
                    new_tracked.pop(old_path, None)
                new_tracked[path] = source_id
            elif kind == "delete":
                path = event["path"]
                source_id = new_tracked.get(path)
                if source_id is None:
                    detail = {"kind": "delete-untracked", "path": path}
                else:
                    result = _delete(root, connector, head, path, source_id, owner)
                    detail = {"kind": kind, "path": path, "source_id": source_id, "deletion": result}
                    retired[path] = source_id
                    new_tracked.pop(path, None)
            elif kind == "scope-remove":
                old_path = event["old_path"]
                new_path = event["path"]
                source_id = new_tracked.get(old_path)
                if source_id is None:
                    detail = {"kind": "scope-remove-untracked", "old_path": old_path, "path": new_path}
                else:
                    meta_path, meta = _source_meta(root, source_id)
                    meta["status"] = "out-of-scope"
                    meta["scope_removed_at"] = utc_now()
                    meta["scope_removed_commit"] = head
                    meta.setdefault("origin_history", []).append({
                        "at": utc_now(),
                        "event": "scope-remove",
                        "from": old_path,
                        "to": new_path,
                        "commit": head,
                    })
                    write_yaml(meta_path, meta)
                    retired[old_path] = source_id
                    new_tracked.pop(old_path, None)
                    detail = {"kind": kind, "old_path": old_path, "path": new_path, "source_id": source_id}
            else:
                continue
            counts[kind] = counts.get(kind, 0) + 1
            run["processed"].append(detail)
            write_yaml(run_path, run)
    except Exception as exc:
        run["state"] = "failed"
        run["error"] = str(exc)
        run["failed_at"] = utc_now()
        write_yaml(run_path, run)
        # Deliberately do not advance connector checkpoint or path mapping.
        raise

    connector["checkpoint"] = head
    connector["tracked"] = new_tracked
    connector["retired"] = retired
    connector["updated"] = utc_now()
    connector["last_sync"] = {
        "sync_id": run_id,
        "at": utc_now(),
        "counts": counts,
    }
    write_yaml(state_path, connector)

    run["state"] = "completed"
    run["completed"] = utc_now()
    run["counts"] = counts
    write_yaml(run_path, run)
    index_workspace(root)
    return {
        "connector_id": connector_id,
        "checkpoint": head,
        "previous_checkpoint": old,
        "changed": bool(events),
        "counts": counts,
        "events": run["processed"],
        "sync_id": run_id,
    }
