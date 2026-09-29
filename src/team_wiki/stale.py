"""Stale knowledge report for doctor.

Detects three classes of knowledge rot that the deterministic toolkit can find
without external services:

- zero-adoption Publications: 发布后长时间没有任何 Work adopt
- stale active knowledge:    长期未修改且仍标 active
- long-lived draft:          draft 状态保持过久

These are surfaced through ``team-wiki doctor --report stale`` as warnings so
repository owners can decide whether to deprecate, refresh, or re-adopt.

All computation is local: we only scan ``.knowledge/records/`` and knowledge
frontmatter. No network, no central server.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .core import iter_knowledge_files, parse_frontmatter, read_yaml


DEFAULTS = {
    "zero_adoption_days": 90,
    "stale_active_days": 180,
    "draft_days": 60,
}


@dataclass
class StaleReport:
    zero_adoption_publications: list[dict[str, Any]] = field(default_factory=list)
    stale_active_knowledge: list[dict[str, Any]] = field(default_factory=list)
    long_lived_drafts: list[dict[str, Any]] = field(default_factory=list)

    @property
    def total(self) -> int:
        return (
            len(self.zero_adoption_publications)
            + len(self.stale_active_knowledge)
            + len(self.long_lived_drafts)
        )


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _age_days(now: datetime, then: datetime | None) -> int | None:
    if then is None:
        return None
    return max(0, (now - then).days)


def _knowledge_last_touched(root: Path, path: Path) -> datetime | None:
    """Latest known modification time for a knowledge file.

    Preference order:
    1. frontmatter ``updated_at`` / ``modified_at``
    2. git log -1 for the file (if in a repo)
    3. file system mtime
    """
    meta, _ = parse_frontmatter(path)
    for key in ("updated_at", "modified_at", "created_at"):
        dt = _parse_iso(meta.get(key))
        if dt:
            return dt
    try:
        import subprocess

        cp = subprocess.run(
            ["git", "-C", str(root), "log", "-1", "--format=%cI", "--", str(path.relative_to(root))],
            capture_output=True,
            text=True,
            check=False,
        )
        if cp.returncode == 0 and cp.stdout.strip():
            return _parse_iso(cp.stdout.strip())
    except Exception:
        pass
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return None


def _publication_records(root: Path) -> list[dict[str, Any]]:
    base = root / ".knowledge/records/publications"
    if not base.exists():
        return []
    rows = []
    for path in sorted(base.glob("PUB-*.yml")):
        data = read_yaml(path)
        data["_record_path"] = str(path.relative_to(root))
        rows.append(data)
    return rows


def _adoption_records(root: Path) -> list[dict[str, Any]]:
    base = root / ".knowledge/records/adoptions"
    if not base.exists():
        return []
    rows = []
    for path in sorted(base.glob("ADOPT-*.yml")):
        data = read_yaml(path)
        rows.append(data)
    return rows


def build_stale_report(
    root: Path,
    *,
    now: datetime | None = None,
    zero_adoption_days: int = DEFAULTS["zero_adoption_days"],
    stale_active_days: int = DEFAULTS["stale_active_days"],
    draft_days: int = DEFAULTS["draft_days"],
) -> StaleReport:
    """Compute stale-knowledge signals for the repository.

    Only reports; never mutates.
    """
    now = now or datetime.now(timezone.utc)
    report = StaleReport()

    # 1. zero-adoption Publications
    publications = _publication_records(root)
    adoptions = _adoption_records(root)
    adopted_pub_ids = {str(a.get("publication_id")) for a in adoptions if a.get("publication_id")}
    for pub in publications:
        pub_id = str(pub.get("publication_id"))
        published_at = _parse_iso(pub.get("published_at"))
        age = _age_days(now, published_at)
        if age is None or age < zero_adoption_days:
            continue
        if pub_id in adopted_pub_ids:
            continue
        report.zero_adoption_publications.append(
            {
                "publication_id": pub_id,
                "knowledge_id": pub.get("knowledge_id"),
                "published_at": pub.get("published_at"),
                "age_days": age,
                "record": pub.get("_record_path"),
            }
        )

    # 2 / 3. per-knowledge checks
    for path in iter_knowledge_files(root):
        meta, _ = parse_frontmatter(path)
        kid = meta.get("id")
        status = str(meta.get("status", "")).lower()
        rel = str(path.relative_to(root))
        last_touched = _knowledge_last_touched(root, path)
        age = _age_days(now, last_touched)

        if status == "active" and age is not None and age >= stale_active_days:
            report.stale_active_knowledge.append(
                {
                    "knowledge_id": kid,
                    "path": rel,
                    "status": status,
                    "last_touched": last_touched.isoformat() if last_touched else None,
                    "age_days": age,
                }
            )
        elif status == "draft" and age is not None and age >= draft_days:
            report.long_lived_drafts.append(
                {
                    "knowledge_id": kid,
                    "path": rel,
                    "status": status,
                    "last_touched": last_touched.isoformat() if last_touched else None,
                    "age_days": age,
                }
            )

    return report


def format_stale_report(report: StaleReport) -> str:
    """Human-readable rendering for ``doctor --report stale``."""
    lines: list[str] = ["# Stale Knowledge Report", ""]
    if report.total == 0:
        lines.append("✅ 未发现知识老化信号。")
        return "\n".join(lines)

    if report.zero_adoption_publications:
        lines.append(f"## 零 Adoption Publication（{len(report.zero_adoption_publications)}）")
        lines.append("")
        lines.append("以下 Publication 发布后长期未被任何 Work adopt，建议检查是否仍适用或标记 deprecated：")
        lines.append("")
        for row in report.zero_adoption_publications:
            lines.append(
                f"- `{row['knowledge_id']}` @ `{row['publication_id']}` "
                f"发布于 {row['published_at']}（{row['age_days']} 天前）"
            )
        lines.append("")

    if report.stale_active_knowledge:
        lines.append(f"## 长期未更新的 Active 知识（{len(report.stale_active_knowledge)}）")
        lines.append("")
        lines.append("以下知识仍为 active 但长期未修改，建议 owner 复核是否仍成立：")
        lines.append("")
        for row in report.stale_active_knowledge:
            lines.append(
                f"- `{row['knowledge_id']}` ({row['path']}) "
                f"最后更新 {row['last_touched']}（{row['age_days']} 天前）"
            )
        lines.append("")

    if report.long_lived_drafts:
        lines.append(f"## 长期停留在 Draft 的知识（{len(report.long_lived_drafts)}）")
        lines.append("")
        lines.append("以下知识 draft 状态保持过久，建议推进审核或标记废弃：")
        lines.append("")
        for row in report.long_lived_drafts:
            lines.append(
                f"- `{row['knowledge_id']}` ({row['path']}) "
                f"创建于 {row['last_touched']}（{row['age_days']} 天前）"
            )
        lines.append("")

    lines.append("---")
    lines.append("阈值可用 `--zero-adoption-days / --stale-active-days / --draft-days` 调整。")
    return "\n".join(lines)
