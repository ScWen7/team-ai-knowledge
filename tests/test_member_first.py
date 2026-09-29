"""Member-first behavior, not the shape of internal implementation.

All documents are synthetic and live in temporary directories. No external
project, real user experience, or business approval is simulated as a fact.
"""
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import yaml

from team_wiki.agent_entry import BEGIN, END, setup_agent_entry
from team_wiki.connections import connected_query, team_path
from team_wiki.core import doctor, init_team, index_workspace, knowledge_ref, read_yaml, write_yaml
from team_wiki.evaluation import evaluate
from team_wiki.project import init_project, lock_latest, project_rules
from team_wiki.retrieval import search_knowledge_report, related_knowledge, context_knowledge
from team_wiki.status import build_status_report
import test_v07 as fixtures


def write(root, path, content):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file() and not p.is_symlink()}


def cli(*args):
    return subprocess.run([sys.executable, "-m", "team_wiki", *map(str, args)], capture_output=True, text=True)


class MemberFirstTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.project = self.base / "project"
        self.project.mkdir()
        self.team = self.base / "team"
        init_team(self.team, "our-team")

    def test_first_read_does_not_need_governance_or_frontmatter(self):
        path = write(self.project, "docs/build.md", "# 依赖版本排查\n核对构建实际使用的依赖版本。\n")
        before = snapshot(self.project)
        rows, issues = search_knowledge_report(self.project, "依赖版本")
        self.assertEqual(rows[0]["path"], "docs/build.md")
        self.assertEqual(rows[0]["title"], "依赖版本排查")
        self.assertIsNone(rows[0]["id"])
        self.assertEqual(issues, [])
        self.assertEqual(before, snapshot(self.project))
        result = init_project(self.project, project_id="p", document_paths=["docs"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["changed_paths"], [])
        self.assertNotIn("pending_confirmation", result)
        self.assertEqual(path.read_bytes(), before["docs/build.md"])
        self.assertFalse((self.project / ".knowledge/documents.md").exists())
        self.assertFalse((self.project / ".knowledge/cache").exists())
        again = snapshot(self.project)
        init_project(self.project, project_id="p")
        self.assertEqual(snapshot(self.project), again)

    def test_connect_can_read_healthy_documents_before_repairing_a_bad_one(self):
        write(self.project, "docs/good.md", "# 构建依赖\n已经记录的经验。")
        write(self.project, "docs/bad.md", "---\ntitle: [bad\n---\n")
        self.assertTrue(init_project(self.project, project_id="p")["ok"])
        rows, issues = search_knowledge_report(self.project, "构建依赖")
        self.assertEqual(rows[0]["path"], "docs/good.md")
        self.assertEqual(issues[0]["kind"], "skipped")

    def test_readme_and_index_are_readable_but_not_governed(self):
        original = {}
        for rel, word in [("README.md", "启动指引"), ("docs/README.md", "接入方法"), ("docs/INDEX.md", "维护约定")]:
            p = write(self.project, rel, f"# {word}\n{word}保存在项目原位。\n")
            original[rel] = p.read_bytes()
        write(self.project, "docs/AGENTS.md", "# 不作为知识的指令\nsecret_instruction_token")
        write(self.project, "docs/CLAUDE.md", "secret_instruction_token")
        init_project(self.project, project_id="p", apply=True)
        for rel, word in [("README.md", "启动指引"), ("docs/README.md", "接入方法"), ("docs/INDEX.md", "维护约定")]:
            rows, _ = search_knowledge_report(self.project, word)
            self.assertIn(rel, [r["path"] for r in rows])
            self.assertEqual((self.project / rel).read_bytes(), original[rel])
        self.assertEqual(search_knowledge_report(self.project, "secret_instruction_token")[0], [])

    def test_search_does_not_follow_an_outside_symlink_and_keeps_good_results(self):
        write(self.project, "docs/good.md", "# 构建缓存\n正常经验")
        outside = write(self.base, "outside.md", "# 未授权内容\nprivate_secret")
        (self.project / "docs/leak.md").symlink_to(outside)
        init_project(self.project, project_id="p")
        rows, issues = search_knowledge_report(self.project, "构建缓存")
        self.assertEqual(rows[0]["path"], "docs/good.md")
        self.assertTrue(any(i["path"] == "docs/leak.md" for i in issues))
        self.assertEqual(search_knowledge_report(self.project, "private_secret")[0], [])

    def test_connected_search_preserves_repository_namespaces_and_writes_nothing(self):
        write(self.project, "docs/local.md", "---\nid: SAME-ID\n---\n# 构建缓存\n本项目的版本边界。")
        write(self.team, "wiki/technical/team.md", "---\nid: SAME-ID\n---\n# 构建缓存\n团队可复用经验。")
        write(self.base, "not-connected/wiki/secret.md", "构建缓存 not_authorized")
        init_project(self.project, project_id="p", team_root=self.team)
        before = snapshot(self.base)
        result = connected_query(self.project, "构建缓存")
        self.assertTrue(result["complete"])
        self.assertEqual([s["repository_id"] for s in result["sources"]], ["p", "our-team"])
        self.assertEqual([s["results"][0]["id"] for s in result["sources"]], ["SAME-ID", "SAME-ID"])
        self.assertEqual(snapshot(self.base), before)
        for source in result["sources"]:
            content = (Path(source["root"]) / source["results"][0]["path"]).read_text()
            self.assertIn("构建缓存", content)
        self.assertEqual(connected_query(self.project, "not_authorized")["sources"][1]["results"], [])

    def test_cli_connection_options_work_without_creating_a_rule_subscription(self):
        write(self.project, "docs/project.md", "# 构建缓存\n项目结论")
        write(self.team, "wiki/technical/answer.md", "# 构建缓存\n团队结论")
        result = cli("project-init", self.project, "--project-id", "p", "--team-root", self.team)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(read_yaml(self.project / ".knowledge/config.yml")["knowledge_sources"], [])
        self.assertNotIn(str(self.team), (self.project / ".knowledge/config.yml").read_text())
        self.assertIn(".knowledge/local.yml", (self.project / ".gitignore").read_text())
        result = cli("search", self.project, "构建缓存", "--connected", "--limit", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(json.loads(result.stdout)["sources"]), 2)
        result = cli("context", self.project, "构建缓存", "--connected")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(json.loads(result.stdout)["sources"][1]["direct"]), 1)
        self.assertFalse((self.project / ".knowledge/knowledge.lock.yml").exists())

    def test_bad_or_missing_connections_are_not_reported_as_no_knowledge(self):
        init_project(self.project, project_id="p", team_root=self.team)
        write_yaml(self.team / ".knowledge/config.yml", {"version": 1, "profile": "team", "repository_id": "wrong"})
        result = connected_query(self.project, "构建缓存")
        self.assertFalse(result["complete"])
        self.assertIn("identity mismatch", result["issues"][0]["message"])
        self.assertEqual(len(result["sources"]), 1)
        (self.team / ".knowledge/config.yml").unlink()
        result = connected_query(self.project, "构建缓存")
        self.assertFalse(result["complete"])
        with self.assertRaises(ValueError):
            team_path(self.project, "our-team")

    def test_declared_but_unconnected_baseline_is_visible(self):
        init_project(self.project, project_id="p", team_repository_id="missing", knowledge_ids=["K-RULE"])
        report = connected_query(self.project, "规则")
        self.assertFalse(report["complete"])
        self.assertEqual(report["issues"][0]["kind"], "not_connected")
        with self.assertRaisesRegex(ValueError, "not connected"):
            project_rules(self.project)

    def test_local_mapping_symlink_is_rejected_and_not_modified(self):
        init_project(self.project, project_id="p")
        outside = write(self.base, "private.yml", "repositories: {}\n")
        (self.project / ".knowledge/local.yml").symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "symlink"):
            init_project(self.project, project_id="p", team_root=self.team)
        self.assertEqual(outside.read_text(), "repositories: {}\n")
        self.assertFalse(connected_query(self.project, "查询")["complete"])

    def test_rule_reading_resolves_local_path_and_keeps_the_gate(self):
        fixture = fixtures.V07Tests()
        team = self.base / "rule-team"
        fixture._init_team_repo(team)
        fixture._publish(team, body="所有必要底线必须读取", requirement="notice", label="v1")
        init_project(self.project, project_id="p", team_repository_id="team-knowledge", knowledge_ids=["K-A"], team_root=team)
        lock_latest(self.project, team)
        result = project_rules(self.project)
        self.assertTrue(result["complete"])
        self.assertIn("所有必要底线", result["rules"][0]["content"])
        fixture._publish(team, body="必须处理的更新", requirement="must-address", label="v2")
        self.assertFalse(project_rules(self.project)["ok"])
        self.assertFalse((self.project / ".knowledge/runs").exists())

    def test_minimal_init_and_index_do_not_resurrect_old_workflow_directories(self):
        index_workspace(self.team)
        self.assertTrue(doctor(self.team).ok)
        for rel in ("changes", "sources/evidence", ".knowledge/records", ".knowledge/runs", ".knowledge/cache"):
            self.assertFalse((self.team / rel).exists(), rel)
        self.assertNotIn("changes/INDEX.md", (self.team / "README.md").read_text())
        write(self.team, "wiki/technical/plain.md", "# 直接可读的经验\n没有元信息不等于没有价值。")
        self.assertTrue(doctor(self.team).ok)
        self.assertTrue(search_knowledge_report(self.team, "直接可读的经验")[0])

    def test_reinitialization_preserves_history_and_existing_ignores(self):
        path = write(self.team, "changes/2025/history.md", "historical record")
        (self.team / ".gitignore").write_text("keep-me\n")
        init_team(self.team, "our-team")
        self.assertEqual(path.read_text(), "historical record")
        self.assertTrue((self.team / ".gitignore").read_text().startswith("keep-me\n"))
        self.assertIn(".knowledge/local.yml", (self.team / ".gitignore").read_text())

    def test_default_status_does_not_compute_unobserved_adoptions_or_old_timestamps(self):
        with patch("team_wiki.status.build_stale_report", side_effect=AssertionError("not a daily task")):
            self.assertEqual(build_status_report(self.team).decisions, [])
        for i in range(4):
            write(self.team, f"sources/inbox/{i}.md", "参考资料，不要求转成知识")
        report = build_status_report(self.team)
        text = json.dumps(report.as_dict(), ensure_ascii=False)
        for frozen in ("ingest", "intake-source", "evidence-bindings", "adoption-status"):
            self.assertNotIn(frozen, text)
        self.assertIn("Agent", text)

    def test_same_experience_can_be_found_by_another_project_and_corrected_in_place(self):
        # Synthetic end-to-end file workflow, not a claim that real members used it.
        source = write(self.project, "docs/experience.md", "# 编译缓存排查\n适用：示例环境 A；先核对依赖版本。\n")
        shared = write(self.team, "wiki/technical/build.md", "# 编译缓存排查\n适用：示例环境 A；先核对依赖版本。\n来源：项目 p 的 docs/experience.md。\n")
        other = self.base / "other"
        other.mkdir()
        init_project(other, project_id="other", team_root=self.team)
        report = connected_query(other, "编译缓存排查")
        target = report["sources"][1]["results"][0]
        self.assertEqual(target["path"], "wiki/technical/build.md")
        self.assertIn("示例环境 A", shared.read_text())
        shared.write_text(shared.read_text() + "反例：示例环境 B 不适用；依据：此次隔离测试记录。\n")
        next_read = connected_query(other, "示例环境")
        self.assertEqual(next_read["sources"][1]["results"][0]["path"], target["path"])
        self.assertIn("不适用", shared.read_text())
        self.assertNotIn("不适用", source.read_text())
        self.assertEqual(len(list((self.team / "wiki/technical").glob("build*.md"))), 1)


class ContractCorrectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        init_team(self.root, "team")

    def test_duplicate_ids_are_explorable_but_not_exact_references(self):
        for name in ("a", "b"):
            write(self.root, f"wiki/technical/{name}.md", "---\nid: DUP\n---\n# 编译缓存\n知识正文")
        rows, issues = search_knowledge_report(self.root, "DUP")
        self.assertEqual(len(rows), 2)
        self.assertEqual(issues[0]["kind"], "duplicate_id")
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            related_knowledge(self.root, "DUP")
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            knowledge_ref(self.root, "DUP")
        plan = context_knowledge(self.root, "DUP")
        self.assertEqual(plan["related"]["DUP"], [])
        self.assertTrue(plan["issues"])

    def test_partial_document_recall_is_not_all_expected_success(self):
        write(self.root, "wiki/technical/a.md", "---\nid: A\n---\n# 构建缓存\n测试")
        write(self.root, "wiki/technical/b.md", "---\nid: B\n---\n# 退款时限\n测试")
        write_yaml(self.root / ".knowledge/eval.yml", {"cases": [{"query": "构建缓存", "expect": ["A", "B"]}]})
        result = evaluate(self.root)
        self.assertEqual(result["recall_at_k"], 0.5)
        self.assertEqual(result["all_expected_at_k"], 0.0)
        self.assertEqual(result["mrr"], 1.0)
        self.assertFalse(result["ok"])

    def test_unreadable_corpus_cannot_make_a_negative_case_pass(self):
        write(self.root, "wiki/technical/bad.md", "---\ntitle: [broken\n---\n")
        write_yaml(self.root / ".knowledge/eval.yml", {"cases": [{"query": "查询", "expect_none": True}]})
        result = evaluate(self.root)
        self.assertEqual(result["invalid_cases"], 1)
        self.assertEqual(result["negative_pass"], "0/0")
        self.assertFalse(result["ok"])
        self.assertTrue(result["health_issues"])
        self.assertIsNone(result["recall_at_k"])
        self.assertNotEqual(cli("eval", self.root).returncode, 0)

    def test_invalid_expectations_are_not_silently_coerced(self):
        for value in ([None], [123], {"A": "B"}, 5):
            write_yaml(self.root / ".knowledge/eval.yml", {"cases": [{"query": "问题", "expect": value}]})
            with self.assertRaises(ValueError):
                evaluate(self.root)
        with self.assertRaises(ValueError):
            evaluate(self.root, k=True)

    def test_agent_entry_preserves_crlf_and_user_owned_whitespace(self):
        prefix = b"# Own instructions\r\n\r\n"
        suffix = b"\r\n\r\n\r\n# Keep suffix\r\n"
        target = self.root / "CLAUDE.md"
        target.write_bytes(prefix + BEGIN.encode() + b"\r\nold\r\n" + END.encode() + suffix)
        setup_agent_entry(self.root, entry_file="CLAUDE.md", apply=True)
        data = target.read_bytes()
        self.assertTrue(data.startswith(prefix))
        self.assertTrue(data.endswith(suffix))
        self.assertFalse(setup_agent_entry(self.root, entry_file="CLAUDE.md", apply=True)["changed"])
        self.assertEqual(data, target.read_bytes())
        self.assertIn(b"--connected", data)
        self.assertNotIn("无需沉淀".encode(), data)

    def test_duplicate_markers_and_broken_config_are_rejected_without_rewrite(self):
        target = self.root / "AGENTS.md"
        original = (f"{BEGIN}\nx\n{END}\n" * 2).encode()
        target.write_bytes(original)
        with self.assertRaises(ValueError):
            setup_agent_entry(self.root, apply=True)
        self.assertEqual(target.read_bytes(), original)
        target.write_text("# Existing instructions\n")
        write(self.root, ".knowledge/config.yml", "broken: [yaml")
        result = cli("agent-entry", self.root, "--apply")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(target.read_text(), "# Existing instructions\n")

    def test_connected_validation_covers_the_entire_configured_scope(self):
        write_yaml(self.root / ".knowledge/local.yml", {"repositories": {"outside": 42}})
        report = connected_query(self.root, "问题")
        self.assertFalse(report["complete"])
        self.assertTrue(report["issues"])
        with self.assertRaises(ValueError):
            connected_query(self.root, "问题", limit=-1)
