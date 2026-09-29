"""V0.8 tests: actionable status report.

``doctor`` reports whether the structure is valid and ``doctor --report stale``
reports what has gone quiet. ``status`` answers the question a maintainer
actually starts the day with: what is waiting on me, and what do I type?

These tests pin that every reported item carries a reason and a runnable
command, that severities are correct, and that resolving the underlying
problem removes the item rather than leaving a stale reminder behind.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess
import unittest

import yaml

from team_wiki.core import _rewrite_change_meta, create_change, init_team, parse_frontmatter
from team_wiki.review import resolve_review, upsert_review
from team_wiki.status import build_status_report, format_status_report
from team_wiki.stale import build_stale_report, format_stale_report


def _age_file(path: Path, key: str, days: int) -> str:
    """Backdate a frontmatter field by ``days`` and return the matching 'now'."""
    meta, _ = parse_frontmatter(path)
    base = datetime.fromisoformat(str(meta[key]).replace("Z", "+00:00"))
    meta[key] = (base - timedelta(days=days)).isoformat()
    path.write_text(
        "---\n" + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False) + "---\n\nbody\n",
        encoding="utf-8",
    )
    return (base + timedelta(days=0)).isoformat()


class V08StatusTests(unittest.TestCase):
    def _team(self, td: str) -> Path:
        root = Path(td) / "kb"
        init_team(root, "demo-team")
        return root

    def _knowledge(self, root: Path, kid: str, status: str) -> Path:
        path = root / "wiki/business/orders" / f"{kid.lower()}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        (path.parent / "INDEX.md").write_text("# orders\n", encoding="utf-8")
        path.write_text(
            f"""---
id: {kid}
type: rule
status: {status}
title: 规则 {kid}
owner: demo
confidence: unknown
summary: 摘要
tags: []
updated_at: {datetime.now(timezone.utc).isoformat()}
---

# 规则 {kid}

正文。
""",
            encoding="utf-8",
        )
        return path

    def _kinds(self, root: Path, **kwargs) -> list[str]:
        return [d.kind for d in build_status_report(root, **kwargs).decisions]

    def _find(self, root: Path, kind: str, **kwargs):
        for item in build_status_report(root, **kwargs).decisions:
            if item.kind == kind:
                return item
        return None

    # --- clean repository ---

    def test_empty_repo_reports_nothing(self):
        with TemporaryDirectory() as td:
            root = self._team(td)
            report = build_status_report(root)
            self.assertEqual(report.decisions, [])
            self.assertEqual(report.blocking, [])
            self.assertEqual(report.attention, [])
            self.assertIn("没有需要你决策", format_status_report(report))

    def test_fresh_active_knowledge_is_not_flagged(self):
        with TemporaryDirectory() as td:
            root = self._team(td)
            self._knowledge(root, "K-FRESH", "active")
            self.assertNotIn("stale-knowledge", self._kinds(root))

    # --- blocked publish ---

    def _blocked_change(self, root: Path) -> tuple[str, str]:
        change = create_change(root, "确认订单导入边界", "demo")
        meta, _ = parse_frontmatter(change)
        change_id = str(meta["change_id"])
        review = upsert_review(
            root,
            kind="contradiction",
            title="导入与退款规则冲突",
            description="两处规则矛盾",
            owner="demo",
            linked_changes=[change_id],
        )
        review_id = str(parse_frontmatter(review)[0]["review_id"])
        _rewrite_change_meta(change, {"stage": "proposed", "review_ids": [review_id]})
        return change_id, review_id

    def test_proposed_change_with_open_review_blocks_publication(self):
        with TemporaryDirectory() as td:
            root = self._team(td)
            change_id, review_id = self._blocked_change(root)

            item = self._find(root, "blocked-publish")

            self.assertIsNotNone(item)
            self.assertEqual(item.severity, "blocking")
            self.assertIn(change_id, item.title)
            self.assertIn(review_id, " ".join(item.actions))
            self.assertIn("导入与退款规则冲突", item.detail)

    def test_resolving_the_review_clears_the_block(self):
        with TemporaryDirectory() as td:
            root = self._team(td)
            _change_id, review_id = self._blocked_change(root)
            self.assertEqual(self._find(root, "blocked-publish").severity, "blocking")

            resolve_review(root, review_id, action="confirmed", note="以导入规则为准")

            self.assertIsNone(self._find(root, "blocked-publish"))

    def test_collecting_change_is_not_a_publish_block(self):
        """A change still being written is not yet blocking anyone."""
        with TemporaryDirectory() as td:
            root = self._team(td)
            change = create_change(root, "还在收集证据", "demo")
            meta, _ = parse_frontmatter(change)
            review = upsert_review(
                root, kind="confirm", title="待确认", description="d", owner="demo"
            )
            _rewrite_change_meta(
                change,
                {"stage": "collecting", "review_ids": [parse_frontmatter(review)[0]["review_id"]]},
            )
            self.assertIsNone(self._find(root, "blocked-publish"))

    def test_clearing_the_block_actually_unblocks_publication(self):
        """status and publish must agree: once status stops reporting, publish works."""
        from team_wiki.publication import record_publication

        with TemporaryDirectory() as td:
            root = self._team(td)

            def git(*args: str) -> None:
                subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)

            git("init", "-q")
            git("config", "user.email", "d@e.com")
            git("config", "user.name", "D")
            self._knowledge(root, "K-BLOCK", "active")
            git("add", "-A")
            git("commit", "-qm", "init")

            change_id, review_id = self._blocked_change(root)
            git("add", "-A")
            git("commit", "-qm", "change")
            with self.assertRaises(ValueError):
                record_publication(root, change_id, "K-BLOCK", published_ref="HEAD")

            resolve_review(root, review_id, action="confirmed", note="ok")
            git("add", "-A")
            git("commit", "-qm", "resolve review")

            self.assertIsNone(self._find(root, "blocked-publish"))
            publication = record_publication(root, change_id, "K-BLOCK", published_ref="HEAD")
            self.assertTrue(publication.exists())

    # --- stale review ---

    def test_long_open_review_is_reported(self):
        with TemporaryDirectory() as td:
            root = self._team(td)
            review = upsert_review(
                root, kind="suggestion", title="建议补充异常处理", description="d", owner="demo"
            )
            review_id = str(parse_frontmatter(review)[0]["review_id"])
            path = next(iter((root / "changes/reviews").rglob(f"{review_id}.md")))
            now = _age_file(path, "created", 40)

            item = self._find(root, "stale-review", now=datetime.fromisoformat(now), review_days=14)

            self.assertIsNotNone(item)
            self.assertIn(review_id, item.title)
            self.assertIn("40 天", item.detail)

    def test_stale_review_blocking_a_change_is_escalated(self):
        with TemporaryDirectory() as td:
            root = self._team(td)
            change_id, review_id = self._blocked_change(root)
            path = next(iter((root / "changes/reviews").rglob(f"{review_id}.md")))
            now = _age_file(path, "created", 40)

            item = self._find(root, "stale-review", now=datetime.fromisoformat(now), review_days=14)

            self.assertIsNotNone(item)
            self.assertEqual(item.severity, "blocking")
            self.assertIn(change_id, item.subject["blocking_changes"])

    # --- stale knowledge signals ---

    def test_long_active_knowledge_is_reported_with_a_repair_command(self):
        with TemporaryDirectory() as td:
            root = self._team(td)
            path = self._knowledge(root, "K-OLD", "active")
            now = _age_file(path, "updated_at", 200)

            self.assertIsNone(self._find(root, "stale-knowledge", now=datetime.fromisoformat(now)))
            item = self._find(root, "stale-knowledge", now=datetime.fromisoformat(now), include_history=True)

            self.assertIsNotNone(item)
            self.assertEqual(item.severity, "attention")
            self.assertIn("K-OLD", item.title)
            self.assertIn("复核线索", item.detail)
            self.assertTrue(any("search" in a for a in item.actions))
            self.assertFalse(any("evidence-bindings" in a for a in item.actions))
            self.assertFalse(any("--comparison narrows" in a for a in item.actions))

    def test_long_draft_is_reported(self):
        with TemporaryDirectory() as td:
            root = self._team(td)
            path = self._knowledge(root, "K-DRAFT", "draft")
            now = _age_file(path, "updated_at", 200)

            self.assertIsNone(self._find(root, "long-draft", now=datetime.fromisoformat(now)))
            item = self._find(root, "long-draft", now=datetime.fromisoformat(now), include_history=True)

            self.assertIsNotNone(item)
            self.assertIn("K-DRAFT", item.title)
            self.assertIn("核对来源", item.detail)
            self.assertTrue(any("search" in a for a in item.actions))
            self.assertFalse(any("evidence-bindings" in a for a in item.actions))
            self.assertFalse(any("--comparison adds" in a for a in item.actions))
            self.assertFalse(any("deprecated" in a for a in item.actions))

    def test_zero_adoption_publication_is_reported(self):
        with TemporaryDirectory() as td:
            root = self._team(td)

            def git(*args: str) -> None:
                subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)

            git("init", "-q")
            git("config", "user.email", "d@e.com")
            git("config", "user.name", "D")
            self._knowledge(root, "K-PUB", "active")
            git("add", "-A")
            git("commit", "-qm", "init")

            from team_wiki.publication import record_publication

            change = create_change(root, "发布 K-PUB", "demo")
            change_id = str(parse_frontmatter(change)[0]["change_id"])
            _rewrite_change_meta(change, {"stage": "proposed", "review_ids": []})
            record_publication(root, change_id, "K-PUB", published_ref="HEAD")
            # Age the publication so it crosses the zero-adoption threshold.
            for pub in (root / ".knowledge/records/publications").glob("PUB-*.yml"):
                data = yaml.safe_load(pub.read_text(encoding="utf-8"))
                data["published_at"] = (
                    datetime.fromisoformat(str(data["published_at"])) - timedelta(days=200)
                ).isoformat()
                pub.write_text(
                    yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
                )

            self.assertIsNone(self._find(root, "zero-adoption", now=datetime.now(timezone.utc)))
            item = self._find(root, "zero-adoption", now=datetime.now(timezone.utc), include_history=True)

            self.assertIsNotNone(item)
            self.assertIn("K-PUB", item.title)
            self.assertNotIn("无人使用", item.title + item.detail)
            self.assertIn("不代表没有实际使用", item.detail)
            self.assertTrue(any("search" in a for a in item.actions))
            self.assertFalse(any("adoption-status" in a for a in item.actions))
            stale_text = format_stale_report(
                build_stale_report(root, now=datetime.now(timezone.utc))
            )
            self.assertIn("不等于没有实际使用", stale_text)
            self.assertNotIn("标记 deprecated", stale_text)

    # --- inbox backlog ---

    def test_inbox_backlog_is_reported(self):
        with TemporaryDirectory() as td:
            root = self._team(td)
            for i in range(5):
                (root / "sources/inbox" / f"note{i}.md").write_text("x", encoding="utf-8")

            item = self._find(root, "inbox-backlog")

            self.assertIsNotNone(item)
            self.assertIn("5", item.title)
            self.assertTrue(any("Agent" in a for a in item.actions))
            self.assertFalse(any("ingest" in a or "intake" in a for a in item.actions))

    def test_small_inbox_is_not_flagged(self):
        with TemporaryDirectory() as td:
            root = self._team(td)
            (root / "sources/inbox" / "note0.md").write_text("x", encoding="utf-8")
            self.assertIsNone(self._find(root, "inbox-backlog"))

    def test_inbox_limit_is_configurable(self):
        with TemporaryDirectory() as td:
            root = self._team(td)
            for i in range(5):
                (root / "sources/inbox" / f"note{i}.md").write_text("x", encoding="utf-8")
            self.assertIsNone(self._find(root, "inbox-backlog", inbox_limit=10))

    # --- rendering and contract ---

    def test_every_decision_carries_a_reason_and_an_action(self):
        with TemporaryDirectory() as td:
            root = self._team(td)
            self._blocked_change(root)
            _age_file(self._knowledge(root, "K-OLD", "active"), "updated_at", 200)
            _age_file(self._knowledge(root, "K-DRAFT", "draft"), "updated_at", 200)
            for i in range(5):
                (root / "sources/inbox" / f"note{i}.md").write_text("x", encoding="utf-8")

            report = build_status_report(root)

            self.assertGreater(len(report.decisions), 0)
            for item in report.decisions:
                self.assertTrue(item.detail.strip(), f"{item.kind} 缺少原因")
                self.assertTrue(item.actions, f"{item.kind} 缺少下一步命令")
                self.assertIn(item.severity, {"blocking", "attention"})

    def test_formatted_output_lists_blocking_first_with_commands(self):
        with TemporaryDirectory() as td:
            root = self._team(td)
            self._blocked_change(root)
            (root / "sources/inbox" / "a.md").write_text("x", encoding="utf-8")
            (root / "sources/inbox" / "b.md").write_text("x", encoding="utf-8")
            (root / "sources/inbox" / "c.md").write_text("x", encoding="utf-8")
            (root / "sources/inbox" / "d.md").write_text("x", encoding="utf-8")

            text = format_status_report(build_status_report(root))

            self.assertIn("阻塞中", text)
            self.assertIn("需要留意", text)
            self.assertIn("review-resolve", text)
            self.assertLess(text.index("阻塞中"), text.index("需要留意"))

    def test_as_dict_is_json_serialisable(self):
        import json

        with TemporaryDirectory() as td:
            root = self._team(td)
            self._blocked_change(root)
            payload = build_status_report(root).as_dict()
            self.assertIn("decisions", payload)
            self.assertIn("blocking_count", payload)
            self.assertIsInstance(json.dumps(payload, ensure_ascii=False), str)

    def test_status_never_mutates_the_repository(self):
        with TemporaryDirectory() as td:
            root = self._team(td)
            self._blocked_change(root)
            before = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())

            build_status_report(root)
            build_status_report(root)

            after = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
