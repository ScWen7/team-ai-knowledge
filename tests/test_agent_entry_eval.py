import tempfile
import unittest
from pathlib import Path

from team_wiki.agent_entry import BEGIN, END, setup_agent_entry
from team_wiki.evaluation import evaluate


def doc(root: Path, rel: str, doc_id: str, title: str, body: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nid: {doc_id}\ntitle: {title}\nstatus: active\n---\n\n{body}\n", encoding="utf-8")


class AgentEntryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_preview_does_not_write_and_apply_is_idempotent(self):
        self.assertTrue(setup_agent_entry(self.root)["changed"])
        self.assertFalse((self.root / "AGENTS.md").exists())
        self.assertTrue(setup_agent_entry(self.root, apply=True)["created"])
        first = (self.root / "AGENTS.md").read_text(encoding="utf-8")
        self.assertFalse(setup_agent_entry(self.root, apply=True)["changed"])
        self.assertEqual((self.root / "AGENTS.md").read_text(encoding="utf-8"), first)

    def test_existing_instructions_are_preserved(self):
        (self.root / "AGENTS.md").write_text("# 项目说明\n\n保留这一行。\n", encoding="utf-8")
        setup_agent_entry(self.root, apply=True)
        text = (self.root / "AGENTS.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# 项目说明\n\n保留这一行。\n"))
        self.assertEqual(text.count(BEGIN), 1)
        (self.root / "AGENTS.md").write_text(text.replace("知识库使用约定", "旧标题"), encoding="utf-8")
        setup_agent_entry(self.root, apply=True)
        updated = (self.root / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("知识库使用约定", updated)
        self.assertNotIn("旧标题", updated)
        self.assertIn("保留这一行。", updated)

    def test_unbalanced_marker_is_refused(self):
        (self.root / "AGENTS.md").write_text(f"{BEGIN}\n手写内容\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "unbalanced"):
            setup_agent_entry(self.root, apply=True)
        self.assertNotIn(END, (self.root / "AGENTS.md").read_text(encoding="utf-8"))


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        (self.root / ".knowledge").mkdir()
        (self.root / ".knowledge/config.yml").write_text(
            "version: 1\nrepository_id: demo\nprofile: team\n", encoding="utf-8")
        doc(self.root, "wiki/build.md", "K-BUILD", "构建缓存", "依赖更新后构建仍使用旧版本，需要清理缓存。")
        doc(self.root, "wiki/auth.md", "K-AUTH", "权限校验", "接口权限失败时返回统一错误码。")

    def write_cases(self, text: str):
        (self.root / ".knowledge/eval.yml").write_text(text, encoding="utf-8")

    def test_reports_recall_mrr_and_negative_cases(self):
        self.write_cases(
            "cases:\n"
            "  - query: 依赖更新后为什么仍用旧版本\n    expect: [K-BUILD]\n"
            "  - query: 权限失败返回什么\n    expect: wiki/auth.md\n"
            "  - query: 支付回调重试\n    expect: [K-PAY]\n"
            "  - query: zzzz qqqq\n    expect_none: true\n")
        result = evaluate(self.root)
        self.assertEqual(result["cases"], 4)
        self.assertEqual(result["recall_at_k"], 0.667)
        self.assertEqual(result["negative_pass"], "1/1")
        self.assertEqual([f["query"] for f in result["failures"]], ["支付回调重试"])
        self.assertEqual(result["failures"][0]["missing"], ["K-PAY"])

    def test_invalid_cases_are_rejected(self):
        self.write_cases("cases:\n  - query: 缺少期望\n")
        with self.assertRaisesRegex(ValueError, "expect"):
            evaluate(self.root)
        self.write_cases("cases: []\n")
        with self.assertRaisesRegex(ValueError, "non-empty"):
            evaluate(self.root)


if __name__ == "__main__":
    unittest.main()
