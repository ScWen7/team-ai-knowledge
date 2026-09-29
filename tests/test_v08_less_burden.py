"""V0.8 tests: usage-burden reduction.

These tests pin the four simplifications:

1. ``intake-decide`` decides a whole intake in one call instead of one
   ``intake-apply`` per chunk.
2. ``source_pipeline_status`` no longer reports an ``indexing`` dimension that
   could never leave ``not-indexed`` (LanceDB is not implemented).
3. ``patch-plan-direct`` plans a change without a separate Candidate step; the
   Candidate record still exists so downstream contracts are unchanged.
4. ``audit_intake`` actually gates a later step, so the per-chunk ledger the
   fast path writes is consumed by something.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import yaml

from team_wiki.candidate import apply_patch_plan, patch_plan_context, plan_patch
from team_wiki.core import init_team, register_source
from team_wiki.intake import (
    audit_intake,
    decide_intake,
    intake_source,
    intake_status,
    source_pipeline_status,
)


def _build_doc(section_count: int = 12) -> str:
    lines = ["# 订单导入规则", ""]
    for i in range(section_count):
        lines.append(
            f"第{i + 1}节说明订单导入在业务线上的具体约束，"
            "包括前置条件校验、字段映射规则、异常处理分支以及对应的责任人和审批要求。"
        )
        lines.append("")
    return "\n".join(lines)


DOC = _build_doc()


class V08Tests(unittest.TestCase):
    def _repo_with_doc(self, td: str, name: str = "rule.md") -> tuple[Path, str]:
        root = Path(td) / "kb"
        init_team(root, "team-knowledge")
        raw = Path(td) / name
        raw.write_text(DOC, encoding="utf-8")
        pkg = register_source(root, raw, "导入规则文档")
        source_id = str(yaml.safe_load((pkg / "source.yml").read_text(encoding="utf-8"))["source_id"])
        return root, source_id

    # --- Optimization 1: intake-decide ---

    def test_intake_decide_marks_kept_chunks_and_skips_the_rest(self):
        with TemporaryDirectory() as td:
            root, source_id = self._repo_with_doc(td)
            intake_id = intake_source(root, source_id, max_chars=500).name
            ledger = intake_status(root, intake_id)
            chunk_ids = [c["id"] for c in ledger["chunks"]]
            self.assertGreater(len(chunk_ids), 1, "fixture should produce several chunks")

            result = decide_intake(root, intake_id, keep=[chunk_ids[0], chunk_ids[1]])

            self.assertEqual(result["review_status"], "complete")
            self.assertEqual(result["summary"]["integrated"], 2)
            self.assertEqual(result["summary"]["pending"], 0)
            self.assertEqual(result["summary"]["skipped"], len(chunk_ids) - 2)
            kept = [c for c in result["chunks"] if c["status"] == "integrated"]
            self.assertEqual([c["id"] for c in kept], [chunk_ids[0], chunk_ids[1]])
            for chunk in result["chunks"]:
                if chunk["status"] == "skipped":
                    self.assertTrue((chunk["note"] or "").strip())

    def test_intake_decide_accepts_evidence_ids_and_attach_knowledge(self):
        with TemporaryDirectory() as td:
            root, source_id = self._repo_with_doc(td)
            intake_id = intake_source(root, source_id, max_chars=500).name
            ledger = intake_status(root, intake_id)
            target = ledger["chunks"][0]

            result = decide_intake(
                root,
                intake_id,
                keep_evidence=[target["evidence_id"]],
                knowledge={target["evidence_id"]: ["K-IMPORT"]},
            )

            kept = [c for c in result["chunks"] if c["status"] == "integrated"]
            self.assertEqual(len(kept), 1)
            self.assertEqual(kept[0]["knowledge_ids"], ["K-IMPORT"])

    def test_intake_decide_keep_all_leaves_nothing_pending(self):
        with TemporaryDirectory() as td:
            root, source_id = self._repo_with_doc(td)
            intake_id = intake_source(root, source_id, max_chars=500).name
            result = decide_intake(
                root, intake_id,
                keep=[c["id"] for c in intake_status(root, intake_id)["chunks"]],
                skip_rest=False,
            )
            self.assertEqual(result["summary"]["pending"], 0)

    def test_intake_decide_reset_returns_chunks_to_pending(self):
        with TemporaryDirectory() as td:
            root, source_id = self._repo_with_doc(td)
            intake_id = intake_source(root, source_id, max_chars=500).name
            first = intake_status(root, intake_id)["chunks"][0]["id"]
            decide_intake(root, intake_id, keep=[first])

            result = decide_intake(root, intake_id, reset=True)

            self.assertEqual(result["review_status"], "in-progress")
            self.assertTrue(all(c["status"] == "pending" for c in result["chunks"]))

    def test_intake_decide_requires_at_least_one_keep(self):
        with TemporaryDirectory() as td:
            root, source_id = self._repo_with_doc(td)
            intake_id = intake_source(root, source_id, max_chars=500).name
            with self.assertRaises(ValueError):
                decide_intake(root, intake_id)

    def test_intake_decide_rejects_unknown_chunk(self):
        with TemporaryDirectory() as td:
            root, source_id = self._repo_with_doc(td)
            intake_id = intake_source(root, source_id, max_chars=500).name
            with self.assertRaises(KeyError):
                decide_intake(root, intake_id, keep=["NOPE-0001"])

    # --- Optimization 4 (enforcement): audit is a real gate ---

    def test_audit_gate_passes_after_decide_and_blocks_before(self):
        with TemporaryDirectory() as td:
            root, source_id = self._repo_with_doc(td)
            intake_id = intake_source(root, source_id, max_chars=500).name

            self.assertFalse(audit_intake(root, intake_id)["complete"])

            ledger = intake_status(root, intake_id)
            decide_intake(root, intake_id, keep=[ledger["chunks"][0]["id"]])

            self.assertTrue(audit_intake(root, intake_id)["complete"])

    def test_audit_gate_rejects_chunks_skipped_without_reason(self):
        with TemporaryDirectory() as td:
            root, source_id = self._repo_with_doc(td)
            intake_id = intake_source(root, source_id, max_chars=500).name
            path = root / ".knowledge/records/intake" / intake_id / "review-progress.yml"
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            for chunk in data["chunks"]:
                chunk["status"] = "skipped"
                chunk["note"] = None
            data["summary"] = {"total": len(data["chunks"]), "pending": 0}
            data["review_status"] = "complete"
            path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")

            report = audit_intake(root, intake_id)

            self.assertFalse(report["complete"])
            self.assertTrue(report["invalid_skips"])


class V08PipelineStatusTests(unittest.TestCase):
    # --- Optimization 2: no always-false indexing dimension ---

    def _prepared(self, td: str) -> tuple[Path, str]:
        root = Path(td) / "kb"
        init_team(root, "team-knowledge")
        raw = Path(td) / "rule.md"
        raw.write_text(DOC, encoding="utf-8")
        pkg = register_source(root, raw, "导入规则文档")
        source_id = str(yaml.safe_load((pkg / "source.yml").read_text(encoding="utf-8"))["source_id"])
        return root, source_id

    def test_source_status_never_reports_indexing(self):
        with TemporaryDirectory() as td:
            root, source_id = self._prepared(td)
            before = source_pipeline_status(root, source_id)
            self.assertNotIn("indexing", before)

            intake_source(root, source_id, max_chars=500)
            after = source_pipeline_status(root, source_id)

            self.assertNotIn("indexing", after)
            self.assertEqual(after["processing"]["state"], "completed")
            self.assertEqual(after["evidence"]["state"], "ready")
            self.assertGreater(after["evidence"]["count"], 0)

    def test_evidence_read_does_not_report_index_state(self):
        from team_wiki.evidence import read_evidence

        with TemporaryDirectory() as td:
            root, source_id = self._prepared(td)
            intake_id = intake_source(root, source_id, max_chars=500).name
            evidence_id = intake_status(root, intake_id)["chunks"][0]["evidence_id"]

            evidence = read_evidence(root, evidence_id)

            self.assertNotIn("index_state", evidence)
            self.assertEqual(evidence["source_id"], source_id)

    def test_manifest_chunks_do_not_persist_index_state(self):
        import json

        with TemporaryDirectory() as td:
            root, source_id = self._prepared(td)
            intake_id = intake_source(root, source_id, max_chars=500).name
            manifest = json.loads(
                (root / ".knowledge/records/intake" / intake_id / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertTrue(manifest["chunks"])
            for chunk in manifest["chunks"]:
                self.assertNotIn("index_state", chunk)


class V08PatchPlanDirectTests(unittest.TestCase):
    # --- Optimization 3: patch-plan-direct ---

    def _repo(self, td: str) -> Path:
        root = Path(td) / "kb"
        init_team(root, "team-knowledge")
        path = root / "wiki/business/orders/rule.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        (path.parent / "INDEX.md").write_text("# orders\n", encoding="utf-8")
        path.write_text(
            """---
id: K-ORDER
type: rule
status: draft
title: 订单导入规则
owner: demo
confidence: unknown
summary: 导入规则。
tags: [订单]
related: []
---

# 订单导入规则

导入必须幂等。
""",
            )
        return root

    def _evidence(self, root: Path, td: str) -> str:
        raw = Path(td) / "evidence.md"
        raw.write_text(DOC, encoding="utf-8")
        pkg = register_source(root, raw, "证据文档")
        source_id = str(yaml.safe_load((pkg / "source.yml").read_text(encoding="utf-8"))["source_id"])
        intake_id = intake_source(root, source_id, max_chars=500).name
        return intake_status(root, intake_id)["chunks"][0]["evidence_id"]

    def test_direct_plan_creates_candidate_record_and_plan(self):
        with TemporaryDirectory() as td:
            root = self._repo(td)
            evidence_id = self._evidence(root, td)

            result = plan_patch(
                root,
                knowledge_id="K-ORDER",
                comparison="narrows",
                summary="补充幂等的适用条件",
                statement="导入必须幂等，且仅在同订单号下成立。",
                evidence_ids=[evidence_id],
            )

            self.assertTrue(result["candidate_id"].startswith("CAND-"))
            self.assertTrue(result["plan_id"].startswith("PLAN-"))
            plan = result["plan"]
            self.assertEqual(plan["comparison"], "narrows")
            self.assertEqual(plan["target"]["knowledge_id"], "K-ORDER")
            self.assertTrue(plan["target"]["base_sha256"])
            self.assertEqual(plan["status"], "proposed")
            self.assertTrue(plan["change_id"])
            self.assertEqual([e["evidence_id"] for e in plan["evidence"]], [evidence_id])

    def test_direct_plan_candidate_is_bound_to_evidence(self):
        from team_wiki.candidate import candidate_context

        with TemporaryDirectory() as td:
            root = self._repo(td)
            evidence_id = self._evidence(root, td)

            result = plan_patch(
                root,
                knowledge_id="K-ORDER",
                comparison="narrows",
                summary="收窄适用范围",
                statement="只在批量导入场景幂等。",
                evidence_ids=[evidence_id],
            )

            ctx = candidate_context(root, result["candidate_id"])
            self.assertEqual(len(ctx["evidence"]), 1)
            self.assertEqual(ctx["evidence"][0]["evidence_id"], evidence_id)
            self.assertEqual(ctx["candidate"]["proposed_id"], "K-ORDER")

    def test_direct_plan_still_supports_apply_and_stale_detection(self):
        with TemporaryDirectory() as td:
            root = self._repo(td)
            evidence_id = self._evidence(root, td)
            result = plan_patch(
                root,
                knowledge_id="K-ORDER",
                comparison="narrows",
                summary="收窄",
                statement="仅批量导入幂等。",
                evidence_ids=[evidence_id],
            )
            target = root / "wiki/business/orders/rule.md"
            body = target.read_text(encoding="utf-8").replace("导入必须幂等。", "仅批量导入幂等。")
            proposed = Path(td) / "revision.md"
            proposed.write_text(body, encoding="utf-8")

            applied = apply_patch_plan(root, result["plan_id"], proposed)

            self.assertEqual(applied, target)
            self.assertIn("仅批量导入幂等", applied.read_text(encoding="utf-8"))

            # Re-applying an already-applied plan is an idempotent no-op.
            proposed2 = Path(td) / "revision2.md"
            proposed2.write_text(body, encoding="utf-8")
            self.assertEqual(apply_patch_plan(root, result["plan_id"], proposed2), target)

    def test_direct_plan_detects_target_drift_after_planning(self):
        with TemporaryDirectory() as td:
            root = self._repo(td)
            evidence_id = self._evidence(root, td)
            result = plan_patch(
                root,
                knowledge_id="K-ORDER",
                comparison="narrows",
                summary="收窄",
                statement="仅批量导入幂等。",
                evidence_ids=[evidence_id],
            )
            # Someone else edits the knowledge between planning and applying.
            target = root / "wiki/business/orders/rule.md"
            target.write_text(
                target.read_text(encoding="utf-8") + "\n他人并发修改。\n", encoding="utf-8"
            )
            proposed = Path(td) / "revision.md"
            proposed.write_text(
                "---\nid: K-ORDER\n---\n\n# 订单导入规则\n\n仅批量导入幂等。\n",
                encoding="utf-8",
            )

            with self.assertRaises(ValueError) as ctx:
                apply_patch_plan(root, result["plan_id"], proposed)

            self.assertIn("stale", str(ctx.exception))

    def test_direct_plan_rejects_missing_evidence_and_statement(self):
        with TemporaryDirectory() as td:
            root = self._repo(td)
            with self.assertRaises(ValueError):
                plan_patch(root, knowledge_id="K-ORDER", comparison="narrows",
                           summary="s", statement="x", evidence_ids=[])
            with self.assertRaises(ValueError):
                plan_patch(root, knowledge_id="K-ORDER", comparison="narrows",
                           summary="s", statement="  ", evidence_ids=["EVD-X"])

    def test_direct_plan_does_not_infer_comparison(self):
        with TemporaryDirectory() as td:
            root = self._repo(td)
            evidence_id = self._evidence(root, td)
            with self.assertRaises(ValueError):
                plan_patch(root, knowledge_id="K-ORDER", comparison="looks-wrong",
                           summary="s", statement="x", evidence_ids=[evidence_id])

    def test_direct_plan_context_matches_explicit_candidate_flow(self):
        with TemporaryDirectory() as td:
            root = self._repo(td)
            evidence_id = self._evidence(root, td)
            result = plan_patch(
                root,
                knowledge_id="K-ORDER",
                comparison="adds",
                summary="新增异常处理",
                statement="导入异常需回滚。",
                evidence_ids=[evidence_id],
            )
            ctx = patch_plan_context(root, result["plan_id"])
            self.assertEqual(ctx["plan"]["plan_id"], result["plan_id"])
            self.assertTrue(ctx["target_content"].startswith("---"))
            self.assertFalse(ctx["stale"])
            self.assertTrue(ctx["evidence"])
            self.assertTrue(ctx["instruction"])


if __name__ == "__main__":
    unittest.main()
