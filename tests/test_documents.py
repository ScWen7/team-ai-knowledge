from __future__ import annotations

import json
import hashlib
import os
import tempfile
import unittest
from pathlib import Path

import yaml

from team_wiki.documents import document_roots, govern_documents, iter_document_files


class DocumentGovernanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="team-wiki-documents-")
        self.root = Path(self.temp.name)
        (self.root / "docs").mkdir()
        (self.root / ".knowledge").mkdir()
        (self.root / ".knowledge/config.yml").write_text(
            "profile: project\nrepository_id: sample-project\ndocument_paths:\n  - docs\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_doc(self, relative: str, content: bytes | str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
        return path

    def issues(self, report: dict, code: str) -> list[dict]:
        return [issue for issue in report["issues"] if issue["code"] == code]

    def test_preview_is_read_only_and_reports_reviewable_diff(self) -> None:
        body = b"# Preview title\r\n\r\nKeep this body byte-for-byte.\r\n"
        path = self.write_doc("docs/guide.md", body)

        report = govern_documents(self.root, repository_id="preview-override")

        self.assertTrue(report["ok"])
        self.assertEqual(report["document_paths"], ["docs"])
        self.assertEqual(path.read_bytes(), body)
        self.assertFalse((self.root / ".knowledge/documents.md").exists())
        file_report = next(item for item in report["files"] if item["path"] == "docs/guide.md")
        self.assertIn("+id: \"doc-", file_report["diff"])
        expected_id = "doc-" + hashlib.sha256(b"preview-override\ndocs/guide.md").hexdigest()[:16]
        self.assertEqual(file_report["metadata"]["id"], expected_id)
        self.assertIn("+title: \"Preview title\"", file_report["diff"])
        self.assertTrue(file_report["pending_confirmation"])
        json.dumps(report, allow_nan=False)

    def test_utf8_bom_does_not_hide_existing_metadata(self) -> None:
        raw = b"\xef\xbb\xbf---\r\nid: EXISTING\r\ntitle: Existing title\r\n---\r\n# Body\r\n"
        path = self.write_doc("docs/bom.md", raw)
        result = govern_documents(self.root, apply=True)
        self.assertTrue(result["ok"], result)
        self.assertTrue(path.read_bytes().startswith(b"\xef\xbb\xbf---\r\nid: EXISTING\r\n"))
        self.assertTrue(path.read_bytes().endswith(b"# Body\r\n"))
        self.assertEqual(path.read_bytes().count(b"id:"), 1)
        self.assertEqual(govern_documents(self.root, apply=True)["changed_paths"], [])

    def test_closing_frontmatter_delimiter_requires_its_own_line(self) -> None:
        raw = b"---\ntitle: Invalid---\n# Body\n"
        path = self.write_doc("docs/invalid-close.md", raw)
        result = govern_documents(self.root, apply=True)
        self.assertFalse(result["ok"])
        self.assertEqual(path.read_bytes(), raw)

    def test_apply_preserves_crlf_body_and_is_idempotent_including_navigation(self) -> None:
        body = b"# CRLF title\r\n\r\nBody line one.\r\nBody line two.\r\n"
        path = self.write_doc("docs/sub/guide.md", body)

        first = govern_documents(self.root, apply=True, repository_id="sample-project")
        first_bytes = path.read_bytes()
        frontmatter_end = first_bytes.index(b"\n---\n", 4) + len(b"\n---\n")
        self.assertEqual(first_bytes[frontmatter_end:], body)
        self.assertIn("docs/sub/guide.md", first["changed_paths"])
        nav_path = self.root / ".knowledge/documents.md"
        nav_first = nav_path.read_bytes()
        self.assertIn(b"[CRLF title](../docs/sub/guide.md)", nav_first)

        second = govern_documents(self.root, apply=True, repository_id="sample-project")

        self.assertTrue(second["ok"])
        self.assertEqual(second["changed_paths"], [])
        self.assertEqual(path.read_bytes(), first_bytes)
        self.assertEqual(nav_path.read_bytes(), nav_first)

    def test_empty_frontmatter_lf_and_crlf_are_valid_and_idempotent(self) -> None:
        bodies = {
            "docs/empty-lf.md": b"---\n---\n# LF body\n",
            "docs/empty-crlf.md": b"---\r\n---\r\n# CRLF body\r\n",
        }
        paths = {name: self.write_doc(name, body) for name, body in bodies.items()}

        first = govern_documents(self.root, apply=True)

        self.assertTrue(first["ok"])
        for name, body in bodies.items():
            written = paths[name].read_bytes()
            line = b"---\r\n" if b"\r\n" in body else b"---\n"
            close_end = written.index(line, len(line)) + len(line)
            self.assertEqual(written[close_end:], body[2 * len(line) :])

        second = govern_documents(self.root, apply=True)
        self.assertEqual(second["changed_paths"], [])

    def test_existing_fields_comments_and_aliases_are_preserved(self) -> None:
        original = (
            "---\n"
            "# existing comment\n"
            "document_id: existing-42\n"
            "name: Existing title\n"
            "doc_type: decision\n"
            "status: verified\n"
            "confidence: 0.7\n"
            "updated: 2026-09-11\n"
            "details:\n  checked_at: 2026-09-12\n"
            "---\n"
            "# Body title\n\nKeep exact body.\n"
        ).encode()
        path = self.write_doc("docs/aliases.md", original)

        report = govern_documents(self.root, apply=True)

        new = path.read_bytes()
        body_start = new.index(b"---\n", 4) + len(b"---\n")
        self.assertEqual(new[body_start:], b"# Body title\n\nKeep exact body.\n")
        self.assertIn(b"# existing comment\n", new)
        self.assertIn(b"confidence: 0.7\n", new)
        self.assertIn(b"updated: 2026-09-11\n", new)
        metadata = yaml.safe_load(new.split(b"---\n", 2)[1])
        self.assertEqual(metadata["document_id"], "existing-42")
        self.assertEqual(metadata["id"], "existing-42")
        self.assertEqual(metadata["name"], "Existing title")
        self.assertEqual(metadata["title"], "Existing title")
        self.assertEqual(metadata["doc_type"], "decision")
        self.assertEqual(metadata["type"], "decision")
        self.assertEqual(metadata["status"], "verified")
        file_report = next(item for item in report["files"] if item["path"] == "docs/aliases.md")
        self.assertEqual(file_report["metadata"]["updated"], "2026-09-11")
        self.assertEqual(file_report["metadata"]["details"]["checked_at"], "2026-09-12")
        json.dumps(report, allow_nan=False)

    def test_repeated_alias_with_same_value_is_accepted_but_conflict_blocks(self) -> None:
        same = self.write_doc("docs/same-alias.md", "---\nid: same\ndoc_id: same\n---\nBody\n")
        conflict = self.write_doc("docs/conflict.md", "---\nid: first\ndoc_id: second\n---\nBody\n")

        report = govern_documents(self.root, apply=True)

        self.assertFalse(report["ok"])
        self.assertTrue(self.issues(report, "duplicate_critical_field"))
        self.assertEqual(same.read_text(), "---\nid: same\ndoc_id: same\n---\nBody\n")
        self.assertEqual(conflict.read_text(), "---\nid: first\ndoc_id: second\n---\nBody\n")
        self.assertFalse((self.root / ".knowledge/documents.md").exists())

    def test_duplicate_ids_block_the_whole_batch(self) -> None:
        first = self.write_doc("docs/a.md", "---\nid: duplicate\n---\nA\n")
        second = self.write_doc("docs/b.md", "---\nid: duplicate\n---\nB\n")

        report = govern_documents(self.root, apply=True)

        self.assertFalse(report["ok"])
        self.assertEqual(len(self.issues(report, "duplicate_id")), 2)
        self.assertEqual(first.read_text(), "---\nid: duplicate\n---\nA\n")
        self.assertEqual(second.read_text(), "---\nid: duplicate\n---\nB\n")
        self.assertFalse((self.root / ".knowledge/documents.md").exists())

    def test_invalid_yaml_and_non_mapping_frontmatter_block(self) -> None:
        malformed = self.write_doc("docs/bad-yaml.md", "---\ntitle: [\n---\nBody\n")
        scalar = self.write_doc("docs/scalar.md", "---\njust a scalar\n---\nBody\n")
        null = self.write_doc("docs/null.md", "---\nnull\n---\nBody\n")
        repeated = self.write_doc("docs/repeated.md", "---\nid: one\nid: two\n---\nBody\n")

        report = govern_documents(self.root, apply=True)

        self.assertFalse(report["ok"])
        self.assertTrue(self.issues(report, "invalid_yaml"))
        self.assertTrue(self.issues(report, "frontmatter_not_mapping"))
        self.assertTrue(self.issues(report, "duplicate_key"))
        for path, content in (
            (malformed, "---\ntitle: [\n---\nBody\n"),
            (scalar, "---\njust a scalar\n---\nBody\n"),
            (null, "---\nnull\n---\nBody\n"),
            (repeated, "---\nid: one\nid: two\n---\nBody\n"),
        ):
            self.assertEqual(path.read_text(), content)

    def test_scope_rejects_traversal_and_symlinks(self) -> None:
        outside = self.root.parent / f"{self.root.name}-outside"
        outside.mkdir()
        try:
            with self.assertRaises(ValueError):
                iter_document_files(self.root, ["../outside"])
            self.assertEqual(iter_document_files(self.root, []), [])
            link = self.root / "linked-docs"
            try:
                link.symlink_to(outside, target_is_directory=True)
            except OSError:
                self.skipTest("symlink creation is unavailable")
            report = govern_documents(self.root, paths=["linked-docs"], apply=True)
            self.assertFalse(report["ok"])
            self.assertTrue(self.issues(report, "scope_symlink"))
            self.assertEqual(document_roots(self.root, paths=["linked-docs"]), [])
        finally:
            outside.rmdir()

    def test_nested_symlink_and_unsafe_markdown_link_block_writes(self) -> None:
        doc = self.write_doc("docs/guide.md", "# Guide\n\n[escape](../../outside.md)\n")
        target = self.root / "outside.md"
        target.write_text("outside", encoding="utf-8")
        try:
            (self.root / "docs/link.md").symlink_to(target)
        except OSError:
            self.skipTest("symlink creation is unavailable")

        report = govern_documents(self.root, apply=True)

        self.assertFalse(report["ok"])
        self.assertTrue(self.issues(report, "external_reference_unverified"))
        self.assertTrue(self.issues(report, "document_symlink"))
        self.assertFalse((self.root / ".knowledge/documents.md").exists())
        self.assertFalse(doc.read_bytes().startswith(b"---"))

    def test_out_of_repo_evidence_link_is_warned_and_preserved(self) -> None:
        body = "# Evidence\n\n[Related project](../../reportHub-api/README.md)\n"
        doc = self.write_doc("docs/evidence.md", body)

        report = govern_documents(self.root, apply=True)

        self.assertTrue(report["ok"])
        self.assertTrue(self.issues(report, "external_reference_unverified"))
        self.assertIn(body, doc.read_text(encoding="utf-8"))
        self.assertTrue(doc.read_text(encoding="utf-8").startswith("---\n"))
        self.assertTrue((self.root / ".knowledge/documents.md").exists())

    def test_navigation_does_not_overwrite_project_indexes(self) -> None:
        index = self.write_doc("docs/INDEX.md", "# Project index\n")
        readme = self.write_doc("docs/README.md", "# Existing navigation\n")
        doc = self.write_doc("docs/guide.md", "# Guide\n")

        report = govern_documents(self.root, apply=True)

        returned_paths = {item["path"] for item in report["files"]}
        self.assertIn("docs/guide.md", returned_paths)
        self.assertNotIn("docs/INDEX.md", returned_paths)
        self.assertNotIn("docs/README.md", returned_paths)
        self.assertEqual(index.read_text(), "# Project index\n")
        self.assertEqual(readme.read_text(), "# Existing navigation\n")
        self.assertTrue((self.root / ".knowledge/documents.md").exists())
        self.assertTrue(doc.read_text().startswith("---\n"))

    def test_document_paths_config_and_direct_markdown_selection(self) -> None:
        self.assertEqual(document_roots(self.root), ["docs"])
        self.assertEqual(document_roots(self.root, ["docs/guide.md"]), [])
        selected = self.write_doc("docs/guide.md", "# Guide\n")
        self.assertEqual(document_roots(self.root, ["docs/guide.md"]), ["docs/guide.md"])
        self.assertEqual(iter_document_files(self.root, ["docs/guide.md"]), [selected])
        self.assertEqual(document_roots(self.root, []), [])

    def test_explicit_root_scope_governs_root_markdown_but_skips_archives_and_rules(self) -> None:
        body = self.write_doc("body.md", "# Root document\n")
        archived = self.write_doc("archive/old.md", "# Old\n")
        instructions = self.write_doc("AGENTS.md", "# Instructions\n")
        nested_repo = self.write_doc("nested-project/knowledge.md", "# Nested repository\n")
        (nested_repo.parent / ".git").mkdir()

        report = govern_documents(self.root, paths=["."], apply=True)

        self.assertTrue(report["ok"])
        self.assertIn("body.md", {item["path"] for item in report["files"]})
        self.assertNotIn("nested-project/knowledge.md", {item["path"] for item in report["files"]})
        self.assertTrue(body.read_text(encoding="utf-8").startswith("---\n"))
        self.assertEqual(archived.read_text(encoding="utf-8"), "# Old\n")
        self.assertEqual(instructions.read_text(encoding="utf-8"), "# Instructions\n")
        self.assertEqual(nested_repo.read_text(encoding="utf-8"), "# Nested repository\n")


if __name__ == "__main__":
    unittest.main()
