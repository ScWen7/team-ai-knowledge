from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess
import unittest

import yaml

from team_wiki.core import (
    _rewrite_change_meta,
    create_change,
    init_team,
)
from team_wiki.project import (
    finalize_project_work,
    handle_update,
    init_project,
    lock_latest,
    prepare_project_work,
    project_adopt,
    project_context,
    project_gate,
    project_observe,
    project_status,
)
from team_wiki.publication import record_publication


class V07Tests(unittest.TestCase):
    def _git(self, repo: Path, *args: str) -> str:
        cp = subprocess.run(
            ["git", "-C", str(repo), *args],
            text=True,
            capture_output=True,
            check=True,
        )
        return cp.stdout.strip()

    def _init_team_repo(self, root: Path) -> None:
        init_team(root, "team-knowledge")
        self._git(root, "init", "-q")
        self._git(root, "config", "user.email", "demo@example.com")
        self._git(root, "config", "user.name", "Demo")

    def _publish(
        self,
        root: Path,
        *,
        body: str,
        requirement: str,
        label: str,
        effective_at: str | None = None,
    ) -> dict:
        path = root / "wiki/business/orders/rule.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        (path.parent / "INDEX.md").write_text("# orders\n", encoding="utf-8")
        path.write_text(
            f"""---
id: K-A
type: rule
status: active
title: 订单联系电话规则
owner: demo
confidence: confirmed
summary: {label}
tags: [订单]
related: []
evidence: []
---
# 订单联系电话规则

{body}
""",
            encoding="utf-8",
        )
        change = create_change(root, f"publish {label}", "demo")
        meta, _ = __import__("team_wiki.core", fromlist=["parse_frontmatter"]).parse_frontmatter(change)
        _rewrite_change_meta(
            change,
            {"stage": "proposed", "review_ids": []},
        )
        self._git(root, "add", ".")
        self._git(root, "commit", "-qm", f"knowledge {label}")
        publication = record_publication(
            root,
            meta["change_id"],
            "K-A",
            published_ref="HEAD",
            adoption_requirement=requirement,
            effective_at=effective_at,
        )
        return yaml.safe_load(publication.read_text(encoding="utf-8"))

    def _init_project(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        init_project(
            root,
            project_id="project-b",
            team_repository_id="team-knowledge",
            knowledge_ids=["K-A"],
        )

    def test_review_required_update_can_defer_but_release_is_blocked_before_decision(self):
        with TemporaryDirectory() as td:
            base = Path(td)
            team = base / "team"
            self._init_team_repo(team)

            pub1 = self._publish(
                team,
                body="版本1：联系电话在所有阶段必填。",
                requirement="notice",
                label="v1",
            )

            project = base / "project"
            self._init_project(project)

            unlocked_gate = project_gate(project, team, phase="start")
            self.assertFalse(unlocked_gate["ok"])
            self.assertEqual(
                unlocked_gate["blockers"][0]["state"],
                "unlocked",
            )

            lock_latest(project, team)
            current = project_status(project, team)["rows"][0]
            self.assertEqual(current["state"], "current")
            self.assertEqual(
                current["locked"]["publication_id"],
                pub1["publication_id"],
            )

            pub2 = self._publish(
                team,
                body="版本2：草稿可为空，正式提交前必须补齐。",
                requirement="review-required",
                label="v2",
            )

            status = project_status(project, team)["rows"][0]
            self.assertEqual(status["state"], "update-available")
            self.assertEqual(
                status["latest"]["publication_id"],
                pub2["publication_id"],
            )

            start_gate = project_gate(project, team, phase="start")
            self.assertTrue(start_gate["ok"])
            self.assertEqual(
                start_gate["warnings"][0]["requirement"],
                "review-required",
            )

            release_gate = project_gate(project, team, phase="release")
            self.assertFalse(release_gate["ok"])

            work = prepare_project_work(
                project,
                team,
                goal="继续按锁定知识完成当前订单导入任务",
            )
            work_id = work.stem

            historical = project_context(project, team, work_id, "K-A")
            self.assertEqual(
                historical["publication_id"],
                pub1["publication_id"],
            )
            self.assertIn("版本1", historical["content"])
            self.assertNotIn("版本2", historical["content"])

            adopted = project_adopt(
                project,
                work_id,
                "K-A",
                used_for="实现订单导入字段校验",
            )
            self.assertEqual(
                adopted["publication_id"],
                pub1["publication_id"],
            )
            project_observe(
                project,
                work_id,
                "K-A",
                outcome="supported-in-scope",
                note="旧版本在本任务范围仍能工作。",
            )

            with self.assertRaisesRegex(ValueError, "release gate blocked"):
                finalize_project_work(project, team, work_id)

            decision = handle_update(
                project,
                team,
                "K-A",
                decision="defer",
                reason="当前迭代保持 v1；下一迭代切换 v2。",
            )
            self.assertEqual(decision["decision"], "defer")
            self.assertEqual(
                decision["to_publication_id"],
                pub2["publication_id"],
            )

            deferred = project_status(project, team)["rows"][0]
            self.assertEqual(deferred["state"], "deferred")
            self.assertTrue(project_gate(project, team, phase="release")["ok"])

            finalized = finalize_project_work(project, team, work_id)
            self.assertEqual(finalized["state"], "finalized")
            self.assertEqual(len(finalized["adoption_ids"]), 1)

            adoption_file = next(
                (team / ".knowledge/records/adoptions").glob("ADOPT-*.yml")
            )
            adoption = yaml.safe_load(adoption_file.read_text(encoding="utf-8"))
            self.assertEqual(adoption["consumer_id"], "project-b")
            self.assertEqual(
                adoption["publication_id"],
                pub1["publication_id"],
            )

    def test_must_address_blocks_start_and_cannot_defer(self):
        with TemporaryDirectory() as td:
            base = Path(td)
            team = base / "team"
            self._init_team_repo(team)

            self._publish(
                team,
                body="版本1：基础规则。",
                requirement="notice",
                label="v1",
            )
            project = base / "project"
            self._init_project(project)
            lock_latest(project, team)

            pub2 = self._publish(
                team,
                body="版本2：安全修订，必须处理。",
                requirement="must-address",
                label="v2",
            )

            gate = project_gate(project, team, phase="start")
            self.assertFalse(gate["ok"])
            self.assertEqual(
                gate["blockers"][0]["requirement"],
                "must-address",
            )

            with self.assertRaisesRegex(ValueError, "cannot be deferred"):
                handle_update(
                    project,
                    team,
                    "K-A",
                    decision="defer",
                    reason="暂缓",
                )

            accepted = handle_update(
                project,
                team,
                "K-A",
                decision="accept",
                reason="升级到安全修订。",
            )
            self.assertEqual(accepted["decision"], "accept")

            status = project_status(project, team)["rows"][0]
            self.assertEqual(status["state"], "current")
            self.assertEqual(
                status["locked"]["publication_id"],
                pub2["publication_id"],
            )
            self.assertTrue(project_gate(project, team, phase="start")["ok"])
            self.assertTrue(project_gate(project, team, phase="release")["ok"])

    def test_lock_change_mid_task_requires_new_work(self):
        with TemporaryDirectory() as td:
            base = Path(td)
            team = base / "team"
            self._init_team_repo(team)

            self._publish(
                team,
                body="版本1。",
                requirement="notice",
                label="v1",
            )
            project = base / "project"
            self._init_project(project)
            lock_latest(project, team)

            work = prepare_project_work(
                project,
                team,
                goal="基于 v1 开始任务",
            )
            work_id = work.stem
            project_adopt(
                project,
                work_id,
                "K-A",
                used_for="执行当前任务",
            )

            self._publish(
                team,
                body="版本2。",
                requirement="notice",
                label="v2",
            )
            self.assertTrue(project_gate(project, team, phase="start")["ok"])

            handle_update(
                project,
                team,
                "K-A",
                decision="accept",
                reason="切换到 v2。",
            )

            with self.assertRaisesRegex(ValueError, "knowledge.lock changed"):
                finalize_project_work(project, team, work_id)

    def test_future_publication_does_not_replace_effective_lock(self):
        with TemporaryDirectory() as td:
            base = Path(td)
            team = base / "team"
            self._init_team_repo(team)

            pub1 = self._publish(
                team,
                body="当前有效版本。",
                requirement="notice",
                label="v1",
            )
            self._publish(
                team,
                body="未来版本。",
                requirement="must-address",
                label="v2-future",
                effective_at="2999-01-01T00:00:00+00:00",
            )

            project = base / "project"
            self._init_project(project)
            lock_latest(project, team)

            row = project_status(project, team)["rows"][0]
            self.assertEqual(
                row["locked"]["publication_id"],
                pub1["publication_id"],
            )
            self.assertEqual(row["state"], "scheduled")
            self.assertTrue(project_gate(project, team, phase="start")["ok"])


if __name__ == "__main__":
    unittest.main()
