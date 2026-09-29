"""Read current Markdown files directly, without a database or persistent cache.

A repository ID selects the entire configured document set. Other scopes match
an explicit frontmatter scope or a repository-relative path and its descendants.
A context request reuses its own document snapshot; nothing survives the call.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

import yaml

from . import core


@dataclass
class _Document:
    path: str
    meta: dict[str, Any]
    body: str

    @property
    def id(self) -> str | None:
        return self.meta.get("id")

    @property
    def title(self) -> str:
        return str(self.meta.get("title") or Path(self.path).stem)

    @property
    def status(self) -> str | None:
        value = self.meta.get("status", "unclassified")
        return str(value) if value is not None else None


def _read_config(root: Path) -> dict[str, Any]:
    path = root / ".knowledge/config.yml"
    if (root / ".knowledge").is_symlink() or path.is_symlink():
        raise ValueError(".knowledge/config.yml path must not contain a symlink")
    try:
        config = core.read_yaml(path) if path.is_file() else {}
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot read .knowledge/config.yml: {exc}") from exc
    if config.get("version", 1) != 1:
        raise ValueError("unsupported knowledge config version")
    if config.get("profile", "team") not in (None, "team", "project"):
        raise ValueError(f"unsupported team-wiki profile for retrieval: {config.get('profile')}")
    return config


def _signature(stat: os.stat_result) -> tuple[int, int, int, int]:
    return stat.st_mtime_ns, stat.st_size, stat.st_ino, stat.st_ctime_ns


def _read_document(root: Path, path: Path) -> _Document:
    relative = path.relative_to(root).as_posix()
    for _ in range(2):
        # Recheck the selected path at read time, including symlinked parents.
        if any(parent.is_symlink() for parent in (path, *path.parents) if parent != root):
            raise ValueError(f"knowledge document path contains a symlink: {relative}")
        try:
            before = path.stat()
            meta, body = core.parse_frontmatter(path)
            after = path.stat()
        except (OSError, UnicodeError, yaml.YAMLError, ValueError) as exc:
            raise ValueError(f"cannot parse knowledge document {relative}: {exc}") from exc
        if _signature(before) == _signature(after):
            identity = meta.get("id")
            if identity is not None and (not isinstance(identity, str) or not identity.strip()):
                raise ValueError(f"knowledge id must be a non-empty string: {relative}")
            from .documents import _guess_title
            meta = {**meta, "title": meta.get("title") or _guess_title(path, body)}
            return _Document(relative, meta, body)
    raise ValueError(f"document changed while being read: {relative}")


def _load_documents(root: Path) -> tuple[dict[str, Any], list[_Document], list[dict[str, str]]]:
    """Read every configured document; one unreadable file must not block the rest.

    Unreadable files are skipped and reported. Duplicate IDs stay searchable
    but are reported, because either copy may be the authoritative one.
    """
    config = _read_config(root)
    documents: list[_Document] = []
    issues: list[dict[str, str]] = []
    identities: dict[str, str] = {}
    # Read-only scope includes useful README/INDEX content without making it editable.
    if config.get("profile") == "project" or (not config and not (root / "wiki").exists()):
        from .documents import document_files_report
        paths, scan_issues = document_files_report(root, for_retrieval=True)
        issues.extend({"path": item.get("path", "."), "kind": "skipped", "message": item["message"]}
                      for item in scan_issues)
    else:
        paths = core.iter_knowledge_files(root)
    for path in paths:
        try:
            document = _read_document(root, path)
        except ValueError as exc:
            issues.append({"path": path.relative_to(root).as_posix(), "kind": "skipped", "message": str(exc)})
            continue
        if document.id:
            if document.id in identities:
                issues.append({"path": document.path, "kind": "duplicate_id",
                               "message": f"duplicate document id {document.id}: {identities[document.id]}, {document.path}"})
            else:
                identities[document.id] = document.path
        documents.append(document)
    return config, documents, issues


def _statuses(value: Iterable[str] | str | None) -> set[str] | None:
    if value is None:
        return None
    try:
        items = [value] if isinstance(value, str) else list(value)
    except TypeError as exc:
        raise ValueError("statuses must be a string or iterable of strings") from exc
    if any(not isinstance(item, str) for item in items):
        raise ValueError("statuses entries must be strings")
    return set(items)


def _validate_limit(limit: int | None) -> None:
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit < 0):
        raise ValueError("limit must be a non-negative integer or None")


def _selected(document: _Document, config: dict[str, Any], statuses: set[str] | None,
              scope: str | None) -> bool:
    if statuses is not None and document.status not in statuses:
        return False
    if scope is None:
        return True
    if not isinstance(scope, str) or not scope.strip():
        return False
    value = scope.strip().replace("\\", "/")
    if value == config.get("repository_id"):
        return True
    declared = document.meta.get("scope")
    if isinstance(declared, str) and declared.strip() == value:
        return True
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts or relative.as_posix() == ".":
        return False
    path = relative.as_posix().rstrip("/")
    return document.path == path or document.path.startswith(path + "/")


def _result(document: _Document, score: int) -> dict[str, Any]:
    return {"score": score, "id": document.id, "title": document.title,
            "status": document.status, "path": document.path}


def _search(documents: list[_Document], query: str, limit: int | None) -> list[dict[str, Any]]:
    exact = [_result(document, 1) for document in documents if document.id == query.strip()]
    if exact:
        return exact[:limit]
    terms = core.tokenize_query(query)
    results = []
    for document in documents:
        fields = {key: value.lower() for key, value in core._knowledge_fields(document.meta, document.body).items()}
        score = 0
        for term in terms:
            weight = core.FIELD_WEIGHTS["body"]
            for field in ("title", "tags", "summary"):
                if term in fields[field]:
                    weight = core.FIELD_WEIGHTS[field]
                    break
            score += sum(value.count(term) for value in fields.values()) * weight * len(term)
        if score:
            results.append(_result(document, score))
    return sorted(results, key=lambda item: (-item["score"], item["path"]))[:limit]


def _relation_ids(meta: dict[str, Any]) -> set[str]:
    links: set[str] = set()
    for field in ("related", "depends_on", "references"):
        items = meta.get(field) or []
        if isinstance(items, (str, dict)):
            items = [items]
        if not isinstance(items, list):
            continue
        for item in items:
            if field == "references" and (not isinstance(item, dict) or item.get("relation") not in
                                          {"related", "related_to", "depends_on", "supersedes"}):
                continue
            identity = item.get("id") if isinstance(item, dict) else item
            if isinstance(identity, str) and identity:
                links.add(identity)
    return links


def _related(documents: list[_Document], knowledge_id: str, limit: int) -> list[dict[str, Any]]:
    sources = [document for document in documents if document.id == knowledge_id]
    if len(sources) > 1:
        raise ValueError(f"ambiguous knowledge id {knowledge_id}: resolve duplicate IDs before related lookup")
    source = sources[0] if sources else None
    if source is None:
        return []
    outgoing = _relation_ids(source.meta)
    counts: dict[str, int] = {}
    for document in documents:
        if document.id:
            counts[document.id] = counts.get(document.id, 0) + 1
    results = []
    for document in documents:
        if not document.id or document.id == knowledge_id or counts[document.id] > 1:
            continue
        relevance = int(document.id in outgoing) + int(knowledge_id in _relation_ids(document.meta))
        if relevance:
            results.append({"id": document.id, "title": document.title, "path": document.path,
                            "relevance": relevance})
    return sorted(results, key=lambda item: (item["id"], item["path"]))[:limit]


def _filtered(root: Path, statuses: set[str] | None, scope: str | None
              ) -> tuple[list[_Document], list[dict[str, str]]]:
    config, documents, issues = _load_documents(root.resolve())
    return [document for document in documents if _selected(document, config, statuses, scope)], issues


def search_knowledge_report(root: Path, query: str, *, statuses: Iterable[str] | str | None = None,
                            scope: str | None = None, limit: int | None = None
                            ) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Return ranked results plus the files that were skipped or ambiguous."""
    if not isinstance(query, str):
        raise ValueError("query must be a string")
    _validate_limit(limit)
    selected_statuses = _statuses(statuses)
    if not query.strip() or not core.tokenize_query(query) or selected_statuses == set() or limit == 0:
        return [], []
    documents, issues = _filtered(root, selected_statuses, scope)
    return _search(documents, query, limit), issues


def search_knowledge(root: Path, query: str, *, statuses: Iterable[str] | str | None = None,
                     scope: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
    return search_knowledge_report(root, query, statuses=statuses, scope=scope, limit=limit)[0]


def related_knowledge(root: Path, knowledge_id: str, limit: int = 5, *,
                      statuses: Iterable[str] | str | None = None,
                      scope: str | None = None) -> list[dict[str, Any]]:
    _validate_limit(limit)
    if limit is None:
        raise ValueError("limit must be a non-negative integer")
    selected_statuses = _statuses(statuses)
    if not isinstance(knowledge_id, str) or not knowledge_id or limit == 0 or selected_statuses == set():
        return []
    return _related(_filtered(root, selected_statuses, scope)[0], knowledge_id, limit)


def context_knowledge(root: Path, query: str, limit: int = 5, *,
                      statuses: Iterable[str] | str | None = None,
                      scope: str | None = None) -> dict[str, Any]:
    """Share only this call's freshly read documents between search and relations."""
    if not isinstance(query, str):
        raise ValueError("query must be a string")
    _validate_limit(limit)
    if limit is None:
        raise ValueError("limit must be a non-negative integer")
    selected_statuses = _statuses(statuses)
    if not query.strip() or not core.tokenize_query(query) or limit == 0 or selected_statuses == set():
        return {"direct": [], "related": {}, "issues": []}
    documents, issues = _filtered(root, selected_statuses, scope)
    direct = _search(documents, query, limit)
    related = {}
    for row in direct[:2]:
        if row.get("id"):
            try:
                related[row["id"]] = _related(documents, row["id"], 3)
            except ValueError:
                # Duplicate identities remain visible in search, never pick a source silently.
                related[row["id"]] = []
    return {"direct": direct, "related": related, "issues": issues}
