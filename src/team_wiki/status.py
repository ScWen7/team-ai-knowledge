"""Actionable status: what needs a human decision, and the exact next command.

``doctor`` answers "is the structure valid". ``doctor --report stale`` answers
"what has gone quiet". Neither answers the question a maintainer actually
starts the day with: *what is waiting on me, and what do I type?*

This module aggregates the signals the toolkit already computes and turns each
one into a decision item carrying its reason and a ready-to-run command. It
adds no new state and never mutates the repository.

Each item is one of:

- ``blocked-publish``  a change cannot be published until its Reviews close
- ``stale-review``     a Review has been open long enough to stall a release
- ``zero-adoption``    no Adoption record was found for a Publication in the observation window
- ``stale-knowledge``  an ``active`` entry has an old recorded modification time
- ``long-draft``       a ``draft`` has an old recorded modification time
- ``inbox-backlog``    material was submitted but never registered
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .core import iter_changes, parse_frontmatter, utc_now
from .stale import _age_days, _parse_iso, build_stale_report


SEVERITIES = ("blocking", "attention")


@dataclass
class Decision:
    kind: str
    severity: str
    title: str
    detail: str
    subject: dict[str, Any] = field(default_factory=dict)
    actions: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "severity": self.severity,
            "title": self.title,
            "detail": self.detail,
            "subject": self.subject,
            "actions": self.actions,
        }


@dataclass
class StatusReport:
    decisions: list[Decision] = field(default_factory=list)
    generated_at: str = ""
    thresholds: dict[str, int] = field(default_factory=dict)

    @property
    def blocking(self) -> list[Decision]:
        return [d for d in self.decisions if d.severity == "blocking"]

    @property
    def attention(self) -> list[Decision]:
        return [d for d in self.decisions if d.severity == "attention"]

    def as_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at or utc_now(),
            "thresholds": self.thresholds,
            "total": len(self.decisions),
            "blocking_count": len(self.blocking),
            "attention_count": len(self.attention),
            "decisions": [d.as_dict() for d in self.decisions],
        }


def _review_state(root: Path, review_id: str) -> str | None:
    from .review import find_review

    path = find_review(root, review_id)
    if path is None:
        return None
    meta, _ = parse_frontmatter(path)
    return str(meta.get("state", "unknown"))


def _review_title(root: Path, review_id: str) -> str:
    from .review import find_review

    path = find_review(root, review_id)
    if path is None:
        return review_id
    meta, _ = parse_frontmatter(path)
    return str(meta.get("title") or review_id)


def _blocked_publishes(root: Path) -> list[Decision]:
    """Changes that are ready to ship but held up by unresolved Reviews."""
    from .publication import RESOLVED_REVIEW_STATES

    out: list[Decision] = []
    for path in sorted(iter_changes(root)):
        meta, _ = parse_frontmatter(path)
        stage = str(meta.get("stage", "unknown"))
        if stage not in {"proposed", "ready"}:
            continue
        pending = [
            str(rid)
            for rid in (meta.get("review_ids") or [])
            if _review_state(root, str(rid)) not in RESOLVED_REVIEW_STATES
        ]
        if not pending:
            continue
        change_id = str(meta.get("change_id") or path.stem)
        titles = "、".join(_review_title(root, rid) for rid in pending)
        out.append(
            Decision(
                kind="blocked-publish",
                severity="blocking",
                title=f"{change_id} {meta.get('title', '')}".strip(),
                detail=(
                    f"stage={stage}，但仍有 {len(pending)} 个未处理 Review（{titles}），"
                    "发布会被拒绝。"
                ),
                subject={
                    "change_id": change_id,
                    "stage": stage,
                    "path": str(path.relative_to(root)),
                    "pending_review_ids": pending,
                },
                actions=[
                    f'team-wiki review-resolve . {pending[0]} --action <action> --note "<理由>"',
                    f'team-wiki publish . {change_id} <knowledge-id> --requirement <notice|review-required|must-address>',
                ],
            )
        )
    return out


def _stale_reviews(root: Path, now: datetime, days: int) -> list[Decision]:
    from .review import list_reviews

    out: list[Decision] = []
    for row in list_reviews(root, state="open"):
        meta, _body = parse_frontmatter(root / row["path"])
        created = _parse_iso(meta.get("created"))
        age = _age_days(now, created)
        if age is None or age < days:
            continue
        rid = str(row["review_id"])
        linked = [
            str(m.get("change_id"))
            for m in (parse_frontmatter(root / p)[0] for p in iter_changes(root))
            if rid in (m.get("review_ids") or [])
        ]
        detail = f"已 open {age} 天（{row['kind']}）。"
        if linked:
            detail += f"正在阻塞发布：{'、'.join(linked)}。"
        out.append(
            Decision(
                kind="stale-review",
                severity="blocking" if linked else "attention",
                title=f"{rid} {row['title']}".strip(),
                detail=detail,
                subject={
                    "review_id": rid,
                    "kind": row.get("kind"),
                    "owner": row.get("owner"),
                    "age_days": age,
                    "blocking_changes": linked,
                },
                actions=[
                    f'team-wiki review-resolve . {rid} --action <action> --note "<结论>"',
                ],
            )
        )
    return out


def _inbox_backlog(root: Path, limit: int) -> list[Decision]:
    inbox = root / "sources/inbox"
    if not inbox.exists():
        return []
    pending = sorted(
        p for p in inbox.iterdir() if p.is_file() and not p.name.startswith(".")
    )
    if len(pending) <= limit:
        return []
    return [
        Decision(
            kind="inbox-backlog",
            severity="attention",
            title=f"{len(pending)} 份资料已投递但未登记",
            detail=(
                "sources/inbox/ 中的文件不会自动成为知识。需要执行 ingest 登记为稳定 source。"
            ),
            subject={"count": len(pending), "files": [p.name for p in pending[:10]]},
            actions=[
                f'team-wiki ingest . sources/inbox/{pending[0].name} --title "<标题>"',
                "team-wiki intake-source . <source-id>",
                "team-wiki intake-decide . <intake-id> --keep-evidence <evidence-id>",
            ],
        )
    ]


def _stale_decisions(root: Path, report: Any) -> list[Decision]:
    out: list[Decision] = []
    for row in report.zero_adoption_publications:
        kid = row.get("knowledge_id")
        out.append(
            Decision(
                kind="zero-adoption",
                severity="attention",
                title=f"{kid} @ {row['publication_id']} 未记录到采用",
                detail=(
                    f"发布于 {row['published_at']}（{row['age_days']} 天前）。"
                    "当前记录中没有该版本的 Adoption；这不代表没有实际使用。"
                    "可核对知识来源、项目记录和查找路径。"
                ),
                subject={
                    "knowledge_id": kid,
                    "publication_id": row["publication_id"],
                    "age_days": row["age_days"],
                },
                actions=[
                    f"team-wiki adoption-status . {kid}",
                    f"team-wiki search . \"{kid}\"",
                ],
            )
        )
    for row in report.stale_active_knowledge:
        kid = row.get("knowledge_id")
        out.append(
            Decision(
                kind="stale-knowledge",
                severity="attention",
                title=f"{kid} 距最近可用修改时间 {row['age_days']} 天",
                detail=(
                    f"最近可用修改时间为 {row['last_touched']}。"
                    "时间较久只是复核线索，不能据此判定知识失效。"
                ),
                subject={
                    "knowledge_id": kid,
                    "path": row["path"],
                    "age_days": row["age_days"],
                },
                actions=[
                    f"team-wiki evidence-bindings . --target-id {kid}",
                    f"team-wiki search . \"{kid}\"",
                ],
            )
        )
    for row in report.long_lived_drafts:
        kid = row.get("knowledge_id")
        out.append(
            Decision(
                kind="long-draft",
                severity="attention",
                title=f"{kid} 仍为 draft，已超过观察期 {row['age_days']} 天",
                detail=(
                    f"最近可用修改时间为 {row['last_touched']}。"
                    "这只是状态和时间线索，建议先核对来源、结论和当前需求。"
                ),
                subject={
                    "knowledge_id": kid,
                    "path": row["path"],
                    "age_days": row["age_days"],
                },
                actions=[
                    f"team-wiki evidence-bindings . --target-id {kid}",
                    f"team-wiki search . \"{kid}\"",
                ],
            )
        )
    return out


def build_status_report(
    root: Path,
    *,
    now: datetime | None = None,
    zero_adoption_days: int = 90,
    stale_active_days: int = 180,
    draft_days: int = 60,
    review_days: int = 14,
    inbox_limit: int = 3,
) -> StatusReport:
    """Collect every decision the current maintainer actually has to make."""
    now = now or datetime.now(timezone.utc)
    stale = build_stale_report(
        root,
        zero_adoption_days=zero_adoption_days,
        stale_active_days=stale_active_days,
        draft_days=draft_days,
    )
    report = StatusReport(
        decisions=[
            *_blocked_publishes(root),
            *_stale_reviews(root, now, review_days),
            *_stale_decisions(root, stale),
            *_inbox_backlog(root, inbox_limit),
        ],
        generated_at=utc_now(),
        thresholds={
            "zero_adoption_days": zero_adoption_days,
            "stale_active_days": stale_active_days,
            "draft_days": draft_days,
            "review_days": review_days,
            "inbox_limit": inbox_limit,
        },
    )
    return report


_KIND_LABELS = {
    "blocked-publish": "发布被阻塞",
    "stale-review": "Review 长期未处理",
    "zero-adoption": "发布后未记录到采用",
    "stale-knowledge": "知识修改时间较久",
    "long-draft": "draft 超过观察期",
    "inbox-backlog": "资料积压未登记",
}


def format_status_report(report: StatusReport) -> str:
    if not report.decisions:
        return "✅ 没有需要你决策的事项。"

    lines = ["# 待决策事项", ""]
    blocking = report.blocking
    attention = report.attention

    if blocking:
        lines.append(f"## 阻塞中（{len(blocking)}）")
        lines.append("")
        for item in blocking:
            lines.append(f"### [{_KIND_LABELS.get(item.kind, item.kind)}] {item.title}")
            lines.append("")
            lines.append(item.detail)
            lines.append("")
            for action in item.actions:
                lines.append(f"```bash\n{action}\n```")
            lines.append("")

    if attention:
        lines.append(f"## 需要留意（{len(attention)}）")
        lines.append("")
        for item in attention:
            lines.append(f"- **[{_KIND_LABELS.get(item.kind, item.kind)}]** {item.title}")
            lines.append(f"  - {item.detail}")
            if item.actions:
                lines.append(f"  - 下一步：`{item.actions[0]}`")
            lines.append("")

    lines.append("---")
    lines.append(
        "阈值可调："
        "`team-wiki status . --zero-adoption-days / --stale-active-days / "
        "--draft-days / --review-days`。"
    )
    return "\n".join(lines)
