from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib
import json
import unittest
import yaml

from team_wiki.core import index_workspace, init_team, register_source
from team_wiki.evidence import bind_evidence, correct_evidence, list_bindings, read_evidence
from team_wiki.impact import refresh_source
from team_wiki.intake import intake_source, source_pipeline_status


class V04Tests(unittest.TestCase):
    def test_upstream_identity_is_stable_across_content_revision(self):
        with TemporaryDirectory() as td:
            root = Path(td) / "kb"
            init_team(root, "demo-team")
            v1 = Path(td) / "renamed-local-copy.md"
            v1.write_text("# 规范\n第一版", encoding="utf-8")
            pkg = register_source(
                root,
                v1,
                "订单规范",
                connector_id="git",
                upstream_id="project-a:docs/order.md",
                logical_path="订单系统/接口规范/订单",
            )
            meta = yaml.safe_load((pkg / "source.yml").read_text(encoding="utf-8"))
            sid = meta["source_id"]
            self.assertEqual(meta["origin"]["identity_mode"], "upstream")
            self.assertEqual(meta["origin"]["logical_path"], "订单系统/接口规范/订单")

            duplicate_name = Path(td) / "another-name.md"
            duplicate_name.write_text("# 规范\n第一版", encoding="utf-8")
            same = register_source(
                root,
                duplicate_name,
                "订单规范",
                connector_id="git",
                upstream_id="project-a:docs/order.md",
                logical_path="订单系统/接口规范/订单",
            )
            self.assertEqual(same, pkg)

            v2 = Path(td) / "v2.md"
            v2.write_text("# 规范\n第二版，增加限制", encoding="utf-8")
            with self.assertRaises(ValueError):
                register_source(
                    root,
                    v2,
                    "订单规范",
                    connector_id="git",
                    upstream_id="project-a:docs/order.md",
                )
            result = refresh_source(root, sid, v2, owner="demo")
            self.assertTrue(result["changed"])
            meta2 = yaml.safe_load((pkg / "source.yml").read_text(encoding="utf-8"))
            self.assertEqual(meta2["source_id"], sid)
            self.assertEqual(meta2["content_sha256"], hashlib.sha256(v2.read_bytes()).hexdigest())

    def test_structured_evidence_keeps_processing_and_locator(self):
        with TemporaryDirectory() as td:
            root = Path(td) / "kb"
            init_team(root, "demo-team")
            src = Path(td) / "spec.md"
            src.write_text(
                "# 订单导入\n\n## 联系电话\n正式提交前必须补齐联系电话。\n\n"
                "## 失败处理\n导入失败应保留失败原因。\n",
                encoding="utf-8",
            )
            pkg = register_source(
                root,
                src,
                "订单导入规范",
                connector_id="git",
                upstream_id="project-a:docs/import.md",
                logical_path="订单系统/接口规范/批量导入",
            )
            source_id = yaml.safe_load((pkg / "source.yml").read_text(encoding="utf-8"))["source_id"]
            intake = intake_source(root, source_id, max_chars=500)
            manifest = json.loads((intake / "manifest.json").read_text(encoding="utf-8"))
            processing = yaml.safe_load((intake / "processing.yml").read_text(encoding="utf-8"))

            self.assertEqual(manifest["version"], 2)
            self.assertEqual(processing["state"], "completed")
            self.assertEqual(processing["parser"]["version"], "0.4.0")
            self.assertEqual(manifest["source_revision"], yaml.safe_load((pkg / "source.yml").read_text(encoding="utf-8"))["content_sha256"])
            self.assertTrue(all(row.get("evidence_id") for row in manifest["chunks"]))
            self.assertTrue(all(row["locator"]["char_end"] > row["locator"]["char_start"] for row in manifest["chunks"]))
            self.assertTrue(any("联系电话" in row["locator"]["heading_path"] for row in manifest["chunks"]))
            self.assertTrue(all(row["locator"]["logical_path"] == "订单系统/接口规范/批量导入" for row in manifest["chunks"]))

            source_meta = yaml.safe_load((pkg / "source.yml").read_text(encoding="utf-8"))
            self.assertEqual(source_meta["status"], "parsed")
            self.assertEqual(source_meta["latest_intake_id"], manifest["intake_id"])
            self.assertEqual(source_meta["latest_processing_id"], processing["processing_id"])

    def test_evidence_correction_preserves_raw_parser_output_and_binding(self):
        with TemporaryDirectory() as td:
            root = Path(td) / "kb"
            init_team(root, "demo-team")
            src = Path(td) / "note.md"
            src.write_text("# 规则\n联系电话非必填。", encoding="utf-8")
            pkg = register_source(root, src, "规则说明")
            source_id = yaml.safe_load((pkg / "source.yml").read_text(encoding="utf-8"))["source_id"]
            intake = intake_source(root, source_id, max_chars=500)
            manifest = json.loads((intake / "manifest.json").read_text(encoding="utf-8"))
            row = manifest["chunks"][0]
            evidence_id = row["evidence_id"]
            raw_path = root / row["path"]
            raw_before = raw_path.read_text(encoding="utf-8")

            corrected = raw_before.replace("非必填", "必填")
            correction = correct_evidence(
                root,
                evidence_id,
                new_text=corrected,
                reason="核对原始截图，OCR 多识别了“非”字",
                verified_by="demo-owner",
            )
            self.assertTrue(correction.exists())
            self.assertEqual(raw_path.read_text(encoding="utf-8"), raw_before)

            current = read_evidence(root, evidence_id)
            self.assertIn("联系电话必填", current["current_text"])
            self.assertNotEqual(current["raw_sha256"], current["current_sha256"])
            self.assertEqual(len(current["correction_ids"]), 1)

            binding = bind_evidence(
                root,
                evidence_id,
                target_kind="candidate",
                target_id="CAND-ORDER-PHONE",
                relation="supports",
                note="支持候选规则的字段要求",
            )
            self.assertTrue(binding.exists())
            rows = list_bindings(root, target_id="CAND-ORDER-PHONE")
            self.assertEqual(rows[0]["evidence_id"], evidence_id)
            self.assertEqual(rows[0]["relation"], "supports")

    def test_source_status_and_evidence_binding_drive_impact(self):
        with TemporaryDirectory() as td:
            root = Path(td) / "kb"
            init_team(root, "demo-team")
            src = Path(td) / "policy.md"
            src.write_text("# 规则\\n第一版规则。", encoding="utf-8")
            pkg = register_source(
                root,
                src,
                "规则来源",
                connector_id="git",
                upstream_id="project-a:docs/policy.md",
                logical_path="项目A/业务规则",
            )
            source_id = yaml.safe_load((pkg / "source.yml").read_text(encoding="utf-8"))["source_id"]
            intake = intake_source(root, source_id, max_chars=500)
            manifest = json.loads((intake / "manifest.json").read_text(encoding="utf-8"))
            evidence_id = manifest["chunks"][0]["evidence_id"]

            k = root / "wiki/business/demo/rule.md"
            k.parent.mkdir(parents=True, exist_ok=True)
            (k.parent / "INDEX.md").write_text("# demo\\n", encoding="utf-8")
            k.write_text(
                """---
id: K-BIND
type: rule
status: draft
title: 通过证据绑定关联的规则
owner: demo
confidence: unknown
summary: 用于验证 evidence binding 的影响传播。
tags: [demo]
related: []
evidence: []
---
# 通过证据绑定关联的规则
""",
                encoding="utf-8",
            )
            bind_evidence(
                root,
                evidence_id,
                target_kind="knowledge",
                target_id="K-BIND",
                relation="supports",
            )

            status = source_pipeline_status(root, source_id)
            self.assertEqual(status["acquisition"]["state"], "acquired")
            self.assertEqual(status["processing"]["state"], "completed")
            self.assertEqual(status["evidence"]["state"], "ready")
            self.assertEqual(status["indexing"]["state"], "not-indexed")

            v2 = Path(td) / "policy-v2.md"
            v2.write_text("# 规则\\n第二版规则，增加条件。", encoding="utf-8")
            result = refresh_source(root, source_id, v2, owner="demo")
            affected = {x["knowledge_id"]: x for x in result["affected"]}
            self.assertIn("K-BIND", affected)
            self.assertIn("evidence-binding", affected["K-BIND"]["basis"])


    def test_source_index_exposes_logical_origin_without_moving_source(self):
        with TemporaryDirectory() as td:
            root = Path(td) / "kb"
            init_team(root, "demo-team")
            src = Path(td) / "meeting.md"
            src.write_text("评审记录", encoding="utf-8")
            pkg = register_source(
                root,
                src,
                "评审记录",
                connector_id="git",
                upstream_id="project-a:docs/review.md",
                logical_path="项目A/评审/订单导入",
            )
            before = pkg
            index_workspace(root)
            text = (root / "sources/INDEX.md").read_text(encoding="utf-8")
            self.assertIn("connector=git", text)
            self.assertIn("path=项目A/评审/订单导入", text)
            self.assertEqual(pkg, before)


if __name__ == "__main__":
    unittest.main()
