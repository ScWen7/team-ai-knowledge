from pathlib import Path
from tempfile import TemporaryDirectory
import json
import subprocess
import unittest

import yaml

from team_wiki.candidate import (
    apply_patch_plan,
    create_candidate,
    create_patch_plan,
    patch_plan_context,
)
from team_wiki.connector import (
    connector_status,
    create_git_connector,
    sync_git_connector,
)
from team_wiki.core import init_team, parse_frontmatter, register_source
from team_wiki.evidence import bind_evidence, correct_evidence
from team_wiki.intake import intake_source


class V05Tests(unittest.TestCase):
    def _knowledge(self, root: Path, kid: str = "K-ORDER") -> Path:
        path = root / "wiki/business/orders/rule.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        (path.parent / "INDEX.md").write_text("# orders\n", encoding="utf-8")
        path.write_text(
            f"""---
id: {kid}
type: rule
status: draft
title: 订单联系电话规则
owner: demo
confidence: unknown
summary: 示例规则。
tags: [订单]
related: []
evidence: []
---
# 订单联系电话规则

正式提交前联系电话必填。
""",
            encoding="utf-8",
        )
        return path

    def _evidence(self, root: Path) -> str:
        source = root.parent / "source.md"
        source.write_text(
            "# 联系电话\n草稿导入可缺少联系电话；正式提交前必须补齐。\n",
            encoding="utf-8",
        )
        pkg = register_source(root, source, "订单导入确认")
        source_id = yaml.safe_load((pkg / "source.yml").read_text(encoding="utf-8"))["source_id"]
        intake = intake_source(root, source_id, max_chars=500)
        manifest = json.loads((intake / "manifest.json").read_text(encoding="utf-8"))
        return manifest["chunks"][0]["evidence_id"]

    def test_evidence_candidate_patch_plan_and_safe_apply(self):
        with TemporaryDirectory() as td:
            root = Path(td) / "kb"
            init_team(root, "demo-team")
            target = self._knowledge(root)
            evidence_id = self._evidence(root)

            candidate = create_candidate(
                root,
                proposed_id="K-ORDER",
                title="订单联系电话按阶段校验",
                knowledge_type="rule",
                statement="草稿导入可缺少联系电话；正式提交前必须补齐。",
                owner="demo-owner",
            )
            candidate_id = yaml.safe_load(candidate.read_text(encoding="utf-8"))["candidate_id"]
            bind_evidence(
                root,
                evidence_id,
                target_kind="candidate",
                target_id=candidate_id,
                relation="limits",
                note="限制原规则的适用阶段",
            )

            plan = create_patch_plan(
                root,
                candidate_id,
                comparison="narrows",
                summary="将原来的全阶段必填收窄为正式提交前必填。",
                owner="demo-owner",
                target_knowledge_id="K-ORDER",
            )
            plan_data = yaml.safe_load(plan.read_text(encoding="utf-8"))
            self.assertEqual(plan_data["action"], "update")
            self.assertTrue(plan_data["change_id"])
            self.assertEqual(plan_data["target"]["knowledge_id"], "K-ORDER")
            self.assertFalse(patch_plan_context(root, plan_data["plan_id"])["stale"])

            proposed = Path(td) / "revised.md"
            proposed.write_text(
                """---
id: K-ORDER
type: rule
status: draft
title: 订单联系电话按阶段校验
owner: demo-owner
confidence: confirmed
summary: 草稿导入可为空，正式提交前必须补齐。
tags: [订单, 导入]
related: []
evidence: []
---
# 订单联系电话按阶段校验

- 草稿导入阶段：联系电话可以为空。
- 正式提交前：联系电话必须补齐。
""",
                encoding="utf-8",
            )
            applied = apply_patch_plan(root, plan_data["plan_id"], proposed)
            self.assertEqual(applied, target)
            self.assertIn("草稿导入阶段", target.read_text(encoding="utf-8"))
            applied_plan = yaml.safe_load(plan.read_text(encoding="utf-8"))
            self.assertEqual(applied_plan["status"], "applied")

            change = next((root / "changes").rglob(f"{plan_data['change_id']}.md"))
            change_meta, _ = parse_frontmatter(change)
            self.assertEqual(change_meta["stage"], "proposed")
            self.assertIn(plan_data["plan_id"], change_meta["patch_plan_ids"])

    def test_patch_plan_rejects_stale_target(self):
        with TemporaryDirectory() as td:
            root = Path(td) / "kb"
            init_team(root, "demo-team")
            target = self._knowledge(root)
            evidence_id = self._evidence(root)
            candidate = create_candidate(
                root,
                proposed_id="K-ORDER",
                title="补充订单联系电话说明",
                knowledge_type="rule",
                statement="增加草稿阶段说明。",
            )
            candidate_id = yaml.safe_load(candidate.read_text(encoding="utf-8"))["candidate_id"]
            bind_evidence(root, evidence_id, target_kind="candidate", target_id=candidate_id, relation="supports")
            plan = create_patch_plan(
                root,
                candidate_id,
                comparison="adds",
                summary="补充草稿阶段说明。",
                target_knowledge_id="K-ORDER",
            )
            plan_id = yaml.safe_load(plan.read_text(encoding="utf-8"))["plan_id"]

            target.write_text(target.read_text(encoding="utf-8") + "\n外部并发修改。\n", encoding="utf-8")
            proposed = Path(td) / "proposal.md"
            proposed.write_text(
                """---
id: K-ORDER
type: rule
status: draft
title: 新标题
owner: demo
confidence: unknown
summary: 示例
tags: []
related: []
evidence: []
---
# 新标题
内容
""",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "stale"):
                apply_patch_plan(root, plan_id, proposed)

    def test_patch_plan_rejects_changed_evidence(self):
        with TemporaryDirectory() as td:
            root = Path(td) / "kb"
            init_team(root, "demo-team")
            self._knowledge(root)
            evidence_id = self._evidence(root)
            candidate = create_candidate(
                root,
                proposed_id="K-ORDER",
                title="证据变化测试",
                knowledge_type="rule",
                statement="基于当前证据提出修改。",
            )
            candidate_id = yaml.safe_load(candidate.read_text(encoding="utf-8"))["candidate_id"]
            bind_evidence(root, evidence_id, target_kind="candidate", target_id=candidate_id, relation="supports")
            plan = create_patch_plan(
                root,
                candidate_id,
                comparison="adds",
                summary="补充说明。",
                target_knowledge_id="K-ORDER",
            )
            plan_id = yaml.safe_load(plan.read_text(encoding="utf-8"))["plan_id"]

            current = patch_plan_context(root, plan_id)
            self.assertFalse(current["stale"])
            evidence_text = current["evidence"][0]["text"]
            correct_evidence(
                root,
                evidence_id,
                new_text=evidence_text + "\n经复核增加一个限定条件。",
                reason="新增人工核对结果",
                verified_by="demo-owner",
            )
            stale = patch_plan_context(root, plan_id)
            self.assertTrue(stale["stale"])
            self.assertEqual(stale["evidence_stale"][0]["evidence_id"], evidence_id)

            proposed = Path(td) / "proposal.md"
            proposed.write_text(
                """---
id: K-ORDER
type: rule
status: draft
title: 证据变化测试
owner: demo
confidence: unknown
summary: 示例
tags: []
related: []
evidence: []
---
# 证据变化测试
内容
""",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "evidence changed"):
                apply_patch_plan(root, plan_id, proposed)

    def test_new_plan_rejects_existing_knowledge_id(self):
        with TemporaryDirectory() as td:
            root = Path(td) / "kb"
            init_team(root, "demo-team")
            self._knowledge(root, "K-ORDER")
            evidence_id = self._evidence(root)
            candidate = create_candidate(
                root,
                proposed_id="K-ORDER",
                title="重复 ID 候选",
                knowledge_type="rule",
                statement="试图用 new 创建已有 ID。",
            )
            candidate_id = yaml.safe_load(candidate.read_text(encoding="utf-8"))["candidate_id"]
            bind_evidence(root, evidence_id, target_kind="candidate", target_id=candidate_id, relation="supports")
            with self.assertRaisesRegex(ValueError, "already exists"):
                create_patch_plan(
                    root,
                    candidate_id,
                    comparison="new",
                    summary="不应创建。",
                    target_path="wiki/business/orders/new-rule.md",
                )

    def _git(self, repo: Path, *args: str) -> str:
        cp = subprocess.run(["git", "-C", str(repo), *args], text=True, capture_output=True, check=True)
        return cp.stdout.strip()

    def test_git_connector_checkpoint_rename_modify_delete(self):
        with TemporaryDirectory() as td:
            base = Path(td)
            project = base / "project"
            project.mkdir()
            self._git(project, "init", "-q")
            self._git(project, "config", "user.email", "demo@example.com")
            self._git(project, "config", "user.name", "Demo")
            (project / "docs").mkdir()
            (project / "docs/a.md").write_text("# A\n第一版\n", encoding="utf-8")
            self._git(project, "add", ".")
            self._git(project, "commit", "-qm", "initial")
            commit1 = self._git(project, "rev-parse", "HEAD")

            root = base / "kb"
            init_team(root, "demo-team")
            create_git_connector(
                root,
                "project_a",
                repository_id="project-a",
                include_paths=["docs"],
                logical_root="项目A",
                auto_intake=True,
            )
            first = sync_git_connector(root, "project_a", project, owner="demo")
            self.assertEqual(first["checkpoint"], commit1)
            state1 = connector_status(root, "project_a")
            source_id = state1["tracked"]["docs/a.md"]
            self.assertEqual(first["counts"]["add"], 1)

            self._git(project, "mv", "docs/a.md", "docs/b.md")
            self._git(project, "commit", "-qm", "rename")
            commit2 = self._git(project, "rev-parse", "HEAD")
            second = sync_git_connector(root, "project_a", project, owner="demo")
            state2 = connector_status(root, "project_a")
            self.assertEqual(second["checkpoint"], commit2)
            self.assertNotIn("docs/a.md", state2["tracked"])
            self.assertEqual(state2["tracked"]["docs/b.md"], source_id)

            pkg = next(
                p.parent for p in (root / "sources").rglob("source.yml")
                if yaml.safe_load(p.read_text(encoding="utf-8"))["source_id"] == source_id
            )
            meta2 = yaml.safe_load((pkg / "source.yml").read_text(encoding="utf-8"))
            self.assertEqual(meta2["origin"]["upstream_id"], "project-a:docs/b.md")
            self.assertEqual(meta2["origin"]["logical_path"], "项目A/docs/b.md")

            (project / "docs/b.md").write_text("# B\n第二版，新增条件。\n", encoding="utf-8")
            self._git(project, "add", ".")
            self._git(project, "commit", "-qm", "modify")
            commit3 = self._git(project, "rev-parse", "HEAD")
            third = sync_git_connector(root, "project_a", project, owner="demo")
            self.assertEqual(third["checkpoint"], commit3)
            self.assertEqual(connector_status(root, "project_a")["tracked"]["docs/b.md"], source_id)
            meta3 = yaml.safe_load((pkg / "source.yml").read_text(encoding="utf-8"))
            self.assertEqual(meta3["source_id"], source_id)
            self.assertGreaterEqual(len(meta3["revisions"]), 1)
            self.assertIsNone(third["events"][0]["refresh"]["change_id"])

            (project / "docs/b.md").unlink()
            self._git(project, "add", "-A")
            self._git(project, "commit", "-qm", "delete")
            commit4 = self._git(project, "rev-parse", "HEAD")
            fourth = sync_git_connector(root, "project_a", project, owner="demo")
            state4 = connector_status(root, "project_a")
            self.assertEqual(fourth["checkpoint"], commit4)
            self.assertNotIn("docs/b.md", state4["tracked"])
            self.assertEqual(state4["retired"]["docs/b.md"], source_id)
            meta4 = yaml.safe_load((pkg / "source.yml").read_text(encoding="utf-8"))
            self.assertEqual(meta4["status"], "deleted-upstream")
            self.assertIsNone(fourth["events"][0]["deletion"]["change_id"])

            no_change = sync_git_connector(root, "project_a", project, owner="demo")
            self.assertFalse(no_change["changed"])
            self.assertEqual(no_change["events"], [])

    def test_git_rename_out_of_scope_is_not_upstream_delete(self):
        with TemporaryDirectory() as td:
            base = Path(td)
            project = base / "project"
            project.mkdir()
            self._git(project, "init", "-q")
            self._git(project, "config", "user.email", "demo@example.com")
            self._git(project, "config", "user.name", "Demo")
            (project / "docs").mkdir()
            (project / "archive").mkdir()
            (project / "docs/a.md").write_text("# A\n内容\n", encoding="utf-8")
            self._git(project, "add", ".")
            self._git(project, "commit", "-qm", "initial")

            root = base / "kb"
            init_team(root, "demo-team")
            create_git_connector(
                root,
                "scope_test",
                repository_id="project-a",
                include_paths=["docs"],
            )
            sync_git_connector(root, "scope_test", project)
            source_id = connector_status(root, "scope_test")["tracked"]["docs/a.md"]

            self._git(project, "mv", "docs/a.md", "archive/a.md")
            self._git(project, "commit", "-qm", "move out of scope")
            result = sync_git_connector(root, "scope_test", project)
            self.assertEqual(result["counts"]["scope-remove"], 1)
            state = connector_status(root, "scope_test")
            self.assertNotIn("docs/a.md", state["tracked"])
            self.assertEqual(state["retired"]["docs/a.md"], source_id)

            pkg = next(
                p.parent for p in (root / "sources").rglob("source.yml")
                if yaml.safe_load(p.read_text(encoding="utf-8"))["source_id"] == source_id
            )
            meta = yaml.safe_load((pkg / "source.yml").read_text(encoding="utf-8"))
            self.assertEqual(meta["status"], "out-of-scope")
            self.assertNotIn("deleted_upstream_commit", meta)



if __name__ == "__main__":
    unittest.main()
