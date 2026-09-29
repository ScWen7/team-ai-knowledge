from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

KIT_VERSION = "0.9.0"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def short_hash(data: bytes, n: int = 8) -> str:
    return hashlib.sha256(data).hexdigest()[:n].upper()


def slugify(value: str) -> str:
    value = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", value).strip("-")
    return value[:48] or "source"


def read_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML must be a mapping: {path}")
    return data


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def parse_frontmatter(path: Path) -> tuple[dict[str, Any], str]:
    from .documents import read_document
    return read_document(path)


def ensure_file(path: Path, content: str) -> None:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def git_info(root: Path) -> dict[str, Any]:
    def run(*args: str) -> str | None:
        try:
            cp = subprocess.run(["git", "-C", str(root), *args], text=True, capture_output=True, check=True)
            return cp.stdout.strip()
        except Exception:
            return None

    status = run("status", "--porcelain")
    return {
        "head": run("rev-parse", "HEAD"),
        "branch": run("rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": bool(status) if status is not None else None,
    }


def init_team(root: Path, repository_id: str | None = None) -> None:
    rid = repository_id or root.name
    for rel in [
        "sources/inbox",
        "sources/evidence",
        "wiki/team-conventions",
        "wiki/technical",
        "wiki/business",
        "wiki/projects",
        "changes/views",
        "changes/reviews",
        ".knowledge/records",
        ".knowledge/runs",
        ".knowledge/cache",
    ]:
        (root / rel).mkdir(parents=True, exist_ok=True)

    ensure_file(
        root / "README.md",
        """# Team Knowledge

- 交资料：`sources/inbox/`
- 看正式知识：`wiki/INDEX.md`
- 看修改和待确认问题：`changes/INDEX.md`

> `wiki/` 中的内容只有在已审核发布分支/快照上才属于正式知识。
""",
    )
    ensure_file(
        root / "AGENTS.md",
        """# Team knowledge workflow

按任务使用 `team-wiki search` 查找知识，核对状态、适用范围和来源后读取正文。未找到时明确说明限制。项目共同底线使用 `team-wiki project-rules` 完整读取，不以检索排名替代。新事实和经验写入所属项目或团队知识库，按既有审核渠道确认；不得把格式通过、搜索命中或采用记录当成业务验证。Work 追溯仅在明确需要时使用。
""",
    )
    ensure_file(
        root / "wiki/PURPOSE.md",
        """# Purpose

## 服务目标
- 让成员和 Agent 找到可追溯的正式知识。
- 让真实工作产生的证据能够修正既有知识。

## 收录边界
- 收录团队约定、跨项目技术知识、业务知识和项目入口。
- 不自动收录个人偏好、密钥和未经授权的受限资料。
""",
    )
    ensure_file(root / "wiki/OVERVIEW.md", "# Overview\n\n尚无已确认领域认识；按实际维护的知识更新本页。\n")
    ensure_file(root / "wiki/INDEX.md", "# Wiki Index\n\n> 由 `team-wiki index` 更新。\n")
    for rel, title in [
        ("team-conventions", "团队约定"),
        ("technical", "技术知识"),
        ("business", "业务知识"),
        ("projects", "项目入口"),
    ]:
        ensure_file(root / "wiki" / rel / "INDEX.md", f"# {title}\n\n暂无条目。\n")
    ensure_file(root / "sources/INDEX.md", "# Sources Index\n\n> 由 `team-wiki index` 更新。\n")
    ensure_file(root / "changes/INDEX.md", "# Changes Index\n\n> 由 `team-wiki index` 更新。\n")
    ensure_file(root / "changes/reviews/INDEX.md", "# Reviews Index\n\n> 由 `team-wiki index` 更新。\n")
    for name, title in [
        ("open.md", "Open Changes"),
        ("blocked.md", "Blocked Changes"),
        ("recently-published.md", "Recently Published"),
    ]:
        ensure_file(root / "changes/views" / name, f"# {title}\n\n暂无。\n")

    cfg = root / ".knowledge/config.yml"
    if not cfg.exists():
        write_yaml(
            cfg,
            {
                "version": 1,
                "repository_id": rid,
                "profile": "team",
                "language": "zh-CN",
                "paths": {
                    "knowledge": "wiki",
                    "sources": "sources",
                    "changes": "changes",
                    "reviews": "changes/reviews",
                    "shared_records": ".knowledge/records",
                    "local_runs": ".knowledge/runs",
                    "cache": ".knowledge/cache",
                },
                "knowledge_sources": [],
            },
        )
    ensure_file(root / ".knowledge/local.yml", "# 本机私有路径映射，不提交\nrepositories: {}\n")
    ensure_file(
        root / ".gitignore",
        ".knowledge/local.yml\n.knowledge/runs/\n.knowledge/cache/\n.venv/\n__pycache__/\n*.pyc\n",
    )


def _find_source_package(root: Path, source_id: str) -> Path | None:
    for meta in (root / "sources").rglob("source.yml"):
        try:
            data = read_yaml(meta)
        except Exception:
            continue
        if data.get("source_id") == source_id:
            return meta.parent
    return None


def register_source(
    root: Path,
    file_path: Path,
    title: str | None = None,
    move: bool = False,
    *,
    connector_id: str = "manual",
    upstream_id: str | None = None,
    logical_path: str | None = None,
) -> Path:
    data = file_path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if upstream_id:
        identity_key = f"{connector_id}::{upstream_id}".encode()
        source_id = f"SRC-{short_hash(identity_key, 10)}"
        identity_mode = "upstream"
    else:
        source_id = f"SRC-{short_hash(data)}"
        identity_mode = "content-fallback"

    existing = _find_source_package(root, source_id)
    if existing is not None:
        meta = read_yaml(existing / "source.yml")
        if meta.get("content_sha256") == digest:
            return existing
        raise ValueError(
            f"source {source_id} already exists with different content; use refresh-source"
        )

    now = datetime.now()
    source_title = title or file_path.stem
    pkg = root / "sources" / f"{now.year:04d}" / f"{now.month:02d}" / f"{source_id}-{slugify(source_title)}"
    pkg.mkdir(parents=True, exist_ok=True)
    dest = pkg / file_path.name
    if dest.exists() and dest.read_bytes() != data:
        raise ValueError(f"source collision: {dest}")
    if not dest.exists():
        shutil.move(str(file_path), dest) if move else shutil.copy2(file_path, dest)

    write_yaml(
        pkg / "source.yml",
        {
            "source_id": source_id,
            "title": source_title,
            "registered_at": utc_now(),
            "content_sha256": digest,
            "original_name": file_path.name,
            "status": "registered",
            "visibility": "team",
            "origin": {
                "identity_mode": identity_mode,
                "connector_id": connector_id,
                "upstream_id": upstream_id,
                "logical_path": logical_path,
            },
            "linked_changes": [],
            "revisions": [],
        },
    )
    return pkg


def iter_knowledge_files(root: Path) -> list[Path]:
    config_path = root / ".knowledge/config.yml"
    if config_path.is_file() and read_yaml(config_path).get("profile") == "project":
        from .documents import iter_document_files
        return iter_document_files(root)
    base = root / "wiki"
    if not base.exists():
        return []
    skip = {"INDEX.md", "PURPOSE.md", "OVERVIEW.md"}
    return sorted(p for p in base.rglob("*.md") if p.name not in skip
                  and not p.is_symlink() and p.resolve().is_relative_to(root.resolve())
                  and not any(part.startswith(".") for part in p.relative_to(base).parts))


def iter_changes(root: Path) -> list[Path]:
    base = root / "changes"
    return [p for p in base.rglob("CHG-*.md")] if base.exists() else []


def index_workspace(root: Path) -> None:
    config_path = root / ".knowledge/config.yml"
    if config_path.is_file() and read_yaml(config_path).get("profile") == "project":
        # File search needs no index build. Check the existing project scope
        # without replacing its navigation or adding metadata to its documents.
        from .documents import govern_documents
        report = govern_documents(root)
        if not report["ok"]:
            raise ValueError("; ".join(report["errors"]))
        return
    lines = ["# Wiki Index", "", "> 正式知识导航；正文是否正式以当前发布分支/快照为准。", ""]
    for rel, label in [
        ("team-conventions", "团队约定"),
        ("technical", "技术知识"),
        ("business", "业务知识"),
        ("projects", "项目入口"),
    ]:
        d = root / "wiki" / rel
        count = len([p for p in d.rglob("*.md") if p.name != "INDEX.md"]) if d.exists() else 0
        lines.append(f"- [{label}]({rel}/INDEX.md) — {count} 个正文/概览文件")
    (root / "wiki/INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    for idx in (root / "wiki").rglob("INDEX.md"):
        if idx == root / "wiki/INDEX.md":
            continue
        rows = []
        for child in sorted(idx.parent.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if child.name.startswith(".") or child.name == "INDEX.md":
                continue
            if child.is_dir():
                rows.append(
                    f"- 📁 [{child.name}]({child.name}/INDEX.md)"
                    if (child / "INDEX.md").exists()
                    else f"- 📁 {child.name}/"
                )
            elif child.suffix == ".md":
                meta, body = parse_frontmatter(child)
                title = meta.get("title") or next(
                    (x[2:].strip() for x in body.splitlines() if x.startswith("# ")),
                    child.stem,
                )
                rows.append(f"- [{title}]({child.name}) — `{meta.get('status', 'unclassified')}`")
        idx.write_text(
            f"# {idx.parent.name}\n\n" + ("\n".join(rows) if rows else "暂无条目。") + "\n",
            encoding="utf-8",
        )

    src_rows = []
    for meta in sorted((root / "sources").rglob("source.yml")):
        data = read_yaml(meta)
        rel = meta.parent.relative_to(root / "sources")
        origin = data.get("origin") or {}
        logical_path = origin.get("logical_path") if isinstance(origin, dict) else None
        connector = origin.get("connector_id") if isinstance(origin, dict) else None
        details = []
        if connector:
            details.append(f"connector={connector}")
        if logical_path:
            details.append(f"path={logical_path}")
        suffix_text = f" — {'; '.join(details)}" if details else ""
        src_rows.append(
            f"- `{data.get('source_id','?')}` {data.get('title','')} — "
            f"`{data.get('status','?')}` — `{rel}`{suffix_text}"
        )
    (root / "sources/INDEX.md").write_text(
        "# Sources Index\n\n" + ("\n".join(src_rows) if src_rows else "暂无已登记来源。") + "\n",
        encoding="utf-8",
    )

    rows, opened, blocked, published = [], [], [], []
    for p in sorted(iter_changes(root)):
        meta, _ = parse_frontmatter(p)
        rel = p.relative_to(root / "changes")
        stage = meta.get("stage", "unknown")
        row = (
            f"- `{meta.get('change_id', p.stem)}` "
            f"[{meta.get('title', p.stem)}]({rel.as_posix()}) — `{stage}`"
        )
        rows.append(row)
        if stage in {"collecting", "proposed", "ready"}:
            opened.append(row)
        if stage == "blocked":
            blocked.append(row)
        if stage == "published":
            published.append(row)
    (root / "changes/INDEX.md").write_text(
        "# Changes Index\n\n" + ("\n".join(rows) if rows else "暂无变更记录。") + "\n",
        encoding="utf-8",
    )
    (root / "changes/views/open.md").write_text(
        "# Open Changes\n\n" + ("\n".join(opened) if opened else "暂无。") + "\n",
        encoding="utf-8",
    )
    (root / "changes/views/blocked.md").write_text(
        "# Blocked Changes\n\n" + ("\n".join(blocked) if blocked else "暂无。") + "\n",
        encoding="utf-8",
    )
    (root / "changes/views/recently-published.md").write_text(
        "# Recently Published\n\n" + ("\n".join(published[-20:]) if published else "暂无。") + "\n",
        encoding="utf-8",
    )

    try:
        from .review import list_reviews
        review_rows = []
        for item in list_reviews(root):
            review_path = Path(item["path"])
            rel = review_path.relative_to("changes/reviews")
            review_rows.append(
                f"- `{item['review_id']}` "
                f"[{item['title']}]({rel.as_posix()}) "
                f"— `{item['state']}` — {item.get('owner') or 'unassigned'}"
            )
        (root / "changes/reviews/INDEX.md").write_text(
            "# Reviews Index\n\n" + ("\n".join(review_rows) if review_rows else "暂无 Review。") + "\n",
            encoding="utf-8",
        )
    except Exception:
        pass


def create_change(root: Path, title: str, owner: str = "unassigned") -> Path:
    now = datetime.now()
    cid = f"CHG-{short_hash((title + '|' + utc_now()).encode())}"
    path = root / "changes" / f"{now.year:04d}" / f"{now.month:02d}" / f"{cid}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "change_id": cid,
        "title": title,
        "stage": "collecting",
        "owner": owner,
        "created": utc_now(),
        "origin": {"work_ids": [], "source_ids": []},
        "affected": [],
        "evidence_ids": [],
        "review_ids": [],
        "publication": None,
    }
    body = "\n".join(
        [
            "---",
            yaml.safe_dump(meta, allow_unicode=True, sort_keys=False).rstrip(),
            "---",
            "",
            f"# {title}",
            "",
            "## 起因与新旧差异",
            "",
            "待补充。",
            "",
            "## 证据",
            "",
            "待补充。",
            "",
            "## 影响与未决问题",
            "",
            "待补充。",
            "",
        ]
    )
    path.write_text(body, encoding="utf-8")
    return path


def prepare_work(root: Path, goal: str, consumer_id: str | None = None) -> Path:
    runs = root / ".knowledge/runs"
    runs.mkdir(parents=True, exist_ok=True)
    config = read_yaml(root / ".knowledge/config.yml")
    consumer = consumer_id or config.get("repository_id") or "unknown"
    wid = f"W-{short_hash((goal + '|' + str(consumer) + '|' + utc_now()).encode())}"
    path = runs / f"{wid}.yml"
    write_yaml(
        path,
        {
            "work_id": wid,
            "goal": goal,
            "consumer_id": consumer,
            "state": "active",
            "created": utc_now(),
            "kit_version": KIT_VERSION,
            "git": git_info(root),
            "adopted": [],
            "changes": [],
        },
    )
    return path


LATIN_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
QUERY_PUNCT_RE = re.compile(r"[\s，。、；：？！,.;:?!()（）\[\]【】\"'“”‘’/\\|~`@#$%^&*+=<>~-]+")
FIELD_WEIGHTS = {"title": 6, "summary": 3, "tags": 4, "body": 1}


def _cjk_ngrams(text: str, sizes: tuple[int, ...] = (2, 3)) -> list[str]:
    """Character n-grams for CJK runs.

    Chinese has no spaces, so whitespace tokenisation turns a whole question
    into a single term and never matches any body text. Character bigrams
    bridge that gap without a dictionary or a model: "手机号能不能为空" shares
    手机号 / 必填-style substrings with a rule that says 手机号为必填项.
    """
    grams: list[str] = []
    for match in re.finditer(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]+", text):
        run = match.group(0)
        for size in sizes:
            if len(run) < size:
                continue
            grams.extend(run[i : i + size] for i in range(len(run) - size + 1))
    return grams


def tokenize_query(query: str) -> list[str]:
    """Split a query into comparable terms.

    Latin/digit runs stay whole words (so ``idempotent`` still matches
    ``idempotent``), CJK runs become character n-grams, and the original
    whitespace-separated terms are kept so an exact phrase still scores.
    """
    cleaned = QUERY_PUNCT_RE.sub(" ", query.strip().lower())
    terms: list[str] = []
    for chunk in cleaned.split():
        terms.append(chunk)
        for match in LATIN_TOKEN_RE.finditer(chunk):
            terms.append(match.group(0))
        terms.extend(_cjk_ngrams(chunk))
    return [t for t in dict.fromkeys(terms) if t]


def _knowledge_fields(meta: dict[str, Any], body: str) -> dict[str, str]:
    return {
        "title": str(meta.get("title", "")),
        "summary": str(meta.get("summary", "")),
        "tags": " ".join(map(str, meta.get("tags", []) or [])),
        "body": body,
    }


def search(root: Path, query: str, *, statuses: list[str] | None = None,
           scope: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
    """Explore documents with explicit status; required rules use project-rules."""
    from .retrieval import search_knowledge
    return search_knowledge(root, query, statuses=statuses, scope=scope, limit=limit)


def search_report(root: Path, query: str, *, statuses: list[str] | None = None,
                  scope: str | None = None, limit: int | None = None
                  ) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Like search, but also returns files skipped as unreadable or ambiguous."""
    from .retrieval import search_knowledge_report
    return search_knowledge_report(root, query, statuses=statuses, scope=scope, limit=limit)


@dataclass
class CheckResult:
    ok: bool
    errors: list[str]
    warnings: list[str]


def doctor(root: Path) -> CheckResult:
    errors, warnings = [], []
    config_path = root / ".knowledge/config.yml"
    if config_path.is_file():
        try:
            config = read_yaml(config_path)
            if config.get("profile") == "project":
                from .documents import govern_documents
                report = govern_documents(root)
                if not config.get("repository_id"):
                    report["errors"].append("config repository_id is required")
                return CheckResult(not report["errors"], report["errors"], report["warnings"])
        except (ValueError, yaml.YAMLError) as exc:
            return CheckResult(False, [str(exc)], [])
    for rel in [
        "README.md",
        "sources/INDEX.md",
        "wiki/INDEX.md",
        "wiki/PURPOSE.md",
        "wiki/OVERVIEW.md",
        "changes/INDEX.md",
        ".knowledge/config.yml",
    ]:
        if not (root / rel).exists():
            errors.append(f"missing required path: {rel}")
    cfg = root / ".knowledge/config.yml"
    if cfg.exists():
        try:
            data = read_yaml(cfg)
            if data.get("profile") not in {"team", "project"}:
                errors.append("config profile must be team or project")
            if not data.get("repository_id"):
                errors.append("config repository_id is required")
        except Exception as exc:
            errors.append(f"invalid config.yml: {exc}")

    ids = {}
    for path in iter_knowledge_files(root):
        try:
            meta, _ = parse_frontmatter(path)
        except Exception as exc:
            errors.append(f"cannot parse {path.relative_to(root)}: {exc}")
            continue
        if not meta:
            warnings.append(f"knowledge file without frontmatter: {path.relative_to(root)}")
            continue
        kid = meta.get("id")
        if not isinstance(kid, str) or not kid.strip():
            errors.append(f"knowledge file missing id: {path.relative_to(root)}")
        elif kid in ids:
            errors.append(
                f"duplicate knowledge id {kid}: {ids[kid]} and {path.relative_to(root)}"
            )
        else:
            ids[kid] = str(path.relative_to(root))
        if meta.get("status") not in {"draft", "active", "superseded", "deprecated"}:
            warnings.append(
                f"unrecognized status in {path.relative_to(root)}: {meta.get('status')}"
            )

    source_iter = (root / "sources").rglob("source.yml") if (root / "sources").exists() else []
    for meta_path in source_iter:
        try:
            data = read_yaml(meta_path)
            if not data.get("source_id"):
                errors.append(
                    f"source package missing source_id: {meta_path.relative_to(root)}"
                )
            if data.get("original_name") and not (
                meta_path.parent / data["original_name"]
            ).exists():
                warnings.append(
                    f"source original file missing: "
                    f"{meta_path.parent.relative_to(root)}/{data['original_name']}"
                )
        except Exception as exc:
            errors.append(
                f"invalid source package {meta_path.relative_to(root)}: {exc}"
            )

    if (root / "wiki").exists():
        for directory in [x for x in (root / "wiki").rglob("*") if x.is_dir()]:
            count = len(
                [
                    p
                    for p in directory.glob("*.md")
                    if p.name not in {"INDEX.md", "PURPOSE.md", "OVERVIEW.md"}
                ]
            )
            if count >= 40:
                warnings.append(
                    f"growth signal: {directory.relative_to(root)} has {count} "
                    "direct knowledge files; review topic split/navigation"
                )
    inbox = root / "sources/inbox"
    if inbox.exists() and len([p for p in inbox.iterdir() if p.is_file()]) > 20:
        warnings.append("inbox backlog exceeds 20 files")
    try:
        from .review import list_reviews
        for item in list_reviews(root):
            if item.get("state") not in {"open", "in-progress", "blocked", "resolved", "dismissed"}:
                errors.append(f"invalid review state: {item.get('review_id')}={item.get('state')}")
    except Exception as exc:
        warnings.append(f"cannot inspect review records: {exc}")
    return CheckResult(not errors, errors, warnings)


# --- V0.2: normalized knowledge graph + work/evidence loop ---

def knowledge_ref(root: Path, knowledge_id: str) -> tuple[Path, dict[str, Any], str]:
    for path in iter_knowledge_files(root):
        meta, _ = parse_frontmatter(path)
        if meta.get("id") == knowledge_id:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            return path, meta, digest
    raise KeyError(f"knowledge id not found: {knowledge_id}")


def related(root: Path, knowledge_id: str, limit: int = 5, *,
            statuses: list[str] | None = None, scope: str | None = None) -> list[dict[str, Any]]:
    """Return current explicit links and reverse links, without inferred affinity."""
    from .retrieval import related_knowledge
    return related_knowledge(root, knowledge_id, limit, statuses=statuses, scope=scope)


def context_budget(max_context_size: int | None) -> dict[str, Any]:
    """Legacy character-budget estimate; does not inspect or truncate a session."""
    size = max_context_size if max_context_size is not None else 204800
    if size <= 0:
        raise ValueError("max context size must be positive")
    pages = int(size * 0.5)
    return {"maxCtx": size, "responseReserve": int(size * 0.15),
            "indexBudget": int(size * 0.05), "pageBudget": pages,
            "maxPageSize": min(pages, max(5000, int(pages * 0.3))),
            "unit": "characters", "applied": False}


def context_plan(root: Path, query: str, max_context_size: int | None = None,
                 limit: int = 5, *, statuses: list[str] | None = None,
                 scope: str | None = None) -> dict[str, Any]:
    from .retrieval import context_knowledge
    plan = context_knowledge(root, query, limit, statuses=statuses, scope=scope)
    return {
        "budget": context_budget(max_context_size),
        "direct": plan["direct"],
        "related": plan["related"],
        "issues": plan["issues"],
        "complete": False,
        "note": "检索计划尚未读取或裁切正文；状态不代表审批。项目共同底线请使用 project-rules 完整读取。",
    }


def _work_path(root: Path, work_id: str) -> Path:
    path = root / ".knowledge/runs" / f"{work_id}.yml"
    if not path.exists():
        raise KeyError(f"work id not found: {work_id}")
    return path


def adopt_knowledge(root: Path, work_id: str, knowledge_id: str, used_for: str) -> dict[str, Any]:
    from .publication import latest_publication_for

    path = _work_path(root, work_id)
    work = read_yaml(path)
    kpath, meta, digest = knowledge_ref(root, knowledge_id)
    publication = latest_publication_for(root, knowledge_id)
    publication_matches = bool(
        publication and publication.get("content_sha256") == digest
    )

    adopted = work.setdefault("adopted", [])
    entry = next((x for x in adopted if x.get("knowledge_id") == knowledge_id), None)
    if entry is None:
        entry = {
            "repository_id": read_yaml(root / ".knowledge/config.yml").get("repository_id"),
            "knowledge_id": knowledge_id,
            "path": str(kpath.relative_to(root)),
            "content_sha256": digest,
            "status_at_use": meta.get("status"),
            "used_for": used_for,
            "outcome": "not-verified",
            "evidence_ids": [],
            "observations": [],
            "publication_id": publication.get("publication_id") if publication_matches else None,
            "published_ref": publication.get("published_ref") if publication_matches else None,
            "adoption_requirement": publication.get("adoption_requirement") if publication_matches else None,
            "latest_publication_id": publication.get("publication_id") if publication else None,
            "publication_match": publication_matches,
        }
        adopted.append(entry)
    else:
        entry["used_for"] = used_for
    write_yaml(path, work)
    return entry


def record_evidence(root: Path, work_id: str, kind: str, locator: str, summary: str) -> Path:
    _work_path(root, work_id)
    eid = f"E-{short_hash((work_id + '|' + kind + '|' + locator + '|' + summary).encode())}"
    path = root / ".knowledge/records/evidence" / f"{eid}.yml"
    if not path.exists():
        write_yaml(path, {
            "evidence_id": eid,
            "work_id": work_id,
            "kind": kind,
            "locator": locator,
            "summary": summary,
            "created": utc_now(),
        })
    work_path = _work_path(root, work_id)
    work = read_yaml(work_path)
    evidence = work.setdefault("evidence_ids", [])
    if eid not in evidence:
        evidence.append(eid)
        write_yaml(work_path, work)
    return path


ALLOWED_OUTCOMES = {"not-verified", "supported-in-scope", "boundary-found", "contradicted", "not-applicable"}


def observe_knowledge(root: Path, work_id: str, knowledge_id: str, outcome: str, note: str, evidence_ids: list[str] | None = None) -> dict[str, Any]:
    if outcome not in ALLOWED_OUTCOMES:
        raise ValueError(f"invalid outcome: {outcome}")
    path = _work_path(root, work_id)
    work = read_yaml(path)
    entry = next((x for x in work.get("adopted", []) if x.get("knowledge_id") == knowledge_id), None)
    if entry is None:
        raise ValueError(f"knowledge {knowledge_id} was not adopted in {work_id}")
    ids = list(dict.fromkeys(evidence_ids or []))
    records = root / ".knowledge/records/evidence"
    for eid in ids:
        if not (records / f"{eid}.yml").exists():
            raise ValueError(f"evidence id not found: {eid}")
    entry["outcome"] = outcome
    entry["evidence_ids"] = list(dict.fromkeys([*(entry.get("evidence_ids") or []), *ids]))
    entry.setdefault("observations", []).append({"at": utc_now(), "outcome": outcome, "note": note, "evidence_ids": ids})
    write_yaml(path, work)
    return entry


def _rewrite_change_meta(path: Path, updates: dict[str, Any]) -> None:
    meta, body = parse_frontmatter(path)
    meta.update(updates)
    path.write_text("---\n" + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False).rstrip() + "\n---\n" + body, encoding="utf-8")


def finalize_work(root: Path, work_id: str, owner: str = "unassigned") -> dict[str, Any]:
    path = _work_path(root, work_id)
    work = read_yaml(path)
    created: list[str] = []
    for item in work.get("adopted", []) or []:
        if item.get("outcome") not in {"boundary-found", "contradicted"}:
            continue
        kid = item["knowledge_id"]
        title = f"复核知识 {kid}: {item.get('outcome')}"
        change = create_change(root, title, owner)
        change_meta, _ = parse_frontmatter(change)
        _rewrite_change_meta(change, {
            "origin": {"work_ids": [work_id], "source_ids": []},
            "affected": [{
                "repository_id": item.get("repository_id"),
                "knowledge_id": kid,
                "content_sha256": item.get("content_sha256"),
            }],
            "evidence_ids": item.get("evidence_ids", []),
        })
        created.append(change_meta["change_id"])
    work["state"] = "finalized"
    work["finalized"] = utc_now()
    work["changes"] = list(dict.fromkeys([*(work.get("changes") or []), *created]))
    write_yaml(path, work)

    from .publication import record_work_adoptions
    adoption_paths = record_work_adoptions(root, work)

    index_workspace(root)
    return {
        "work_id": work_id,
        "changes": created,
        "adoption_ids": [p.stem for p in adoption_paths],
        "state": work["state"],
    }
