from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import yaml

from team_wiki.core import init_team, parse_frontmatter, register_source
from team_wiki.impact import refresh_source
from team_wiki.intake import apply_disposition, audit_intake, intake_source, intake_status
from team_wiki.review import resolve_review, upsert_review


class V03Tests(unittest.TestCase):
    def _knowledge(self, root: Path, kid: str, source_id: str):
        p = root / "wiki/business/demo/rule.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        (p.parent / "INDEX.md").write_text("# demo\n", encoding="utf-8")
        meta = {
            "id": kid,
            "type": "rule",
            "status": "draft",
            "title": "示例来源依赖规则",
            "owner": "demo-owner",
            "confidence": "unknown",
            "summary": "用于验证来源变化影响传播。",
            "tags": ["demo"],
            "related": [],
            "evidence": [{"source_id": source_id}],
        }
        p.write_text(
            "---\n" + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False)
            + "---\n# 示例来源依赖规则\n",
            encoding="utf-8",
        )
        return p

    def test_review_reopens_only_for_new_evidence_version(self):
        with TemporaryDirectory() as td:
            root = Path(td) / "kb"
            init_team(root, "demo-team")
            path = upsert_review(
                root,
                kind="confirm",
                title="同一个待确认问题",
                description="需要确认。",
                owner="demo-owner",
                scope_key="demo",
                evidence_version="v1",
            )
            meta, _ = parse_frontmatter(path)
            rid = meta["review_id"]
            resolve_review(root, rid, action="confirmed", note="已确认", evidence_version="v1")

            same = upsert_review(
                root,
                kind="confirm",
                title="同一个待确认问题",
                description="再次遇到相同问题。",
                owner="demo-owner",
                scope_key="demo",
                evidence_version="v1",
            )
            same_meta, _ = parse_frontmatter(same)
            self.assertEqual(same_meta["state"], "resolved")

            reopened = upsert_review(
                root,
                kind="confirm",
                title="同一个待确认问题",
                description="新证据出现，需要重新检查。",
                owner="demo-owner",
                scope_key="demo",
                evidence_version="v2",
                observation="新的来源版本",
            )
            reopened_meta, _ = parse_frontmatter(reopened)
            self.assertEqual(reopened_meta["review_id"], rid)
            self.assertEqual(reopened_meta["state"], "open")
            self.assertIsNone(reopened_meta["resolution"])
            self.assertTrue(any(x.get("event") == "reopened" for x in reopened_meta["history"]))

    def test_text_intake_requires_disposition_for_every_chunk(self):
        with TemporaryDirectory() as td:
            root = Path(td) / "kb"
            init_team(root, "demo-team")
            source_file = Path(td) / "note.md"
            source_file.write_text(
                "# 第一节\n" + ("A" * 650) + "\n\n# 第二节\n" + ("B" * 650),
                encoding="utf-8",
            )
            pkg = register_source(root, source_file, "长资料")
            source_id = yaml.safe_load((pkg / "source.yml").read_text(encoding="utf-8"))["source_id"]

            intake = intake_source(root, source_id, max_chars=500)
            intake_id = intake.name
            ledger = intake_status(root, intake_id)
            self.assertGreaterEqual(ledger["summary"]["total"], 2)
            self.assertEqual(ledger["review_status"], "pending")
            self.assertFalse(audit_intake(root, intake_id)["complete"])

            for i, chunk in enumerate(ledger["chunks"]):
                if i == 0:
                    apply_disposition(
                        root, intake_id, chunk["id"],
                        status="integrated",
                        note="已整合到示例知识",
                        knowledge_ids=["K-DEMO"],
                    )
                else:
                    apply_disposition(
                        root, intake_id, chunk["id"],
                        status="skipped",
                        note="重复或无长期价值",
                    )

            audit = audit_intake(root, intake_id)
            self.assertTrue(audit["complete"])
            self.assertEqual(audit["pending"], [])
            self.assertEqual(intake_status(root, intake_id)["review_status"], "complete")

    def test_source_refresh_creates_change_and_reopens_review(self):
        with TemporaryDirectory() as td:
            root = Path(td) / "kb"
            init_team(root, "demo-team")
            original = Path(td) / "source.md"
            original.write_text("第一版资料", encoding="utf-8")
            pkg = register_source(root, original, "示例来源")
            source_meta = yaml.safe_load((pkg / "source.yml").read_text(encoding="utf-8"))
            source_id = source_meta["source_id"]
            self._knowledge(root, "K-DEMO", source_id)

            v2 = Path(td) / "source-v2.md"
            v2.write_text("第二版资料，增加限制条件", encoding="utf-8")
            result = refresh_source(root, source_id, v2, owner="demo-owner")
            self.assertTrue(result["changed"])
            self.assertEqual(result["affected"][0]["knowledge_id"], "K-DEMO")
            self.assertTrue(list((root / "changes").rglob(f"{result['change_id']}.md")))
            review_path = next((root / "changes/reviews").rglob(f"{result['review_id']}.md"))
            review_meta, _ = parse_frontmatter(review_path)
            self.assertEqual(review_meta["state"], "open")
            self.assertTrue((pkg / result["archived_revision"]).exists())

            resolve_review(
                root,
                result["review_id"],
                action="reviewed",
                note="第二版已完成复核",
                evidence_version=result["content_sha256"],
            )
            v3 = Path(td) / "source-v3.md"
            v3.write_text("第三版资料，再次调整条件", encoding="utf-8")
            result2 = refresh_source(root, source_id, v3, owner="demo-owner")
            self.assertEqual(result2["review_id"], result["review_id"])
            meta2, _ = parse_frontmatter(review_path)
            self.assertEqual(meta2["state"], "open")
            self.assertTrue(any(x.get("event") == "reopened" for x in meta2["history"]))


if __name__ == "__main__":
    unittest.main()
