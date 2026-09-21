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

KIT_VERSION = "0.7.0"
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def short_hash(data: bytes, n: int = 8) -> str:
    return hashlib.sha256(data).hexdigest()[:n].upper()


def slugify(value: str) -> str:
    value = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", value).strip("-")
    return value[:48] or "source"


def read_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def parse_frontmatter(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    return yaml.safe_load(match.group(1)) or {}, text[match.end():]


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
        ".agents/skills/team-wiki",
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

先准备知识依据，按需读取；只有真正影响产出的知识才记录为 adopted；持久新证据进入知识变更；不得把搜索命中当作采用，也不得把未执行检查写成通过。
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
    ensure_file(root / "wiki/OVERVIEW.md", "# Overview\n\n当前为 V0.1 空知识库，尚无已确认领域认识。\n")
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
    ensure_file(root / "changes/reviews/INDEX.md", "# Reviews Index\\n\\n> 由 `team-wiki index` 更新。\\n")
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
    base = root / "wiki"
    if not base.exists():
        return []
    skip = {"INDEX.md", "PURPOSE.md", "OVERVIEW.md"}
    return [p for p in base.rglob("*.md") if p.name not in skip]


def iter_changes(root: Path) -> list[Path]:
    base = root / "changes"
    return [p for p in base.rglob("CHG-*.md")] if base.exists() else []


def index_workspace(root: Path) -> None:
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
            "# Reviews Index\\n\\n" + ("\\n".join(review_rows) if review_rows else "暂无 Review。") + "\\n",
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


def search(root: Path, query: str) -> list[dict[str, Any]]:
    terms = [x.lower() for x in re.split(r"\s+", query.strip()) if x]
    results = []
    for path in iter_knowledge_files(root):
        meta, body = parse_frontmatter(path)
        hay = " ".join(
            [
                str(meta.get("title", "")),
                str(meta.get("summary", "")),
                " ".join(map(str, meta.get("tags", []) or [])),
                body,
            ]
        ).lower()
        score = sum(hay.count(t) for t in terms)
        if score:
            results.append(
                {
                    "score": score,
                    "id": meta.get("id"),
                    "title": meta.get("title") or path.stem,
                    "status": meta.get("status", "unclassified"),
                    "path": str(path.relative_to(root)),
                }
            )
    return sorted(results, key=lambda x: (-x["score"], x["path"]))


@dataclass
class CheckResult:
    ok: bool
    errors: list[str]
    warnings: list[str]


def doctor(root: Path) -> CheckResult:
    errors, warnings = [], []
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
        if not kid:
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
        from .node_core import available as node_core_available
        if not node_core_available():
            warnings.append("Node.js knowledge-core unavailable: relation/context-budget features are disabled")
    except Exception as exc:
        warnings.append(f"cannot inspect Node.js knowledge-core: {exc}")
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


def build_relationship_nodes(root: Path) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    raw_out: dict[str, set[str]] = {}
    metas: dict[str, dict[str, Any]] = {}
    paths: dict[str, Path] = {}
    for path in iter_knowledge_files(root):
        meta, _ = parse_frontmatter(path)
        kid = meta.get("id")
        if not kid:
            continue
        kid = str(kid)
        metas[kid] = meta
        paths[kid] = path
        links: set[str] = set()
        for item in meta.get("related", []) or []:
            if isinstance(item, str):
                links.add(item)
            elif isinstance(item, dict) and item.get("id"):
                links.add(str(item["id"]))
        for item in meta.get("references", []) or []:
            if isinstance(item, dict) and item.get("id") and item.get("relation") in {"related", "related_to", "depends_on", "supersedes"}:
                links.add(str(item["id"]))
        raw_out[kid] = links

    incoming: dict[str, set[str]] = {kid: set() for kid in metas}
    for src, targets in raw_out.items():
        for target in targets:
            if target in incoming and target != src:
                incoming[target].add(src)

    for kid, meta in metas.items():
        sources: list[str] = []
        for item in meta.get("source_paths", []) or []:
            sources.append(str(item))
        for item in meta.get("evidence", []) or []:
            if isinstance(item, str):
                sources.append(item)
            elif isinstance(item, dict):
                sid = item.get("source_id") or item.get("id")
                if sid:
                    sources.append(str(sid))
        nodes.append({
            "id": kid,
            "title": meta.get("title") or paths[kid].stem,
            "type": str(meta.get("type", "other")),
            "path": str(paths[kid].relative_to(root)),
            "sources": sorted(set(sources)),
            "outLinks": sorted(t for t in raw_out.get(kid, set()) if t in metas and t != kid),
            "inLinks": sorted(incoming.get(kid, set())),
        })
    return nodes


def related(root: Path, knowledge_id: str, limit: int = 5) -> list[dict[str, Any]]:
    from .node_core import related_nodes
    rows = related_nodes(knowledge_id, build_relationship_nodes(root), limit)
    return [
        {
            "id": row["node"]["id"],
            "title": row["node"]["title"],
            "path": row["node"]["path"],
            "relevance": row["relevance"],
        }
        for row in rows
    ]


def context_plan(root: Path, query: str, max_context_size: int | None = None, limit: int = 5) -> dict[str, Any]:
    from .node_core import context_budget
    direct = search(root, query)[:limit]
    related_rows: dict[str, list[dict[str, Any]]] = {}
    for row in direct[:2]:
        if row.get("id"):
            related_rows[str(row["id"])] = related(root, str(row["id"]), limit=3)
    return {
        "budget": context_budget(max_context_size),
        "direct": direct,
        "related": related_rows,
        "complete": False,
        "note": "V0.2 returns a retrieval plan; the current Agent decides what to read and cite.",
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
