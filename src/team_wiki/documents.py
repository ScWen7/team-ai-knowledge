"""Safe, incremental governance for existing project Markdown documents.

The module deliberately edits only frontmatter additions and its own navigation
file. Markdown bodies and existing frontmatter bytes are retained verbatim.
"""

from __future__ import annotations

import difflib
import base64
import hashlib
import json
import math
import os
import posixpath
import re
import stat
import tempfile
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote, unquote, urlsplit

import yaml


_FRONTMATTER_RE = re.compile(
    r"\A\ufeff?---[ \t]*(?P<eol>\r\n|\n)(?P<meta>.*?)(?P<before_close>\r\n|\n)?"
    r"^---[ \t]*(?P<close_eol>\r\n|\n|\Z)",
    re.DOTALL | re.MULTILINE,
)
_FRONTMATTER_OPEN_RE = re.compile(r"\A\ufeff?---[ \t]*(?:\r?\n|\Z)")
_H1_RE = re.compile(r"^\s{0,3}#\s+(.+?)\s*#*\s*$")
_LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
_FENCE_RE = re.compile(r"(?ms)^\s{0,3}(```+|~~~+)[^\r\n]*\r?\n.*?^\s{0,3}(?:```+|~~~+)[ \t]*$")
_INLINE_CODE_RE = re.compile(r"(?<!`)`[^`\r\n]*`(?!`)")
_NAVIGATION_NAMES = {
    "agents.md",
    "claude.md",
    "index.md",
    "readme.md",
    "toc.md",
    "table-of-contents.md",
    "table_of_contents.md",
    "contents.md",
    "navigation.md",
    "nav.md",
}
_EXCLUDED_DIRS = {
    ".git",
    ".svn",
    ".hg",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "vendor",
    "__pycache__",
    "dist",
    "build",
    "target",
    ".next",
    ".tox",
    "archive",
    "archives",
    "archived",
    "deprecated",
    "legacy",
    "归档",
    "历史归档",
}
_ID_ALIASES = ("id", "doc_id", "document_id", "knowledge_id")
_TITLE_ALIASES = ("title", "name")
_TYPE_ALIASES = ("type", "doc_type")
_CONFIG_UNSET = object()


class _DuplicateKeyError(yaml.constructor.ConstructorError):
    """Raised when a YAML mapping repeats a key instead of silently overriding it."""


class _DuplicateCriticalFieldError(ValueError):
    """Raised when two aliases compete for one canonical metadata field."""


class _FrontmatterMappingError(TypeError):
    """Raised when frontmatter parses but is not a string-keyed mapping."""


class _UniqueKeyLoader(yaml.SafeLoader):
    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        if not isinstance(node, yaml.MappingNode):
            return super().construct_mapping(node, deep=deep)
        result: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                duplicate = key in result
            except TypeError as exc:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "mapping key is not hashable",
                    key_node.start_mark,
                ) from exc
            if duplicate:
                raise _DuplicateKeyError(
                    "while constructing a mapping",
                    node.start_mark,
                    f"duplicate key {key!r}",
                    key_node.start_mark,
                )
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def _load_yaml_mapping(source: str) -> dict[str, Any]:
    if not source.strip():
        return {}
    value = yaml.load(source, Loader=_UniqueKeyLoader)
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise _FrontmatterMappingError("frontmatter must be a mapping with string keys")
    return value


def _issue(
    code: str,
    message: str,
    *,
    path: str | None = None,
    severity: str = "error",
    blocking: bool = False,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "code": code,
        "message": message,
        "severity": severity,
        "blocking": blocking,
    }
    if path is not None:
        item["path"] = path
    return item


def _relative_candidate(root: Path, raw: Any) -> tuple[str, Path] | None:
    if not isinstance(raw, (str, os.PathLike)):
        return None
    value = os.fspath(raw)
    if not value or "\x00" in value or "\\" in value:
        return None
    if Path(value).is_absolute() or re.match(r"^[A-Za-z]:", value):
        return None
    pure = PurePosixPath(value)
    if any(part == ".." for part in pure.parts) or pure.as_posix() in {""}:
        return None
    rel = pure.as_posix()
    candidate = root / Path(*pure.parts)
    return rel, candidate


def _has_symlink_component(root: Path, rel: str) -> bool:
    cursor = root
    for part in PurePosixPath(rel).parts:
        cursor = cursor / part
        try:
            if cursor.is_symlink():
                return True
        except OSError:
            return True
    return False


def _read_config(root: Path, issues: list[dict[str, Any]]) -> dict[str, Any] | None:
    config_path = root / ".knowledge" / "config.yml"
    if not config_path.exists() and not config_path.is_symlink():
        return None
    if _has_symlink_component(root, ".knowledge/config.yml"):
        issues.append(
            _issue(
                "config_symlink",
                "项目配置路径包含符号链接，拒绝读取文档范围。",
                path=".knowledge/config.yml",
                blocking=True,
            )
        )
        return {}
    try:
        raw = config_path.read_bytes()
        data = _load_yaml_mapping(raw.decode("utf-8"))
        return data
    except Exception as exc:
        issues.append(
            _issue(
                "invalid_config",
                f"无法读取 .knowledge/config.yml：{exc}",
                path=".knowledge/config.yml",
                blocking=True,
            )
        )
        return {}


def _scope_entries(
    root: Path,
    paths: list[str] | None,
    *,
    config_data: dict[str, Any] | None | object = _CONFIG_UNSET,
) -> tuple[list[tuple[str, Path]], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    try:
        resolved_root = root.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        return [], [_issue("invalid_root", f"项目根目录不可访问：{exc}", blocking=True)]
    if not resolved_root.is_dir():
        return [], [_issue("invalid_root", "项目根目录不是目录。", blocking=True)]

    configured: list[Any] | None = None
    if paths is not None:
        # An explicitly empty list is an intentional empty scope.
        configured = list(paths)
    else:
        config = _read_config(resolved_root, issues) if config_data is _CONFIG_UNSET else config_data
        if config is not None:
            if not isinstance(config, dict):
                config = {}
            if "document_paths" in config:
                raw_paths = config["document_paths"]
                if not isinstance(raw_paths, list) or any(not isinstance(item, str) for item in raw_paths):
                    issues.append(
                        _issue(
                            "invalid_document_paths",
                            ".knowledge/config.yml 的 document_paths 必须是相对路径列表。",
                            path=".knowledge/config.yml",
                            blocking=True,
                        )
                    )
                    configured = []
                else:
                    configured = raw_paths
    if configured is None:
        configured = [
            name
            for name in ("docs", "doc", "knowledge", "knowledge-base", "文档", "知识库", "README.md")
            if (resolved_root / name).exists() or (resolved_root / name).is_symlink()
        ]

    entries: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for raw in configured:
        candidate_info = _relative_candidate(resolved_root, raw)
        display = os.fspath(raw) if isinstance(raw, (str, os.PathLike)) else repr(raw)
        if candidate_info is None:
            issues.append(
                _issue(
                    "unsafe_scope_path",
                    f"文档范围路径必须是仓库内相对路径：{display}",
                    path=display,
                    blocking=True,
                )
            )
            continue
        rel, candidate = candidate_info
        if _has_symlink_component(resolved_root, rel):
            issues.append(
                _issue(
                    "scope_symlink",
                    f"文档范围包含符号链接，拒绝治理：{rel}",
                    path=rel,
                    blocking=True,
                )
            )
            continue
        try:
            is_dir = candidate.is_dir()
            is_file = candidate.is_file()
        except OSError:
            is_dir = is_file = False
        if not is_dir and not (is_file and candidate.suffix.lower() in {".md", ".markdown"}):
            issues.append(
                _issue(
                    "missing_scope_path",
                    f"文档范围不存在或不是 Markdown 文件/目录：{rel}",
                    path=rel,
                    blocking=True,
                )
            )
            continue
        if rel not in seen:
            entries.append((rel, candidate))
            seen.add(rel)
    return entries, issues


def document_roots(root: Path, paths: list[str] | None = None) -> list[str]:
    """Return safe document directories/files selected for this repository."""
    entries, _ = _scope_entries(Path(root), paths)
    return [rel for rel, _ in entries]


def _excluded_rel(rel: str, *, for_retrieval: bool = False) -> bool:
    pure = PurePosixPath(rel)
    if any(part.startswith(".") for part in pure.parts):
        return True
    if any(part.casefold() in _EXCLUDED_DIRS for part in pure.parts[:-1]):
        return True
    excluded_names = {"agents.md", "claude.md"} if for_retrieval else _NAVIGATION_NAMES
    if pure.name.casefold() in excluded_names:
        return True
    return pure.suffix.lower() not in {".md", ".markdown"}


def _scan_entries(
    root: Path,
    entries: list[tuple[str, Path]],
    *, for_retrieval: bool = False,
) -> tuple[list[Path], list[dict[str, Any]]]:
    files: list[Path] = []
    issues: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_file(rel: str, path: Path) -> None:
        if _excluded_rel(rel, for_retrieval=for_retrieval) or rel in seen:
            return
        try:
            if path.is_symlink():
                issues.append(
                    _issue(
                        "document_symlink",
                        f"文档文件是符号链接，拒绝读取和写入：{rel}",
                        path=rel,
                        blocking=True,
                    )
                )
                return
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(root) or not resolved.is_file():
                issues.append(
                    _issue(
                        "unsafe_document_path",
                        f"文档路径越出仓库或不是普通文件：{rel}",
                        path=rel,
                        blocking=True,
                    )
                )
                return
        except (OSError, RuntimeError, ValueError):
            issues.append(
                _issue(
                    "unreadable_document",
                    f"文档不可安全访问：{rel}",
                    path=rel,
                    blocking=True,
                )
            )
            return
        files.append(path)
        seen.add(rel)

    def visit_dir(rel: str, directory: Path) -> None:
        if directory != root:
            git_marker = directory / ".git"
            if git_marker.exists() or git_marker.is_symlink():
                return
        try:
            with os.scandir(directory) as iterator:
                children = sorted(iterator, key=lambda entry: entry.name.casefold())
        except OSError as exc:
            issues.append(
                _issue(
                    "unreadable_directory",
                    f"无法扫描文档目录 {rel}：{exc}",
                    path=rel,
                    blocking=True,
                )
            )
            return
        for child in children:
            prefix = "" if rel == "." else rel
            child_rel = f"{prefix}/{child.name}" if prefix else child.name
            if child.name.startswith("."):
                continue
            if child.name.casefold() in _EXCLUDED_DIRS:
                continue
            try:
                if child.is_symlink():
                    issues.append(
                        _issue(
                            "document_symlink",
                            f"文档范围包含符号链接，拒绝跟随：{child_rel}",
                            path=child_rel,
                            blocking=True,
                        )
                    )
                    continue
                if child.is_dir(follow_symlinks=False):
                    visit_dir(child_rel, Path(child.path))
                elif child.is_file(follow_symlinks=False):
                    add_file(child_rel, Path(child.path))
            except OSError as exc:
                issues.append(
                    _issue(
                        "unreadable_entry",
                        f"无法检查文档范围条目 {child_rel}：{exc}",
                        path=child_rel,
                        blocking=True,
                    )
                )

    for rel, path in entries:
        if path.is_dir():
            visit_dir(rel, path)
        else:
            add_file(rel, path)
    files.sort(key=lambda item: item.relative_to(root).as_posix().casefold())
    return files, issues


def document_files_report(root: Path, paths: list[str] | None = None, *,
                          for_retrieval: bool = False) -> tuple[list[Path], list[dict[str, Any]]]:
    """List authorized files and report omissions without reading outside the scope."""
    supplied_root = Path(root)
    resolved_root = supplied_root.resolve(strict=False)
    entries, scope_issues = _scope_entries(supplied_root, paths)
    files, scan_issues = _scan_entries(resolved_root, entries, for_retrieval=for_retrieval)
    return [supplied_root / item.relative_to(resolved_root) for item in files], [*scope_issues, *scan_issues]


def iter_document_files(root: Path, paths: list[str] | None = None) -> list[Path]:
    """Governance excludes navigation; retrieval opts into a separate read scope."""
    files, issues = document_files_report(root, paths)
    blocking = [item for item in issues if item.get("blocking")]
    if blocking:
        raise ValueError("; ".join(item["message"] for item in blocking))
    return files


def _extract_frontmatter(raw: bytes) -> tuple[dict[str, Any], str, re.Match[str] | None]:
    text = raw.decode("utf-8")
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        if _FRONTMATTER_OPEN_RE.match(text):
            raise ValueError("frontmatter opening delimiter has no closing delimiter")
        return {}, text.removeprefix("\ufeff"), None
    metadata = _load_yaml_mapping(match.group("meta") or "")
    return metadata, text[match.end() :], match


def read_document(path: Path) -> tuple[dict[str, Any], str]:
    """Read frontmatter with strict duplicate-key and mapping validation."""
    metadata, body, _ = _extract_frontmatter(Path(path).read_bytes())
    return metadata, body


def _alias_value(metadata: dict[str, Any], aliases: tuple[str, ...], label: str, path: str) -> tuple[str | None, Any]:
    present = [key for key in aliases if key in metadata]
    if not present:
        return None, None
    values = [metadata[key] for key in present]
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise ValueError(f"critical field {present[0]} must be a non-empty string")
    if any(value != values[0] for value in values[1:]):
        raise _DuplicateCriticalFieldError(f"conflicting critical field aliases for {label}: {', '.join(present)}")
    selected = next((key for key in aliases if key in present), present[0])
    return selected, metadata[selected]


def _guess_title(path: Path, body: str) -> str:
    in_fence: str | None = None
    for line in body.splitlines():
        fence = re.match(r"^\s{0,3}(```+|~~~+)", line)
        if fence:
            mark = fence.group(1)[0]
            if in_fence is None:
                in_fence = mark
            elif in_fence == mark:
                in_fence = None
            continue
        if in_fence is not None:
            continue
        match = _H1_RE.match(line)
        if match:
            title = match.group(1).strip()
            if title:
                return title
    return re.sub(r"[_-]+", " ", path.stem).strip() or path.stem


def _metadata_additions(
    metadata: dict[str, Any],
    body: str,
    path: Path,
    relative_path: str,
    repository_id: str,
) -> tuple[dict[str, Any], list[tuple[str, str]], list[str]]:
    additions: list[tuple[str, str]] = []
    pending: list[str] = []

    id_key, document_id = _alias_value(metadata, _ID_ALIASES, "id", relative_path)
    if id_key is None:
        digest = hashlib.sha256(f"{repository_id}\n{relative_path}".encode("utf-8")).hexdigest()[:16]
        document_id = f"doc-{digest}"
        additions.append(("id", document_id))
    elif id_key != "id":
        additions.append(("id", document_id))

    title_key, title = _alias_value(metadata, _TITLE_ALIASES, "title", relative_path)
    if title_key is None:
        title = _guess_title(path, body)
        additions.append(("title", title))
    elif title_key != "title":
        additions.append(("title", title))

    type_key, doc_type = _alias_value(metadata, _TYPE_ALIASES, "type", relative_path)
    if type_key is None:
        doc_type = "unknown"
        additions.append(("type", doc_type))
        pending.append("type")
    elif type_key != "type":
        additions.append(("type", doc_type))
        if str(doc_type).casefold() == "unknown":
            pending.append("type")
    elif str(doc_type).casefold() == "unknown":
        pending.append("type")

    if "status" in metadata:
        status = metadata["status"]
        if not isinstance(status, str) or not status.strip():
            raise ValueError("critical field status must be a non-empty string")
        if status.casefold() == "draft" or status.casefold() not in {"draft", "active", "superseded", "deprecated", "unknown"}:
            pending.append("status")
    else:
        status = "draft"
        additions.append(("status", status))
        pending.append("status")

    if not any(key in metadata and isinstance(metadata[key], str) and metadata[key].strip() for key in ("owner", "maintainer")):
        pending.append("owner")
    if not any(key in metadata and metadata[key] not in (None, "", []) for key in ("sources", "source")):
        pending.append("sources")

    proposed = dict(metadata)
    for key, value in additions:
        proposed[key] = value
    return proposed, additions, pending


def _yaml_scalar(value: str) -> str:
    # JSON strings are valid YAML scalars and avoid accidental interpretation of
    # titles containing colons, hashes, quotes, or leading YAML punctuation.
    return json.dumps(value, ensure_ascii=False)


def _add_frontmatter(raw: bytes, additions: list[tuple[str, str]]) -> bytes:
    if not additions:
        return raw
    text = raw.decode("utf-8")
    match = _FRONTMATTER_RE.match(text)
    eol = match.group("eol") if match else "\n"
    lines = [f"{key}: {_yaml_scalar(value)}" for key, value in additions]
    if match:
        metadata = match.group("meta") or ""
        before_close = match.group("before_close") or ""
        if not before_close:
            before_close = eol
        separator = "" if not metadata or metadata.endswith(("\n", "\r")) else eol
        inserted = metadata + separator + eol.join(lines)
        after_metadata = match.end("before_close") if match.group("before_close") is not None else match.end("meta")
        rebuilt = (
            text[: match.start("meta")]
            + inserted
            + before_close
            + text[after_metadata:]
        )
        return rebuilt.encode("utf-8")
    prefix = "---" + eol + eol.join(lines) + eol + "---" + eol
    bom = b"\xef\xbb\xbf" if raw.startswith(b"\xef\xbb\xbf") else b""
    return bom + prefix.encode("utf-8") + raw[len(bom):]


def _check_local_links(root: Path, path: Path, relative_path: str, body: str) -> list[dict[str, Any]]:
    text = _FENCE_RE.sub("", body)
    text = _INLINE_CODE_RE.sub("", text)
    issues: list[dict[str, Any]] = []
    parent_rel = PurePosixPath(relative_path).parent.as_posix()
    if parent_rel == ".":
        parent_rel = ""
    for match in _LINK_RE.finditer(text):
        target_text = match.group(1).strip()
        if target_text.startswith("<") and ">" in target_text:
            target_text = target_text[1 : target_text.index(">")]
        else:
            target_text = target_text.split(maxsplit=1)[0].strip("<>") if target_text else ""
        if "\\" in target_text or re.match(r"^[A-Za-z]:", target_text):
            issues.append(
                _issue(
                    "external_reference_unverified",
                    f"外部引用未验证：{target_text}",
                    path=relative_path,
                    severity="warning",
                )
            )
            continue
        try:
            parsed = urlsplit(target_text)
        except ValueError:
            issues.append(
                _issue("invalid_link", f"无法解析链接：{target_text}", path=relative_path, severity="warning")
            )
            continue
        if parsed.scheme or parsed.netloc or not parsed.path:
            continue
        decoded = unquote(parsed.path)
        if "\x00" in decoded or "\\" in decoded or re.match(r"^[A-Za-z]:", decoded):
            issues.append(
                _issue(
                    "external_reference_unverified",
                    f"外部引用未验证：{target_text}",
                    path=relative_path,
                    severity="warning",
                )
            )
            continue
        target_rel = posixpath.normpath(posixpath.join(parent_rel, decoded))
        if target_rel == ".." or target_rel.startswith("../") or target_rel.startswith("/"):
            issues.append(
                _issue(
                    "external_reference_unverified",
                    f"外部引用未验证：{target_text}",
                    path=relative_path,
                    severity="warning",
                )
            )
            continue
        if target_rel in {"", "."}:
            continue
        target_path = root / Path(*PurePosixPath(target_rel).parts)
        if _has_symlink_component(root, target_rel):
            issues.append(
                _issue(
                    "external_reference_unverified",
                    f"外部引用未验证：{target_text}",
                    path=relative_path,
                    severity="warning",
                )
            )
        elif not target_path.exists():
            issues.append(
                _issue(
                    "broken_link",
                    f"本地链接目标不存在：{target_text}",
                    path=relative_path,
                    severity="warning",
                )
            )
    return issues


def _unified_diff(path: str, old: bytes, new: bytes) -> str:
    old_text = old.decode("utf-8", errors="replace").splitlines(keepends=True)
    new_text = new.decode("utf-8", errors="replace").splitlines(keepends=True)
    return "".join(
        difflib.unified_diff(
            old_text,
            new_text,
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm="\n",
        )
    )


def _json_safe(value: Any) -> Any:
    """Convert PyYAML values into strict JSON values without changing source data."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return "base64:" + base64.b64encode(value).decode("ascii")
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, set):
        return sorted((_json_safe(item) for item in value), key=repr)
    return str(value)


def _navigation_content(documents: list[dict[str, Any]]) -> bytes:
    lines = [
        "# 项目文档导航",
        "",
        "<!-- generated-by: team-wiki document governance v1 -->",
        "",
        "本页由 team-wiki 根据项目现有文档生成。文档正文和项目自有导航保持原位。",
        "",
        "## 文档",
        "",
    ]
    for item in documents:
        relative = item["path"]
        target = posixpath.relpath(relative, ".knowledge")
        target = "/".join(quote(part, safe="") for part in target.split("/"))
        title = str(item["metadata"].get("title", Path(relative).stem)).replace("\\", "\\\\").replace("]", "\\]")
        lines.append(
            f"- [{title}]({target}) -- `{item['metadata'].get('id', '')}`; "
            f"type: `{item['metadata'].get('type', 'unknown')}`; "
            f"status: `{item['metadata'].get('status', 'draft')}`"
        )
    pending_lines = [
        f"- `{item['path']}`：尚未确认" + "、".join(item["pending_confirmation"]) + "。"
        for item in documents
        if item["pending_confirmation"]
    ]
    if pending_lines:
        lines.extend(["", "## 待确认", "", *pending_lines])
    return ("\n".join(lines).rstrip() + "\n").encode("utf-8")


def _make_report(
    root: Path,
    paths: list[str] | None,
    apply: bool,
    repository_id: str | None = None,
) -> dict[str, Any]:
    root = root.resolve(strict=False)
    requested_repository_id = repository_id
    issues: list[dict[str, Any]] = []
    config = _read_config(root, issues)
    entries, scope_issues = _scope_entries(root, paths, config_data=config)
    issues.extend(scope_issues)
    document_paths = [rel for rel, _ in entries]
    files, scan_issues = _scan_entries(root, entries)
    issues.extend(scan_issues)
    if requested_repository_id and requested_repository_id.strip():
        repository_id = requested_repository_id.strip()
    elif config is not None and isinstance(config.get("repository_id"), str) and config["repository_id"].strip():
        repository_id = config["repository_id"].strip()
    else:
        repository_id = root.name or "project"

    documents: list[dict[str, Any]] = []
    seen_ids: dict[str, list[str]] = defaultdict(list)
    for path in files:
        relative = path.relative_to(root).as_posix()
        entry: dict[str, Any] = {
            "path": relative,
            "status": "current",
            "metadata": {},
            "pending_confirmation": [],
            "issues": [],
            "diff": "",
        }
        try:
            raw = path.read_bytes()
            metadata, body, _ = _extract_frontmatter(raw)
            proposed, additions, pending = _metadata_additions(
                metadata, body, path, relative, repository_id
            )
            entry["metadata"] = proposed
            entry["pending_confirmation"] = pending
            entry["_original"] = raw
            entry["_hash"] = hashlib.sha256(raw).hexdigest()
            entry["_new"] = _add_frontmatter(raw, additions)
            entry["_additions"] = additions
            for alias_group, label in ((_ID_ALIASES, "id"),):
                present = [key for key in alias_group if key in proposed]
                identity = proposed[present[0]] if present else None
                if identity is not None:
                    if not isinstance(identity, str) or not identity.strip():
                        raise ValueError("critical field id must be a non-empty string")
                    seen_ids[identity].append(relative)
            link_issues = _check_local_links(root, path, relative, body)
            entry["issues"].extend(link_issues)
            issues.extend(link_issues)
        except _DuplicateKeyError as exc:
            issue = _issue(
                "duplicate_key",
                f"frontmatter 含重复 YAML 字段，拒绝写入：{exc.problem or exc}",
                path=relative,
                blocking=True,
            )
            entry["status"] = "blocked"
            entry["issues"].append(issue)
            issues.append(issue)
        except yaml.YAMLError as exc:
            issue = _issue(
                "invalid_yaml",
                f"frontmatter YAML 无法解析，拒绝写入：{exc}",
                path=relative,
                blocking=True,
            )
            entry["status"] = "blocked"
            entry["issues"].append(issue)
            issues.append(issue)
        except _DuplicateCriticalFieldError as exc:
            issue = _issue(
                "duplicate_critical_field",
                f"文档含重复或冲突的关键字段，拒绝写入：{exc}",
                path=relative,
                blocking=True,
            )
            entry["status"] = "blocked"
            entry["issues"].append(issue)
            issues.append(issue)
        except _FrontmatterMappingError as exc:
            issue = _issue(
                "frontmatter_not_mapping",
                f"frontmatter 必须是键值映射，拒绝写入：{exc}",
                path=relative,
                blocking=True,
            )
            entry["status"] = "blocked"
            entry["issues"].append(issue)
            issues.append(issue)
        except (UnicodeError, TypeError, ValueError) as exc:
            issue = _issue(
                "invalid_metadata",
                f"文档元信息无法安全治理：{exc}",
                path=relative,
                blocking=True,
            )
            entry["status"] = "blocked"
            entry["issues"].append(issue)
            issues.append(issue)
        documents.append(entry)

    for identity, relative_paths in seen_ids.items():
        if len(relative_paths) < 2:
            continue
        message = f"文档 ID 重复：{identity}（{', '.join(relative_paths)}）"
        for entry in documents:
            if entry["path"] in relative_paths:
                issue = _issue("duplicate_id", message, path=entry["path"], blocking=True)
                entry["issues"].append(issue)
                entry["status"] = "blocked"
                issues.append(issue)

    for entry in documents:
        for field in entry["pending_confirmation"]:
            warning = _issue(
                f"confirm_{field}",
                f"{entry['path']}：{field} 尚未确认；治理不会自动补造该结论。",
                path=entry["path"],
                severity="warning",
            )
            entry["issues"].append(warning)
            issues.append(warning)

    navigation_path = root / ".knowledge" / "documents.md"
    navigation_rel = ".knowledge/documents.md"
    navigation_new: bytes | None = None
    navigation_old: bytes | None = None
    navigation_hash: str | None = None
    if documents:
        try:
            if navigation_path.is_symlink() or _has_symlink_component(root, navigation_rel):
                issues.append(
                    _issue(
                        "navigation_symlink",
                        "team-wiki 导航路径包含符号链接，拒绝写入。",
                        path=navigation_rel,
                        blocking=True,
                    )
                )
            elif navigation_path.exists():
                navigation_old = navigation_path.read_bytes()
                navigation_hash = hashlib.sha256(navigation_old).hexdigest()
                if b"generated-by: team-wiki document governance v1" not in navigation_old:
                    issues.append(
                        _issue(
                            "navigation_conflict",
                            "目标 team-wiki 导航文件已存在且不含工具所有权标记，拒绝覆盖。",
                            path=navigation_rel,
                            blocking=True,
                        )
                    )
                else:
                    navigation_new = _navigation_content(documents)
            else:
                navigation_new = _navigation_content(documents)
            if navigation_new is not None:
                old = navigation_old or b""
                diff = _unified_diff(navigation_rel, old, navigation_new)
                if diff:
                    documents.append(
                        {
                            "path": navigation_rel,
                            "status": "generated",
                            "metadata": {},
                            "pending_confirmation": [],
                            "issues": [],
                            "diff": diff,
                            "_original": old,
                            "_hash": navigation_hash,
                            "_new": navigation_new,
                            "_generated": True,
                        }
                    )
        except OSError as exc:
            issues.append(
                _issue(
                    "navigation_error",
                    f"无法读取 team-wiki 导航：{exc}",
                    path=navigation_rel,
                    blocking=True,
                )
            )

    proposed_paths: list[str] = []
    candidates: list[dict[str, Any]] = []
    for entry in documents:
        original = entry.get("_original", b"")
        updated = entry.get("_new", original)
        if updated != original:
            proposed_paths.append(entry["path"])
            candidates.append(entry)
            if not entry.get("_generated"):
                entry["status"] = "needs_metadata"
            entry["diff"] = _unified_diff(entry["path"], original, updated)
    blocking = [item for item in issues if item.get("blocking")]
    written_paths: list[str] = []
    if apply and not blocking and candidates:
        prepared: list[tuple[Path, bytes, str | None, dict[str, Any]]] = []
        for entry in candidates:
            target = root / entry["path"]
            old_hash = entry.get("_hash")
            if entry.get("_generated") and old_hash is None:
                if target.exists() or target.is_symlink():
                    issues.append(
                        _issue(
                            "concurrent_modification",
                            f"写入前目标已出现，拒绝覆盖：{entry['path']}",
                            path=entry["path"],
                            blocking=True,
                        )
                    )
                    continue
            else:
                try:
                    current_hash = hashlib.sha256(target.read_bytes()).hexdigest()
                except OSError:
                    current_hash = None
                if current_hash != old_hash:
                    issues.append(
                        _issue(
                            "concurrent_modification",
                            f"文档在预检后发生变化，拒绝写入：{entry['path']}",
                            path=entry["path"],
                            blocking=True,
                        )
                    )
                    continue
            prepared.append((target, entry["_new"], old_hash, entry))
        if not any(item.get("blocking") for item in issues) and len(prepared) == len(candidates):
            staged: list[tuple[Path, Path, bytes, str | None, dict[str, Any]]] = []
            try:
                for target, data, old_hash, entry in prepared:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    fd, temp_name = tempfile.mkstemp(prefix=".team-wiki-doc-", dir=str(target.parent))
                    temp_path = Path(temp_name)
                    try:
                        with os.fdopen(fd, "wb") as stream:
                            stream.write(data)
                            stream.flush()
                            os.fsync(stream.fileno())
                        if target.exists():
                            os.chmod(temp_path, stat.S_IMODE(target.stat().st_mode))
                    except Exception:
                        temp_path.unlink(missing_ok=True)
                        raise
                    staged.append((target, temp_path, data, old_hash, entry))
            except OSError as exc:
                for _, temp_path, _, _, _ in staged:
                    temp_path.unlink(missing_ok=True)
                issues.append(_issue("write_failed", f"无法准备治理文件：{exc}", blocking=True))
            else:
                # Verify the full batch again after staging and immediately before
                # replacing any target, so stale previews never overwrite edits.
                drifted = False
                for target, _, _, old_hash, entry in staged:
                    if _has_symlink_component(root, entry["path"]):
                        drifted = True
                    if entry.get("_generated") and old_hash is None:
                        if target.exists() or target.is_symlink():
                            drifted = True
                    else:
                        try:
                            current_hash = hashlib.sha256(target.read_bytes()).hexdigest()
                        except OSError:
                            current_hash = None
                        if current_hash != old_hash:
                            drifted = True
                    if drifted:
                        issues.append(
                            _issue(
                                "concurrent_modification",
                                f"治理文件在应用前发生变化，整批取消：{entry['path']}",
                                path=entry["path"],
                                blocking=True,
                            )
                        )
                        break
                if drifted:
                    for _, temp_path, _, _, _ in staged:
                        temp_path.unlink(missing_ok=True)
                else:
                    try:
                        for target, temp_path, _, _, entry in staged:
                            os.replace(temp_path, target)
                            written_paths.append(entry["path"])
                            entry["status"] = "applied"
                    except OSError as exc:
                        for _, temp_path, _, _, _ in staged:
                            temp_path.unlink(missing_ok=True)
                        issues.append(
                            _issue(
                                "write_failed",
                                f"应用治理文件时发生错误，已写入路径：{', '.join(written_paths)}；错误：{exc}",
                                blocking=True,
                            )
                        )

    blocking = [item for item in issues if item.get("blocking")]
    errors = [item["message"] for item in issues if item.get("severity") == "error"]
    warnings = [item["message"] for item in issues if item.get("severity") == "warning"]
    file_results: list[dict[str, Any]] = []
    for entry in documents:
        file_results.append(
            {
                key: entry[key]
                for key in ("path", "status", "metadata", "pending_confirmation", "issues", "diff")
            }
        )
        file_results[-1]["metadata"] = _json_safe(file_results[-1]["metadata"])
    return {
        "ok": not blocking and not errors,
        "errors": errors,
        "warnings": warnings,
        "document_paths": document_paths,
        "changed_paths": written_paths if apply else proposed_paths,
        "written_paths": written_paths,
        "files": file_results,
        "issues": issues,
        "counts": {
            "files": sum(1 for item in documents if not item.get("_generated")),
            "changed": len(proposed_paths),
            "written": len(written_paths),
            "issues": len(issues),
            "errors": len(errors),
            "warnings": len(warnings),
            "blocking": len(blocking),
            "pending_confirmation": sum(len(item.get("pending_confirmation", [])) for item in documents),
        },
        "mode": "apply" if apply else "preview",
    }


def govern_documents(
    root: Path,
    paths: list[str] | None = None,
    apply: bool = False,
    repository_id: str | None = None,
) -> dict[str, Any]:
    """Preview or safely apply metadata additions and a dedicated navigation file."""
    return _make_report(Path(root), paths, apply, repository_id=repository_id)


def check_documents(root: Path, paths: list[str] | None = None) -> dict[str, Any]:
    """Return the read-only governance report for integration with doctor checks."""
    return govern_documents(root, paths=paths, apply=False)
