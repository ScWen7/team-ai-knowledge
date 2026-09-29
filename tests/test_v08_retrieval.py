"""V0.8 tests: Chinese-capable knowledge retrieval.

`search` used to split the query on whitespace only. Chinese has no spaces,
so a natural-language question became a single term that was then matched as a
substring against body text — "手机号能不能为空" shares no characters with a
rule written as "手机号为必填项", and the query silently returned zero results.

Zero results are the dangerous part: an Agent receiving an empty list concludes
the knowledge does not exist and answers from its own assumptions.

These tests pin natural-language recall, clean rejection of unrelated queries,
field weighting, and that the retrieval-driven `context` planner benefits too.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from team_wiki.core import context_plan, init_team, search, tokenize_query


KNOWLEDGE = {
    "wiki/business/orders/import/contact-phone.md": (
        "RULE-CONTACT-PHONE",
        "rule",
        "active",
        "订单导入联系电话必填规则",
        "批量导入订单时，收货联系人的手机号为必填项。若该字段为空，系统会拒绝入库并返回 CONTACT_PHONE_REQUIRED 错误。",
        ["订单", "导入", "联系信息"],
    ),
    "wiki/business/orders/import/idempotent.md": (
        "RULE-IDEMPOTENT",
        "rule",
        "active",
        "订单导入幂等约束",
        "导入接口以订单号作为幂等键，重复提交返回首次结果，不会产生重复订单。",
        ["订单", "导入", "幂等"],
    ),
    "wiki/business/refund/policy.md": (
        "RULE-REFUND-WINDOW",
        "rule",
        "active",
        "退款时效规则",
        "用户在签收后 7 天内可发起无理由退款，超期需要人工审核。",
        ["退款", "时效"],
    ),
    "wiki/technical/api/error-codes.md": (
        "DOC-ERROR-CODES",
        "concept",
        "active",
        "订单接口错误码说明",
        "CONTACT_PHONE_REQUIRED 表示收货联系人手机号缺失；ORDER_DUPLICATED 表示订单号重复。",
        ["接口", "错误码"],
    ),
}


def build(root: Path) -> None:
    for rel, (kid, ktype, status, title, summary, tags) in KNOWLEDGE.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        tag_line = ", ".join(tags)
        path.write_text(
            f"""---
id: {kid}
type: {ktype}
status: {status}
title: {title}
owner: demo
confidence: confirmed
summary: {summary}
tags: [{tag_line}]
---

# {title}

{summary}
""",
            encoding="utf-8",
        )


def top_id(root: Path, query: str) -> str | None:
    hits = search(root, query)
    return hits[0]["id"] if hits else None


class V08RetrievalTests(unittest.TestCase):
    def setUp(self) -> None:
        self._td = TemporaryDirectory()
        self.root = Path(self._td.name) / "kb"
        init_team(self.root, "demo-team")
        build(self.root)

    def tearDown(self) -> None:
        self._td.cleanup()

    # --- tokenization ---

    def test_tokenizer_expands_cjk_into_ngrams(self):
        terms = tokenize_query("手机号必填")
        self.assertIn("手机", terms)
        self.assertIn("手机号", terms)
        self.assertIn("号必", terms)

    def test_tokenizer_keeps_latin_tokens_whole(self):
        terms = tokenize_query("CONTACT_PHONE_REQUIRED 幂等")
        self.assertIn("contact_phone_required", terms)
        self.assertIn("幂等", terms)

    def test_tokenizer_strips_punctuation(self):
        terms = tokenize_query("手机号，能不能为空？")
        self.assertTrue(all(not t.endswith("？") and "，" not in t for t in terms))

    def test_empty_query_returns_nothing(self):
        self.assertEqual(search(self.root, ""), [])
        self.assertEqual(search(self.root, "   "), [])
        self.assertEqual(search(self.root, "？？？！"), [])

    # --- natural language recall: the actual regression ---

    def test_natural_language_questions_return_results(self):
        """Each of these returned zero rows before the fix."""
        for query in (
            "手机号能不能为空",
            "重复导入会怎么样",
            "多久可以退款",
            "收货人电话要填吗",
            "必填字段有哪些",
            "订单导入失败怎么办",
            "错误码怎么处理",
            "怎么避免重复订单",
        ):
            with self.subTest(query=query):
                self.assertTrue(search(self.root, query), f"{query!r} returned nothing")

    def test_natural_language_questions_rank_the_right_entry_first(self):
        cases = {
            "手机号能不能为空": "RULE-CONTACT-PHONE",
            "收货人电话要填吗": "RULE-CONTACT-PHONE",
            "必填字段有哪些": "RULE-CONTACT-PHONE",
            "重复导入会怎么样": "RULE-IDEMPOTENT",
            "怎么避免重复订单": "RULE-IDEMPOTENT",
            "多久可以退款": "RULE-REFUND-WINDOW",
            "退款期限是多久": "RULE-REFUND-WINDOW",
            "错误码怎么处理": "DOC-ERROR-CODES",
        }
        for query, expected in cases.items():
            with self.subTest(query=query):
                self.assertEqual(top_id(self.root, query), expected)

    def test_wording_may_differ_from_the_knowledge_text(self):
        """The query does not need to reuse the rule's exact phrasing."""
        # knowledge says 手机号为必填项; question says 手机号能不能为空
        self.assertEqual(top_id(self.root, "手机号能不能为空"), "RULE-CONTACT-PHONE")

    # --- negative cases: unrelated queries must not fabricate hits ---

    def test_unrelated_queries_return_nothing(self):
        for query in ("今天天气怎么样", "篮球比赛", "Kubernetes 部署", "zzzqqqxxx", "!!!???"):
            with self.subTest(query=query):
                self.assertEqual(search(self.root, query), [], f"{query!r} should not match")

    def test_zero_results_beat_wrong_results(self):
        """A wrong answer is worse than an empty list."""
        self.assertIsNone(top_id(self.root, "如何申请调休"))

    # --- existing behaviour preserved ---

    def test_whitespace_separated_query_still_works(self):
        self.assertEqual(top_id(self.root, "订单 导入"), "RULE-IDEMPOTENT")

    def test_single_keyword_query_still_works(self):
        self.assertEqual(top_id(self.root, "幂等"), "RULE-IDEMPOTENT")
        self.assertEqual(top_id(self.root, "退款"), "RULE-REFUND-WINDOW")

    def test_latin_identifier_still_matches(self):
        self.assertEqual(top_id(self.root, "CONTACT_PHONE_REQUIRED"), "RULE-CONTACT-PHONE")

    def test_mixed_cjk_and_latin_query(self):
        self.assertEqual(top_id(self.root, "订单 ORDER_DUPLICATED"), "DOC-ERROR-CODES")

    def test_results_are_sorted_by_descending_score(self):
        hits = search(self.root, "订单 导入")
        scores = [h["score"] for h in hits]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_result_shape_is_unchanged(self):
        hit = search(self.root, "幂等")[0]
        self.assertEqual(
            set(hit), {"score", "id", "title", "status", "path"}
        )

    def test_title_match_outranks_body_match(self):
        hits = search(self.root, "退款")
        self.assertEqual(hits[0]["id"], "RULE-REFUND-WINDOW")

    # --- retrieval-driven context planner ---

    def test_context_plan_finds_knowledge_for_a_question(self):
        """`context` calls search internally, so it was broken the same way."""
        plan = context_plan(self.root, "手机号能不能为空")
        self.assertTrue(plan["direct"], "context returned no direct hits")
        self.assertEqual(plan["direct"][0]["id"], "RULE-CONTACT-PHONE")

    def test_context_plan_expands_relations(self):
        plan = context_plan(self.root, "重复导入会怎么样")
        self.assertTrue(plan["direct"])
        self.assertTrue(plan["related"], "context produced no related expansion")

    def test_context_plan_still_reports_incompleteness(self):
        """The planner is a retrieval plan, not a claim of completeness."""
        plan = context_plan(self.root, "幂等")
        self.assertFalse(plan["complete"])
        self.assertIn("note", plan)

    # --- no index files / no lifecycle knowledge leaked ---

    def test_search_does_not_match_index_navigation_files(self):
        """INDEX.md navigation must not outrank real knowledge."""
        hits = search(self.root, "幂等")
        self.assertNotIn("INDEX.md", hits[0]["path"])

    def test_draft_and_active_are_both_findable(self):
        path = self.root / "wiki/business/orders/import/contact-phone.md"
        text = path.read_text(encoding="utf-8").replace("status: active", "status: draft")
        path.write_text(text, encoding="utf-8")
        hit = top_id(self.root, "手机号能不能为空")
        self.assertEqual(hit, "RULE-CONTACT-PHONE")


if __name__ == "__main__":
    unittest.main()
