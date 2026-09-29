"""V0.8 tests: project-work facade.

``project-work`` collapses the documented project-side sequence

    project-prepare → project-context → project-adopt
                    → project-observe → project-finalize

from five invocations to two. The important property is not the shorter
command line but that the facade cannot bypass the start/release gates:
every test here asserts the same blocking behaviour the individual
commands already guarantee.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess
import unittest

import yaml

from team_wiki.core import _rewrite_change_meta, create_change, init_team, parse_frontmatter
from team_wiki.project import (
    finalize_project_work,
    init_project,
    lock_latest,
    prepare_project_work,
    project_adopt,
    project_observe,
    run_project_work,
)
from team_wiki.publication import record_publication


class V08ProjectWorkTests(unittest.TestCase):
    def _git(self, repo: Path, *args: str) -> str:
        cp = subprocess.run(
            ["git", "-C", str(repo), *args], text=True, capture_output=True, check=True
        )
        return cp.stdout.strip()

    def _init_team_repo(self, root: Path) -> None:
        init_team(root, "team-knowledge")
        self._git(root, "init", "-q")
        self._git(root, "config", "user.email", "demo@example.com")
        self._git(root, "config", "user.name", "Demo")

    def _publish(self, root: Path, *, body: str, requirement: str, label: str) -> dict:
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
        meta, _ = parse_frontmatter(change)
        _rewrite_change_meta(change, {"stage": "proposed", "review_ids": []})
        self._git(root, "add", ".")
        self._git(root, "commit", "-qm", f"knowledge {label}")
        publication = record_publication(
            root, meta["change_id"], "K-A",
            published_ref="HEAD", adoption_requirement=requirement,
        )
        return yaml.safe_load(publication.read_text(encoding="utf-8"))

    def _project(self, base: Path, team: Path) -> Path:
        project = base / "project-b"
        init_project(
            project,
            project_id="project-b",
            team_repository_id="team-knowledge",
            knowledge_ids=["K-A"],
        )
        lock_latest(project, team)
        return project

    # --- start ---

    def test_start_creates_work_and_returns_locked_context(self):
        with TemporaryDirectory() as td:
            base = Path(td)
            team = base / "team"
            self._init_team_repo(team)
            self._publish(team, body="版本1：联系电话必填。", requirement="notice", label="v1")
            project = self._project(base, team)

            result = run_project_work(project, team, phase="start", goal="实现订单导入", read_knowledge=["K-A"])

            self.assertTrue(str(result["work_id"]).startswith("PW-"))
            self.assertEqual(len(result["contexts"]), 1)
            self.assertEqual(result["contexts"][0]["knowledge_id"], "K-A")
            self.assertIn("联系电话必填", result["contexts"][0]["content"])
            self.assertIsNone(result["finalized"])

    def test_start_requires_goal(self):
        with TemporaryDirectory() as td:
            base = Path(td)
            team = base / "team"
            self._init_team_repo(team)
            self._publish(team, body="v1", requirement="notice", label="v1")
            project = self._project(base, team)

            with self.assertRaises(ValueError):
                run_project_work(project, team, phase="start")

    def test_start_rejects_unknown_phase(self):
        with TemporaryDirectory() as td:
            base = Path(td)
            team = base / "team"
            self._init_team_repo(team)
            with self.assertRaises(ValueError):
                run_project_work(base / "p", team, phase="middle")

    def test_start_does_not_finalize(self):
        """The facade must not report adoption for work that is still running."""
        with TemporaryDirectory() as td:
            base = Path(td)
            team = base / "team"
            self._init_team_repo(team)
            self._publish(team, body="v1", requirement="notice", label="v1")
            project = self._project(base, team)

            result = run_project_work(project, team, phase="start", goal="g", read_knowledge=["K-A"])

            work = yaml.safe_load(
                (project / ".knowledge/runs" / f"{result['work_id']}.yml").read_text(encoding="utf-8")
            )
            self.assertEqual(work["state"], "active")
            self.assertEqual(work["adopted"], [])
            self.assertEqual(list((team / ".knowledge/records/adoptions").glob("*.yml")), [])

    # --- finish ---

    def test_finish_records_adoption_and_reports_to_team(self):
        with TemporaryDirectory() as td:
            base = Path(td)
            team = base / "team"
            self._init_team_repo(team)
            self._publish(team, body="版本1：联系电话必填。", requirement="notice", label="v1")
            project = self._project(base, team)
            start = run_project_work(project, team, phase="start", goal="g", read_knowledge=["K-A"])

            result = run_project_work(
                project, team, phase="finish", work_id=start["work_id"],
                adopt=["K-A"],
                observations=[{
                    "knowledge_id": "K-A", "outcome": "supported-in-scope",
                    "note": "批量场景验证通过", "used_for": "实现导入校验",
                }],
            )

            self.assertEqual(result["finalized"]["state"], "finalized")
            self.assertEqual(len(result["adoptions"]), 1)
            self.assertEqual(result["adoptions"][0]["used_for"], "实现导入校验")
            self.assertEqual(result["observations"][0]["outcome"], "supported-in-scope")

            adoptions = list((team / ".knowledge/records/adoptions").glob("ADOPT-*.yml"))
            self.assertEqual(len(adoptions), 1)
            record = yaml.safe_load(adoptions[0].read_text(encoding="utf-8"))
            self.assertEqual(record["consumer_id"], "project-b")
            self.assertEqual(record["knowledge_id"], "K-A")
            self.assertEqual(record["outcome"], "supported-in-scope")

    def test_finish_requires_work_id(self):
        with TemporaryDirectory() as td:
            base = Path(td)
            team = base / "team"
            self._init_team_repo(team)
            with self.assertRaises(ValueError):
                run_project_work(base / "p", team, phase="finish")

    def test_observation_requires_knowledge_id(self):
        with TemporaryDirectory() as td:
            base = Path(td)
            team = base / "team"
            self._init_team_repo(team)
            self._publish(team, body="v1", requirement="notice", label="v1")
            project = self._project(base, team)
            start = run_project_work(project, team, phase="start", goal="g")

            with self.assertRaises(ValueError):
                run_project_work(
                    project, team, phase="finish", work_id=start["work_id"],
                    observations=[{"outcome": "supported-in-scope", "note": "x"}],
                )

    def test_observe_without_adopt_is_rejected(self):
        """The facade must not weaken the adopt-before-observe precondition."""
        with TemporaryDirectory() as td:
            base = Path(td)
            team = base / "team"
            self._init_team_repo(team)
            self._publish(team, body="v1", requirement="notice", label="v1")
            project = self._project(base, team)
            start = run_project_work(project, team, phase="start", goal="g")

            with self.assertRaises(ValueError):
                run_project_work(
                    project, team, phase="finish", work_id=start["work_id"],
                    observations=[{"knowledge_id": "K-A", "outcome": "supported-in-scope", "note": "x"}],
                )

    # --- gates are not bypassed ---

    def test_must_address_still_blocks_start(self):
        with TemporaryDirectory() as td:
            base = Path(td)
            team = base / "team"
            self._init_team_repo(team)
            self._publish(team, body="版本1。", requirement="notice", label="v1")
            project = self._project(base, team)
            self._publish(team, body="版本2 必须处理。", requirement="must-address", label="v2")

            with self.assertRaises(ValueError) as ctx:
                run_project_work(project, team, phase="start", goal="g")

            self.assertIn("start gate blocked", str(ctx.exception))
            self.assertIn("K-A", str(ctx.exception))

    def test_review_required_still_blocks_release(self):
        with TemporaryDirectory() as td:
            base = Path(td)
            team = base / "team"
            self._init_team_repo(team)
            self._publish(team, body="版本1。", requirement="notice", label="v1")
            project = self._project(base, team)
            start = run_project_work(project, team, phase="start", goal="g")
            self._publish(team, body="版本2 需复核。", requirement="review-required", label="v2")

            with self.assertRaises(ValueError) as ctx:
                run_project_work(project, team, phase="finish", work_id=start["work_id"])

            self.assertIn("release gate blocked", str(ctx.exception))

    def test_lock_change_mid_task_still_rejects_finish(self):
        with TemporaryDirectory() as td:
            base = Path(td)
            team = base / "team"
            self._init_team_repo(team)
            self._publish(team, body="版本1。", requirement="notice", label="v1")
            project = self._project(base, team)
            start = run_project_work(project, team, phase="start", goal="g")

            # Someone upgrades the lock while the task is running.
            self._publish(team, body="版本2。", requirement="notice", label="v2")
            lock_latest(project, team)

            with self.assertRaises(ValueError) as ctx:
                run_project_work(project, team, phase="finish", work_id=start["work_id"])

            self.assertIn("knowledge.lock changed", str(ctx.exception))

    def test_facade_matches_manual_sequence(self):
        """The facade and the five individual commands must produce the same state."""
        with TemporaryDirectory() as td:
            base = Path(td)
            facade_team = base / "team-a"
            manual_team = base / "team-b"
            self._init_team_repo(facade_team)
            self._init_team_repo(manual_team)
            self._publish(facade_team, body="版本1。", requirement="notice", label="v1")
            self._publish(manual_team, body="版本1。", requirement="notice", label="v1")
            facade_project = self._project(base / "a", facade_team)
            manual_project = self._project(base / "b", manual_team)

            run_project_work(
                facade_project, facade_team, phase="start", goal="g", read_knowledge=["K-A"]
            )
            facade_work_id = list((facade_project / ".knowledge/runs").glob("PW-*.yml"))[0].stem
            run_project_work(
                facade_project, facade_team, phase="finish",
                work_id=facade_work_id,
                adopt=["K-A"],
                observations=[{"knowledge_id": "K-A", "outcome": "boundary-found",
                               "note": "边界", "used_for": "u"}],
            )

            manual_work = prepare_project_work(manual_project, manual_team, goal="g")
            project_adopt(manual_project, manual_work.stem, "K-A", used_for="u")
            project_observe(manual_project, manual_work.stem, "K-A",
                            outcome="boundary-found", note="边界")
            finalize_project_work(manual_project, manual_team, manual_work.stem)

            def summarize(project: Path, work_id: str) -> tuple:
                data = yaml.safe_load(
                    (project / ".knowledge/runs" / f"{work_id}.yml").read_text(encoding="utf-8")
                )
                adopted = data["adopted"][0]
                return (
                    data["state"],
                    adopted["knowledge_id"],
                    adopted["used_for"],
                    adopted["outcome"],
                    len(adopted["observations"]),
                )

            self.assertEqual(
                summarize(facade_project, facade_work_id),
                summarize(manual_project, manual_work.stem),
            )


if __name__ == "__main__":
    unittest.main()
