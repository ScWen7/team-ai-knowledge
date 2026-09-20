from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess
import unittest
import yaml

from team_wiki.core import (
    adopt_knowledge,
    context_plan,
    finalize_work,
    index_workspace,
    init_team,
    observe_knowledge,
    prepare_work,
    record_evidence,
    related,
)
from team_wiki.node_core import available, context_budget
from team_wiki.scope import SourceScope, SourceScopeError


class V02Tests(unittest.TestCase):
    def _knowledge(self, root: Path, name: str, kid: str, title: str, type_: str, sources=None, related_ids=None):
        p = root / "wiki/technical/demo" / f"{name}.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        meta = {
            "id": kid,
            "type": type_,
            "status": "draft",
            "title": title,
            "owner": "demo",
            "confidence": "unknown",
            "summary": f"{title} summary",
            "tags": ["demo"],
            "related": related_ids or [],
            "evidence": [{"source_id": x} for x in (sources or [])],
        }
        p.write_text("---\n" + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False) + "---\n# " + title + "\n", encoding="utf-8")
        return p

    @unittest.skipUnless(available(), "Node.js unavailable")
    def test_budget_and_relationships(self):
        b = context_budget(100_000)
        self.assertEqual(b["unit"], "characters")
        self.assertEqual(b["responseReserve"], 15_000)
        self.assertEqual(b["indexBudget"], 5_000)
        self.assertEqual(b["pageBudget"], 50_000)
        self.assertEqual(b["maxPageSize"], 15_000)

        with TemporaryDirectory() as td:
            root = Path(td) / "kb"
            init_team(root, "demo-team")
            self._knowledge(root, "a", "K-A", "订单导入规则", "rule", ["SRC-1"], ["K-B"])
            self._knowledge(root, "b", "K-B", "订单导入指南", "guide", ["SRC-1"])
            self._knowledge(root, "c", "K-C", "无关概念", "concept", ["SRC-9"])
            rows = related(root, "K-A", 3)
            self.assertEqual(rows[0]["id"], "K-B")
            plan = context_plan(root, "订单 导入", 100_000, 3)
            self.assertEqual(plan["budget"]["unit"], "characters")
            self.assertTrue(plan["direct"])
            self.assertIn("K-A", plan["related"])

    def test_source_scope_respects_ignore_and_traversal(self):
        with TemporaryDirectory() as td:
            root = Path(td) / "repo"
            (root / ".project-wiki").mkdir(parents=True)
            (root / ".project-wiki/.wikiignore").write_text("secret.txt\nignored/\n", encoding="utf-8")
            (root / "src").mkdir(); (root / "ignored").mkdir()
            (root / "src/app.txt").write_text("needle visible\n", encoding="utf-8")
            (root / "secret.txt").write_text("needle secret\n", encoding="utf-8")
            (root / "ignored/x.txt").write_text("needle ignored\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            with SourceScope(root) as scope:
                files = {p.relative_to(root).as_posix() for p in scope.source_files()}
                self.assertIn("src/app.txt", files)
                self.assertNotIn("secret.txt", files)
                self.assertNotIn("ignored/x.txt", files)
                hits = scope.search("needle")
                self.assertEqual([h["path"] for h in hits], ["src/app.txt"])
                with self.assertRaises(SourceScopeError):
                    scope.normalize("../outside.txt")

    def test_work_observation_creates_change(self):
        with TemporaryDirectory() as td:
            root = Path(td) / "kb"
            init_team(root, "demo-team")
            self._knowledge(root, "rule", "K-RULE", "示例规则", "rule")
            index_workspace(root)

            work_path = prepare_work(root, "验证示例规则")
            work_id = work_path.stem
            adopted = adopt_knowledge(root, work_id, "K-RULE", "判断本次实现边界")
            self.assertEqual(adopted["outcome"], "not-verified")

            evidence_path = record_evidence(root, work_id, "test", "tests/demo::test_rule", "指定条件下发现新的边界")
            evidence_id = evidence_path.stem
            observed = observe_knowledge(root, work_id, "K-RULE", "boundary-found", "规则缺少一个适用条件", [evidence_id])
            self.assertEqual(observed["outcome"], "boundary-found")

            result = finalize_work(root, work_id, owner="demo-owner")
            self.assertEqual(result["state"], "finalized")
            self.assertEqual(len(result["changes"]), 1)
            change_files = list((root / "changes").rglob("CHG-*.md"))
            self.assertEqual(len(change_files), 1)
            text = change_files[0].read_text(encoding="utf-8")
            self.assertIn(work_id, text)
            self.assertIn("K-RULE", text)
            self.assertIn(evidence_id, text)


if __name__ == "__main__":
    unittest.main()
