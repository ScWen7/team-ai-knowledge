from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from team_wiki.core import create_change, doctor, index_workspace, init_team, register_source, search


class TeamWikiTests(unittest.TestCase):
    def test_vertical_slice(self):
        with TemporaryDirectory() as td:
            root = Path(td) / "kb"
            init_team(root, "demo-team")
            note = Path(td) / "订单导入评审纪要.md"
            note.write_text("订单导入阶段允许草稿缺少某字段。", encoding="utf-8")
            pkg = register_source(root, note, "订单导入评审纪要")
            self.assertTrue((pkg / "source.yml").exists())

            k = root / "wiki/business/orders/import"
            k.mkdir(parents=True)
            (k / "INDEX.md").write_text("# import\n", encoding="utf-8")
            (k / "rule.md").write_text(
                """---
id: RULE-ORDER-IMPORT
type: rule
status: draft
title: 订单导入字段规则
owner: demo
confidence: unknown
summary: 示例知识，不代表真实业务规则。
tags: [订单, 导入]
---
# 订单导入字段规则
示例正文。
""",
                encoding="utf-8",
            )

            create_change(root, "验证订单导入字段边界", "demo-owner")
            index_workspace(root)

            self.assertTrue(doctor(root).ok)
            self.assertEqual(search(root, "订单 导入")[0]["id"], "RULE-ORDER-IMPORT")
            self.assertIn(
                "订单导入评审",
                (root / "sources/INDEX.md").read_text(encoding="utf-8"),
            )
            self.assertIn(
                "验证订单导入字段边界",
                (root / "changes/INDEX.md").read_text(encoding="utf-8"),
            )

    def test_duplicate_id_fails(self):
        with TemporaryDirectory() as td:
            root = Path(td) / "kb"
            init_team(root)
            for name in ["a", "b"]:
                (root / "wiki/technical" / f"{name}.md").write_text(
                    """---
id: DUP-1
type: guide
status: draft
title: 示例
---
# 示例
""",
                    encoding="utf-8",
                )
            result = doctor(root)
            self.assertFalse(result.ok)
            self.assertTrue(
                any("duplicate knowledge id" in x for x in result.errors)
            )


if __name__ == "__main__":
    unittest.main()
