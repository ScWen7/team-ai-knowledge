"""Read explicitly connected local repositories, using the existing local path map.

No network, discovery, persistent search state, or cross-repository score merging.
The ignored .knowledge/local.yml is the only place that stores machine paths.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from . import core


def _local(root: Path) -> tuple[Path, dict[str, Any]]:
    path = root / ".knowledge/local.yml"
    if (root / ".knowledge").is_symlink() or path.is_symlink():
        raise ValueError("local knowledge connection must not contain a symlink")
    data = core.read_yaml(path) if path.exists() else {}
    mappings = data.get("repositories", {})
    if not isinstance(mappings, dict) or any(
        not isinstance(k, str) or not k.strip() or not isinstance(v, str) or not v.strip()
        for k, v in mappings.items()
    ):
        raise ValueError("local.yml repositories must map repository IDs to local directory paths")
    return path, data


def repository_identity(root: Path) -> str:
    config = root / ".knowledge/config.yml"
    if root.is_symlink() or (root / ".knowledge").is_symlink() or config.is_symlink():
        raise ValueError("connected knowledge repository must not contain a symlink at its root/config")
    if not root.is_dir() or not config.is_file():
        raise ValueError(f"knowledge repository is unavailable or uninitialized: {root}")
    data = core.read_yaml(config)
    identity = data.get("repository_id")
    if data.get("version", 1) != 1 or data.get("profile") not in {"team", "project"}:
        raise ValueError(f"unsupported connected repository configuration: {root}")
    if not isinstance(identity, str) or not identity.strip():
        raise ValueError(f"connected repository_id is required: {root}")
    return identity


def connection_update(root: Path, team_root: Path) -> tuple[Path, dict[str, Any]]:
    """Validate before project initialization writes anything; preserve other mappings."""
    identity = repository_identity(team_root)
    path, local = _local(root)
    entries = dict(local.get("repositories", {}))
    entries[identity] = str(team_root.resolve())
    return path, {**local, "repositories": entries}


def team_path(root: Path, repository_id: str) -> Path:
    _, local = _local(root)
    value = local.get("repositories", {}).get(repository_id)
    if not value:
        raise ValueError(f"team repository {repository_id} is not connected on this machine; set local.yml or project-init --team-root")
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    if repository_identity(candidate) != repository_id:
        raise ValueError(f"connected repository identity mismatch: {repository_id}")
    return candidate.resolve()


def connected_query(root: Path, query: str, *, context: bool = False,
                    statuses: list[str] | str | None = None, scope: str | None = None,
                    limit: int | None = 5) -> dict[str, Any]:
    """Search each authorized checkout and keep results and warnings namespaced."""
    from .retrieval import context_knowledge, search_knowledge_report, _validate_limit
    if not isinstance(query, str):
        raise ValueError("query must be a string")
    _validate_limit(limit)
    root = root.resolve()
    issues: list[dict[str, str]] = []
    sources: list[dict[str, Any]] = []
    roots: list[tuple[str, Path]] = []
    try:
        identity = repository_identity(root) if (root / ".knowledge/config.yml").exists() else root.name
        roots.append((identity, root))
        _, local = _local(root)
        mappings = local.get("repositories", {})
        for rid in mappings:
            try:
                candidate = team_path(root, rid)
                if candidate != root:
                    roots.append((rid, candidate))
            except (ValueError, OSError, yaml.YAMLError) as exc:
                issues.append({"repository_id": rid, "kind": "unavailable", "message": str(exc)})
        config_path = root / ".knowledge/config.yml"
        config = core.read_yaml(config_path) if config_path.exists() else {}
        declared = config.get("knowledge_sources") or []
        if not isinstance(declared, list) or any(not isinstance(item, dict) for item in declared):
            raise ValueError("knowledge_sources must be a list of source mappings")
        for source in declared:
            rid = source.get("repository_id")
            if rid and rid not in mappings and rid != identity:
                issues.append({"repository_id": str(rid), "kind": "not_connected",
                               "message": "Subscribed team repository is not connected on this machine; its knowledge was not searched."})
    except (ValueError, OSError, yaml.YAMLError) as exc:
        issues.append({"repository_id": root.name, "kind": "configuration", "message": str(exc)})
    for rid, checkout in roots:
        try:
            if context:
                result = context_knowledge(checkout, query, limit=5 if limit is None else limit,
                                           statuses=statuses, scope=scope)
                found_issues = result.pop("issues")
            else:
                rows, found_issues = search_knowledge_report(checkout, query, statuses=statuses,
                                                             scope=scope, limit=limit)
                result = {"results": rows}
            sources.append({"repository_id": rid, "root": str(checkout),
                            "git": core.git_info(checkout), **result})
            issues.extend({"repository_id": rid, **issue} for issue in found_issues)
        except (ValueError, OSError, yaml.YAMLError) as exc:
            issues.append({"repository_id": rid, "kind": "unavailable", "message": str(exc)})
    return {"sources": sources, "issues": issues, "complete": not issues,
            "scope": "current checkout and explicitly connected local checkouts only",
            "note": "候选资料，不是已确认答案；继续读取原文、核对适用条件。未连接/不可读不等于知识不存在；本地版本不保证是远端最新。"}
