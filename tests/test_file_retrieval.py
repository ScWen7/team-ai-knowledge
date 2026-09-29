from __future__ import annotations

import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from team_wiki.core import context_plan, init_team
from team_wiki.retrieval import related_knowledge, search_knowledge, search_knowledge_report


def write_doc(
    root: Path,
    relative: str,
    *,
    doc_id: str | None,
    title: str,
    body: str,
    status: str = "active",
    scope: str | None = None,
    extra: str = "",
) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    frontmatter = [
        "---",
        f"id: {doc_id}" if doc_id is not None else "# no formal id",
        f"title: {title}",
        f"status: {status}",
    ]
    if scope is not None:
        frontmatter.append(f"scope: {scope}")
    if extra:
        frontmatter.extend(extra.strip().splitlines())
    frontmatter.append("---")
    path.write_text("\n".join(frontmatter) + f"\n\n{body}\n", encoding="utf-8")
    return path


def snapshot_tree(root: Path) -> dict[str, tuple[object, ...]]:
    snapshot: dict[str, tuple[object, ...]] = {}
    for path in [root, *sorted(root.rglob("*"))]:
        stat = path.lstat()
        relative = "." if path == root else path.relative_to(root).as_posix()
        if path.is_symlink():
            payload: object = path.readlink().as_posix()
        elif path.is_file():
            payload = path.read_bytes()
        else:
            payload = None
        snapshot[relative] = (stat.st_mode, stat.st_size, stat.st_mtime_ns, payload)
    return snapshot


class FileRetrievalTests(unittest.TestCase):
    def setUp(self) -> None:
        self._td = TemporaryDirectory()
        self.root = Path(self._td.name) / "repo"
        init_team(self.root, "demo-team")

    def tearDown(self) -> None:
        self._td.cleanup()

    def test_chinese_retrieval_and_unrelated_negative(self):
        write_doc(
            self.root,
            "wiki/business/orders/import.md",
            doc_id="K-IMPORT",
            title="订单导入手机号规则",
            body="批量订单导入时，收货人的手机号为必填项。",
        )
        write_doc(
            self.root,
            "wiki/technical/java.md",
            doc_id="K-JAVA",
            title="Java 内存排障",
            body="使用 heapdump 定位内存泄漏。",
        )
        write_doc(
            self.root,
            "wiki/.private/hidden.md",
            doc_id="K-HIDDEN",
            title="订单导入私有便笺",
            body="私有目录不进入团队检索。",
        )

        hits = search_knowledge(self.root, "订单导入手机号不能为空")
        self.assertEqual(hits[0]["id"], "K-IMPORT")
        self.assertNotIn("K-HIDDEN", {hit["id"] for hit in hits})
        self.assertEqual(search_knowledge(self.root, "dump")[0]["id"], "K-JAVA")
        self.assertEqual(search_knowledge(self.root, "员工年假余额"), [])
        self.assertEqual(
            set(hits[0]), {"score", "id", "title", "status", "path"}
        )

    def test_status_scope_and_limit_filters(self):
        write_doc(
            self.root,
            "wiki/business/orders/current.md",
            doc_id="K-CURRENT",
            title="订单导入当前规则",
            body="订单导入使用批量校验。",
            scope="operations",
        )
        write_doc(
            self.root,
            "wiki/business/orders/draft.md",
            doc_id="K-DRAFT",
            title="订单导入草案",
            body="订单导入方案待评审。",
            status="draft",
        )
        write_doc(
            self.root,
            "wiki/business/refunds/policy.md",
            doc_id="K-REFUND",
            title="退款处理规则",
            body="退款先检查支付状态。",
        )

        self.assertEqual(
            {hit["id"] for hit in search_knowledge(self.root, "订单导入", statuses=["active"])},
            {"K-CURRENT"},
        )
        self.assertEqual(
            {hit["id"] for hit in search_knowledge(self.root, "订单导入", statuses=None)},
            {"K-CURRENT", "K-DRAFT"},
        )
        self.assertEqual(
            [hit["id"] for hit in search_knowledge(self.root, "订单导入", scope="wiki/business/orders", limit=1)],
            ["K-CURRENT"],
        )
        self.assertEqual(
            [hit["id"] for hit in search_knowledge(self.root, "订单导入", scope="operations")],
            ["K-CURRENT"],
        )
        self.assertEqual(
            {hit["id"] for hit in search_knowledge(self.root, "退款", scope="demo-team")},
            {"K-REFUND"},
        )
        self.assertEqual(search_knowledge(self.root, "订单导入", scope="unknown-area"), [])
        self.assertEqual(search_knowledge(self.root, "订单导入", statuses=[]), [])

    def test_exact_id_is_a_direct_locator(self):
        write_doc(
            self.root,
            "wiki/business/entry.md",
            doc_id="K-DIRECT-42",
            title="可检索标题",
            body="正文不包含身份编号。",
        )
        hits = search_knowledge(self.root, "K-DIRECT-42")
        self.assertEqual([row["id"] for row in hits], ["K-DIRECT-42"])
        self.assertEqual(hits[0]["score"], 1)

    def test_project_documents_follow_configured_paths(self):
        config = self.root / ".knowledge/config.yml"
        config.write_text(
            "version: 1\nrepository_id: demo-project\nprofile: project\n"
            "document_paths:\n  - project-notes\n",
            encoding="utf-8",
        )
        write_doc(
            self.root,
            "project-notes/design.md",
            doc_id="P-DESIGN",
            title="项目回调重试设计",
            body="支付回调使用幂等键。",
        )
        write_doc(
            self.root,
            "unconfigured/private.md",
            doc_id="P-PRIVATE",
            title="支付回调私有笔记",
            body="支付回调不得被检索。",
        )

        self.assertEqual(
            [row["id"] for row in search_knowledge(self.root, "支付回调")],
            ["P-DESIGN"],
        )
        self.assertEqual(
            [row["id"] for row in search_knowledge(self.root, "支付回调", scope="project-notes")],
            ["P-DESIGN"],
        )

    def test_project_scope_configuration_changes_apply_on_next_call(self):
        config = self.root / ".knowledge/config.yml"

        def select(directory: str) -> None:
            config.write_text(
                "version: 1\nrepository_id: demo-project\nprofile: project\n"
                f"document_paths:\n  - {directory}\n",
                encoding="utf-8",
            )

        write_doc(
            self.root,
            "project-notes/old.md",
            doc_id="P-OLD",
            title="项目蓝鲸回调旧流程",
            body="old_process_token_91",
        )
        write_doc(
            self.root,
            "other-notes/new.md",
            doc_id="P-NEW",
            title="项目蓝鲸回调新流程",
            body="new_process_token_82",
        )
        select("project-notes")
        self.assertEqual(search_knowledge(self.root, "old_process_token_91")[0]["id"], "P-OLD")

        select("other-notes")
        self.assertEqual(search_knowledge(self.root, "new_process_token_82")[0]["id"], "P-NEW")
        self.assertEqual(search_knowledge(self.root, "old_process_token_91"), [])

    def test_document_without_id_keeps_id_none(self):
        write_doc(
            self.root,
            "wiki/business/notes.md",
            doc_id=None,
            title="未编号经验",
            body="缓存刷新遇到延迟。",
        )
        self.assertIsNone(search_knowledge(self.root, "缓存刷新")[0]["id"])

    def test_add_modify_rename_and_delete_are_visible_without_refresh(self):
        original = write_doc(
            self.root,
            "wiki/business/live/original.md",
            doc_id="K-LIVE",
            title="初始文档",
            body="quartz_delta_849",
        )
        self.assertEqual(search_knowledge(self.root, "quartz_delta_849")[0]["id"], "K-LIVE")

        added = write_doc(
            self.root,
            "wiki/technical/added.md",
            doc_id="K-ADDED",
            title="新增文档",
            body="indigo_signal_735",
        )
        self.assertEqual(search_knowledge(self.root, "indigo_signal_735")[0]["id"], "K-ADDED")

        original.write_text(
            "---\nid: K-LIVE\ntitle: 修改后文档\nstatus: active\n---\n\n"
            "violet_sigma_573\n",
            encoding="utf-8",
        )
        self.assertEqual(search_knowledge(self.root, "violet_sigma_573")[0]["id"], "K-LIVE")
        self.assertEqual(search_knowledge(self.root, "quartz_delta_849"), [])

        renamed = self.root / "wiki/business/live/renamed.md"
        original.rename(renamed)
        self.assertEqual(search_knowledge(self.root, "violet_sigma_573")[0]["path"], "wiki/business/live/renamed.md")
        self.assertEqual(search_knowledge(self.root, "quartz_delta_849"), [])

        renamed.unlink()
        added.unlink()
        self.assertEqual(search_knowledge(self.root, "violet_sigma_573"), [])
        self.assertEqual(search_knowledge(self.root, "indigo_signal_735"), [])

    def test_relations_are_explicit_and_respect_status_and_scope(self):
        write_doc(
            self.root,
            "wiki/team/source.md",
            doc_id="K-SOURCE",
            title="支付回调设计",
            body="使用幂等键处理回调。",
            extra=(
                "related:\n  - K-LINKED\n  - K-DRAFT\n"
                "references:\n  - id: K-UNRELATED\n    relation: unrelated\n"
                "depends_on:\n  - K-REVERSE"
            ),
        )
        write_doc(
            self.root,
            "wiki/team/linked.md",
            doc_id="K-LINKED",
            title="回调失败重试",
            body="根据明确关联设置重试。",
        )
        write_doc(
            self.root,
            "wiki/team/draft.md",
            doc_id="K-DRAFT",
            title="待定回调想法",
            body="草案说明。",
            status="draft",
        )
        write_doc(
            self.root,
            "wiki/team/reverse.md",
            doc_id="K-REVERSE",
            title="反向依赖说明",
            body="此文档依赖来源。",
            extra="depends_on:\n  - K-SOURCE",
        )
        write_doc(
            self.root,
            "wiki/team/unrelated.md",
            doc_id="K-UNRELATED",
            title="同一目录的普通文档",
            body="目录位置不构成显式关系。",
        )
        write_doc(
            self.root,
            "wiki/other/leak.md",
            doc_id="K-OTHER",
            title="范围外关系",
            body="不得被返回。",
            extra="related:\n  - K-SOURCE\n  - K-LINKED",
        )

        rows = related_knowledge(self.root, "K-SOURCE", statuses=["active"], scope="wiki/team")
        self.assertEqual({row["id"] for row in rows}, {"K-LINKED", "K-REVERSE"})
        self.assertTrue(all("/team/" in row["path"] for row in rows))
        self.assertEqual(related_knowledge(self.root, "K-SOURCE", scope="wiki/other"), [])

    def test_queries_read_documents_without_writes_or_database_access(self):
        write_doc(
            self.root,
            "wiki/team/source.md",
            doc_id="K-SOURCE",
            title="支付回调处理",
            body="处理支付回调并检查签名。",
            extra="related:\n  - K-LINKED\n  - K-DRAFT",
        )
        write_doc(
            self.root,
            "wiki/team/linked.md",
            doc_id="K-LINKED",
            title="支付回调重试",
            body="支付回调失败时按策略重试。",
        )
        write_doc(
            self.root,
            "wiki/team/draft.md",
            doc_id="K-DRAFT",
            title="支付回调待定方案",
            body="草案等待确认。",
            status="draft",
        )
        bad_database = self.root / ".knowledge/cache/search.sqlite3"
        bad_database.parent.mkdir(parents=True, exist_ok=True)
        bad_database.write_bytes(b"preserve malformed legacy database")
        before = snapshot_tree(self.root)

        from team_wiki import core

        original_open = Path.open

        def reject_database_open(path: Path, *args, **kwargs):
            if path.resolve() == bad_database.resolve():
                raise AssertionError("legacy SQLite file must not be read")
            return original_open(path, *args, **kwargs)

        with patch("sqlite3.connect", side_effect=AssertionError("SQLite must not be used")):
            with patch.object(Path, "open", reject_database_open):
                direct = search_knowledge(self.root, "支付回调", statuses=["active"], scope="wiki/team")
                self.assertIn("K-SOURCE", {row["id"] for row in direct})
                self.assertNotIn("K-DRAFT", {row["id"] for row in direct})
                self.assertEqual(
                    {row["id"] for row in related_knowledge(
                        self.root, "K-SOURCE", statuses=["active"], scope="wiki/team"
                    )},
                    {"K-LINKED"},
                )
                with patch.object(core, "parse_frontmatter", wraps=core.parse_frontmatter) as parser:
                    plan = context_plan(
                        self.root,
                        "支付回调",
                        statuses=["active"],
                        scope="wiki/team",
                    )
                    self.assertEqual(parser.call_count, 3)
                self.assertNotIn("K-DRAFT", {row["id"] for rows in plan["related"].values() for row in rows})

        self.assertEqual(snapshot_tree(self.root), before)

        linked_path = self.root / "wiki/team/linked.md"
        linked_path.write_text(
            "---\nid: K-LINKED\ntitle: 付款签名更新\nstatus: active\n---\n\n"
            "付款签名现使用新算法。\n",
            encoding="utf-8",
        )
        with patch.object(core, "parse_frontmatter", wraps=core.parse_frontmatter) as parser:
            next_plan = context_plan(self.root, "付款签名", statuses=["active"], scope="wiki/team")
            self.assertEqual(parser.call_count, 3)
        self.assertEqual(next_plan["direct"][0]["id"], "K-LINKED")

    def test_invalid_frontmatter_and_duplicate_ids_are_visible(self):
        malformed = write_doc(
            self.root,
            "wiki/business/malformed.md",
            doc_id="K-BROKEN",
            title="有效标题",
            body="正文。",
        )
        malformed.write_text("---\ntitle: [broken\n---\n正文。\n", encoding="utf-8")
        write_doc(self.root, "wiki/business/healthy.md", doc_id="K-HEALTHY",
                  title="健康文档", body="正文。")
        results, issues = search_knowledge_report(self.root, "正文")
        self.assertEqual([row["id"] for row in results], ["K-HEALTHY"])
        self.assertEqual([(i["path"], i["kind"]) for i in issues],
                         [("wiki/business/malformed.md", "skipped")])
        self.assertIn("cannot parse knowledge document", issues[0]["message"])

        malformed.unlink()
        for relative in ("wiki/business/a.md", "wiki/business/b.md"):
            write_doc(
                self.root,
                relative,
                doc_id="K-DUPLICATE",
                title="重复身份",
                body="冲突记录。",
            )
        results, issues = search_knowledge_report(self.root, "冲突记录")
        self.assertEqual(len(results), 2)
        self.assertEqual([i["kind"] for i in issues], ["duplicate_id"])
        self.assertIn("K-DUPLICATE", issues[0]["message"])

    def test_continuous_read_drift_is_visible_not_stale(self):
        path = write_doc(
            self.root,
            "wiki/business/drifting.md",
            doc_id="K-DRIFT",
            title="并发文档",
            body="旧版本查询词。",
        )
        self.assertEqual(search_knowledge(self.root, "旧版本查询词")[0]["id"], "K-DRIFT")
        path.write_text(
            "---\nid: K-DRIFT\ntitle: 并发文档\nstatus: active\n---\n\n更新期间内容并等待重新读取。\n",
            encoding="utf-8",
        )
        stat = path.stat()
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 60_000_000_000))
        from team_wiki import core

        original_parse = core.parse_frontmatter
        parse_count = 0

        def parse_then_write_again(source: Path):
            nonlocal parse_count
            parsed = original_parse(source)
            if source.resolve() == path.resolve():
                parse_count += 1
                source.write_text(
                    "---\nid: K-DRIFT\ntitle: 并发文档\nstatus: active\n---\n\n"
                    f"稳定词 {'持续漂移' * parse_count}迭代{parse_count}。\n",
                    encoding="utf-8",
                )
            return parsed

        with patch.object(core, "parse_frontmatter", side_effect=parse_then_write_again):
            results, issues = search_knowledge_report(self.root, "稳定词")
            self.assertEqual(results, [])
            self.assertIn("document changed while being read", issues[0]["message"])
        self.assertGreater(parse_count, 0)
        self.assertEqual(search_knowledge(self.root, "持续漂移")[0]["id"], "K-DRIFT")
        self.assertEqual(search_knowledge(self.root, "旧版本查询词"), [])

    def test_git_branch_switch_is_visible_without_refresh(self):
        repo = Path(self._td.name) / "isolated-git-repo"
        repo.mkdir()
        env = os.environ.copy()
        env["GIT_CONFIG_NOSYSTEM"] = "1"
        env["GIT_CONFIG_GLOBAL"] = os.devnull

        def git(*args: str) -> None:
            subprocess.run(
                ["git", *args],
                cwd=repo,
                env=env,
                text=True,
                capture_output=True,
                check=True,
            )

        git("init", "--quiet", "--initial-branch=main", "--template=")
        old_path = write_doc(
            repo,
            "wiki/project/current.md",
            doc_id="K-BRANCH-OLD",
            title="旧分支知识",
            body="branch_old_token_51",
        )
        git("add", "-A")
        git("-c", "user.name=Retrieval Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "main docs")

        git("switch", "--quiet", "-c", "next")
        old_path.unlink()
        write_doc(
            repo,
            "wiki/project/current.md",
            doc_id="K-BRANCH-NEW",
            title="新分支知识",
            body="branch_new_token_62",
        )
        git("add", "-A")
        git("-c", "user.name=Retrieval Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "next docs")

        git("switch", "--quiet", "main")
        self.assertEqual(search_knowledge(repo, "branch_old_token_51")[0]["id"], "K-BRANCH-OLD")
        self.assertEqual(search_knowledge(repo, "branch_new_token_62"), [])
        git("switch", "--quiet", "next")
        self.assertEqual(search_knowledge(repo, "branch_new_token_62")[0]["id"], "K-BRANCH-NEW")
        self.assertEqual(search_knowledge(repo, "branch_old_token_51"), [])


if __name__ == "__main__":
    unittest.main()
