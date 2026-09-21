from pathlib import Path
from tempfile import TemporaryDirectory
import json
import subprocess
import unittest

import yaml

from team_wiki.batch import batch_context, create_candidate_batch
from team_wiki.candidate import apply_patch_plan, create_candidate, create_patch_plan
from team_wiki.core import (
    adopt_knowledge,
    finalize_work,
    init_team,
    observe_knowledge,
    prepare_work,
    register_source,
)
from team_wiki.dependency import dependency_impact
from team_wiki.evidence import bind_evidence
from team_wiki.intake import intake_source
from team_wiki.publication import adoption_status, record_publication
from team_wiki.review import resolve_review


class V06Tests(unittest.TestCase):
    def _git(self, repo: Path, *args: str) -> str:
        cp = subprocess.run(
            ["git", "-C", str(repo), *args],
            text=True,
            capture_output=True,
            check=True,
        )
        return cp.stdout.strip()

    def _evidence(self, root: Path, name: str, text: str) -> str:
        source = root.parent / name
        source.write_text(text, encoding="utf-8")
        pkg = register_source(root, source, name)
        source_id = yaml.safe_load(
            (pkg / "source.yml").read_text(encoding="utf-8")
        )["source_id"]
        intake = intake_source(root, source_id, max_chars=500)
        manifest = json.loads((intake / "manifest.json").read_text(encoding="utf-8"))
        return manifest["chunks"][0]["evidence_id"]

    def _knowledge_graph(self, root: Path) -> None:
        a = root / "wiki/business/orders/contact-phone.md"
        a.parent.mkdir(parents=True, exist_ok=True)
        (a.parent / "INDEX.md").write_text("# orders\n", encoding="utf-8")
        a.write_text(
            """---
id: K-A
type: rule
status: draft
title: 订单联系电话规则
owner: order-owner
confidence: unknown
summary: 联系电话必填。
tags: [订单]
related: []
evidence: []
---
# 订单联系电话规则

联系电话必填。
""",
            encoding="utf-8",
        )

        b = root / "wiki/business/orders/import-guide.md"
        b.write_text(
            """---
id: K-B
type: guide
status: draft
title: 订单导入指南
owner: order-owner
confidence: unknown
summary: 订单导入处理方法。
tags: [订单, 导入]
depends_on: [K-A]
related: []
evidence: []
---
# 订单导入指南

按订单联系电话规则校验。
""",
            encoding="utf-8",
        )

        (root / "wiki/OVERVIEW.md").write_text(
            """---
title: 订单域总体认识
depends_on: [K-B]
---
# Overview

订单导入能力依赖导入指南。
""",
            encoding="utf-8",
        )

    def test_multi_source_batch_preserves_all_evidence(self):
        with TemporaryDirectory() as td:
            root = Path(td) / "kb"
            init_team(root, "demo-team")
            e1 = self._evidence(
                root,
                "review-1.md",
                "# 电话规则\n草稿导入阶段联系电话可以为空。\n",
            )
            e2 = self._evidence(
                root,
                "review-2.md",
                "# 电话规则\n正式提交前联系电话必须补齐。\n",
            )

            c1 = create_candidate(
                root,
                proposed_id="K-A",
                title="草稿阶段规则",
                knowledge_type="rule",
                statement="草稿导入阶段联系电话可以为空。",
            )
            c2 = create_candidate(
                root,
                proposed_id="K-A",
                title="正式提交规则",
                knowledge_type="rule",
                statement="正式提交前联系电话必须补齐。",
            )
            c1_id = yaml.safe_load(c1.read_text(encoding="utf-8"))["candidate_id"]
            c2_id = yaml.safe_load(c2.read_text(encoding="utf-8"))["candidate_id"]
            bind_evidence(
                root, e1,
                target_kind="candidate",
                target_id=c1_id,
                relation="limits",
            )
            bind_evidence(
                root, e2,
                target_kind="candidate",
                target_id=c2_id,
                relation="supports",
            )

            batch = create_candidate_batch(
                root,
                [c1_id, c2_id],
                title="订单联系电话按阶段校验",
                merged_statement="草稿可为空，正式提交前必须补齐。",
            )
            batch_id = yaml.safe_load(batch.read_text(encoding="utf-8"))["batch_id"]
            ctx = batch_context(root, batch_id)
            self.assertEqual(len(ctx["candidates"]), 2)
            self.assertEqual(len(ctx["merged_candidate"]["evidence"]), 2)
            self.assertEqual(
                {x["source_id"] for x in ctx["merged_candidate"]["evidence"]},
                {x["source_id"] for x in ctx["batch"]["evidence"]},
            )
            self.assertFalse(ctx["requires_semantic_review"])

    def test_patch_dependency_publish_and_adoption_loop(self):
        with TemporaryDirectory() as td:
            root = Path(td) / "kb"
            init_team(root, "team-knowledge")
            self._knowledge_graph(root)

            self._git(root, "init", "-q")
            self._git(root, "config", "user.email", "demo@example.com")
            self._git(root, "config", "user.name", "Demo")
            self._git(root, "add", ".")
            self._git(root, "commit", "-qm", "baseline")

            e1 = self._evidence(
                root,
                "source-a.md",
                "# 电话\n草稿导入阶段联系电话可以为空。\n",
            )
            e2 = self._evidence(
                root,
                "source-b.md",
                "# 电话\n正式提交前联系电话必须补齐。\n",
            )

            c1 = create_candidate(
                root,
                proposed_id="K-A",
                title="草稿阶段",
                knowledge_type="rule",
                statement="草稿导入阶段联系电话可以为空。",
                owner="order-owner",
            )
            c2 = create_candidate(
                root,
                proposed_id="K-A",
                title="提交阶段",
                knowledge_type="rule",
                statement="正式提交前联系电话必须补齐。",
                owner="order-owner",
            )
            c1_id = yaml.safe_load(c1.read_text(encoding="utf-8"))["candidate_id"]
            c2_id = yaml.safe_load(c2.read_text(encoding="utf-8"))["candidate_id"]
            bind_evidence(root, e1, target_kind="candidate", target_id=c1_id, relation="limits")
            bind_evidence(root, e2, target_kind="candidate", target_id=c2_id, relation="supports")

            batch = create_candidate_batch(
                root,
                [c1_id, c2_id],
                title="订单联系电话按阶段校验",
                merged_statement="草稿导入可为空；正式提交前必须补齐。",
                owner="order-owner",
            )
            merged_id = yaml.safe_load(batch.read_text(encoding="utf-8"))[
                "merged_candidate_id"
            ]

            plan = create_patch_plan(
                root,
                merged_id,
                comparison="narrows",
                summary="将全阶段必填收窄为正式提交前必填。",
                owner="order-owner",
                target_knowledge_id="K-A",
            )
            plan_data = yaml.safe_load(plan.read_text(encoding="utf-8"))
            proposed = Path(td) / "revised.md"
            proposed.write_text(
                """---
id: K-A
type: rule
status: draft
title: 订单联系电话按阶段校验
owner: order-owner
confidence: confirmed
summary: 草稿导入可为空，正式提交前必须补齐。
tags: [订单, 导入]
related: []
evidence: []
---
# 订单联系电话按阶段校验

- 草稿导入：联系电话可以为空。
- 正式提交前：联系电话必须补齐。
""",
                encoding="utf-8",
            )
            apply_patch_plan(root, plan_data["plan_id"], proposed)
            applied_plan = yaml.safe_load(plan.read_text(encoding="utf-8"))
            self.assertEqual(applied_plan["dependency_impact"]["count"], 2)
            self.assertTrue(applied_plan["dependency_review_id"])

            impact = dependency_impact(root, "K-A")
            self.assertEqual([x["id"] for x in impact["direct"]], ["K-B"])
            self.assertTrue(
                any(x["id"].startswith("VIEW:wiki/OVERVIEW.md") for x in impact["affected"])
            )

            with self.assertRaisesRegex(ValueError, "unresolved Reviews"):
                record_publication(
                    root,
                    plan_data["change_id"],
                    "K-A",
                    published_ref="HEAD",
                    adoption_requirement="review-required",
                )

            resolve_review(
                root,
                applied_plan["dependency_review_id"],
                action="checked",
                note="导入指南与 Overview 已复核，当前表述仍成立。",
                evidence_version=applied_plan["applied"]["content_sha256"],
            )

            self._git(root, "add", ".")
            self._git(root, "commit", "-qm", "publish staged knowledge revision")
            published_commit = self._git(root, "rev-parse", "HEAD")

            publication = record_publication(
                root,
                plan_data["change_id"],
                "K-A",
                published_ref="HEAD",
                adoption_requirement="review-required",
            )
            pub = yaml.safe_load(publication.read_text(encoding="utf-8"))
            self.assertEqual(pub["published_ref"], published_commit)

            work = prepare_work(
                root,
                "项目 B 使用新的订单联系电话规则",
                consumer_id="project-b",
            )
            work_id = work.stem
            adopted = adopt_knowledge(
                root,
                work_id,
                "K-A",
                "实现项目 B 的订单导入校验",
            )
            self.assertTrue(adopted["publication_match"])
            self.assertEqual(adopted["publication_id"], pub["publication_id"])
            self.assertEqual(adopted["adoption_requirement"], "review-required")

            observe_knowledge(
                root,
                work_id,
                "K-A",
                "supported-in-scope",
                "项目 B 的草稿和正式提交验证均符合新规则。",
            )
            finalized = finalize_work(root, work_id, owner="project-b")
            self.assertEqual(len(finalized["adoption_ids"]), 1)

            status = adoption_status(root, "K-A")
            self.assertEqual(status["publication"]["publication_id"], pub["publication_id"])
            self.assertEqual(status["consumer_count"], 1)
            self.assertEqual(status["consumers"], ["project-b"])
            self.assertEqual(
                status["adoptions"][0]["outcome"],
                "supported-in-scope",
            )


if __name__ == "__main__":
    unittest.main()
