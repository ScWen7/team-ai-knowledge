from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib
import json
import subprocess
import sys
import unittest

import yaml

from team_wiki.core import _rewrite_change_meta, create_change, doctor, index_workspace, parse_frontmatter, search
from team_wiki.project import handle_update, init_project, lock_latest, project_rules
from team_wiki.publication import record_publication
import test_v07 as fixtures


class ProjectGovernanceTests(unittest.TestCase):
    def test_project_initialization_preserves_existing_docs_and_indexes(self):
        with TemporaryDirectory() as td:
            root = Path(td) / "project"
            docs = root / "知识库/经验库"
            docs.mkdir(parents=True)
            original = b"# Build troubleshooting\n\nKeep **every word**.\n\n```sh\necho build\n```\n"
            path = docs / "build.md"
            path.write_bytes(original)
            index = root / "知识库/INDEX.md"
            index.write_text("# 项目自己的导航\n", encoding="utf-8")

            preview = init_project(root, project_id="project-demo", document_paths=["知识库"])
            self.assertTrue(preview["ok"], preview)
            self.assertEqual(path.read_bytes(), original)
            self.assertFalse((root / "wiki").exists())
            applied = init_project(root, project_id="project-demo", apply=True)
            self.assertTrue(applied["ok"], applied)
            self.assertTrue(path.read_bytes().endswith(original))
            self.assertEqual(index.read_text(encoding="utf-8"), "# 项目自己的导航\n")
            before = path.read_bytes()
            again = init_project(root, project_id="project-demo", apply=True)
            self.assertEqual(again["changed_paths"], [])
            self.assertEqual(path.read_bytes(), before)
            self.assertTrue(doctor(root).ok)
            index_workspace(root)
            hits = search(root, "build")
            self.assertEqual(hits[0]["path"], "知识库/经验库/build.md")
            self.assertNotEqual(hits[0]["status"], "active")

    def test_invalid_document_preflight_does_not_initialize(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "docs").mkdir()
            (root / "docs/broken.md").write_text("---\ntitle: [broken\n---\n# Body\n", encoding="utf-8")
            result = init_project(root, project_id="broken", document_paths=["docs"], apply=True)
            self.assertFalse(result["ok"])
            self.assertFalse((root / ".knowledge/config.yml").exists())

    def test_newer_configuration_is_never_silently_downgraded(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            config = root / ".knowledge/config.yml"
            config.parent.mkdir()
            original = "version: 2\nprofile: project\nrepository_id: next-version\n"
            config.write_text(original, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "does not migrate or downgrade"):
                init_project(root, project_id="next-version", apply=True)
            self.assertEqual(config.read_text(encoding="utf-8"), original)
            self.assertFalse((root / ".gitignore").exists())

    def test_cli_preview_apply_search_and_repeat(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "docs").mkdir()
            (root / "docs/case.md").write_text("# 构建缓存问题\n\n依赖更新后核对构建实际使用的版本。\n", encoding="utf-8")

            def cli(*args):
                return subprocess.run([sys.executable, "-m", "team_wiki", *args], text=True, capture_output=True)

            result = cli("project-init", str(root), "--project-id", "cli-demo", "--docs", "docs", "--apply")
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertTrue(json.loads(result.stdout)["initialized"])
            result = cli("search", str(root), "构建使用什么版本")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)[0]["path"], "docs/case.md")
            snapshot = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in root.rglob("*") if p.is_file()}
            result = cli("govern", str(root))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["changed_paths"], [])
            self.assertEqual(snapshot, {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                                       for p in root.rglob("*") if p.is_file()})

    def test_rules_read_all_without_work_and_keep_update_gate(self):
        fixture = fixtures.V07Tests()
        with TemporaryDirectory() as td:
            base = Path(td)
            team, project = base / "team", base / "project"
            fixture._init_team_repo(team)
            fixture._publish(team, body="不能静默丢弃的共同底线", requirement="notice", label="v1")
            init_project(project, project_id="consumer", team_repository_id="team-knowledge", knowledge_ids=["K-A"])
            lock_latest(project, team)
            result = project_rules(project, team)
            self.assertTrue(result["complete"])
            self.assertEqual([x["knowledge_id"] for x in result["rules"]], ["K-A"])
            self.assertIn("共同底线", result["rules"][0]["content"])
            self.assertFalse((project / ".knowledge/runs").exists())
            self.assertFalse((team / ".knowledge/records/adoptions").exists())
            fixture._publish(team, body="新强制底线", requirement="must-address", label="v2")
            blocked = project_rules(project, team)
            self.assertFalse(blocked["ok"])
            self.assertEqual(blocked["rules"], [])
            accepted = handle_update(project, team, "K-A", decision="accept", reason="已评估新底线影响")
            stored = yaml.safe_load((project / ".knowledge/records/update-decisions" / f"{accepted['decision_id']}.yml").read_text())
            self.assertEqual(stored["reason"], "已评估新底线影响")
            self.assertTrue(project_rules(project, team)["ok"])

    def test_lock_identity_tampering_is_rejected(self):
        fixture = fixtures.V07Tests()
        with TemporaryDirectory() as td:
            base = Path(td)
            team, project = base / "team", base / "project"
            fixture._init_team_repo(team)
            fixture._publish(team, body="底线", requirement="notice", label="v1")
            init_project(project, project_id="consumer", team_repository_id="team-knowledge", knowledge_ids=["K-A"])
            lock_path = lock_latest(project, team)
            lock = yaml.safe_load(lock_path.read_text())
            lock["entries"]["K-A"]["content_sha256"] = "wrong"
            lock_path.write_text(yaml.safe_dump(lock), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "identity mismatch"):
                project_rules(project, team)

    def test_publication_file_identity_tampering_is_rejected(self):
        fixture = fixtures.V07Tests()
        with TemporaryDirectory() as td:
            base = Path(td)
            team, project = base / "team", base / "project"
            fixture._init_team_repo(team)
            fixture._publish(team, body="底线", requirement="notice", label="v1")
            init_project(project, project_id="consumer", team_repository_id="team-knowledge", knowledge_ids=["K-A"])
            lock_latest(project, team)
            publication = next((team / ".knowledge/records/publications").glob("PUB-*.yml"))
            record = yaml.safe_load(publication.read_text())
            record["publication_id"] = "PUB-TAMPERED"
            publication.write_text(yaml.safe_dump(record), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "identity mismatch"):
                project_rules(project, team)

    def test_rules_are_not_limited_to_top_five(self):
        fixture = fixtures.V07Tests()
        with TemporaryDirectory() as td:
            base = Path(td)
            team, project = base / "team", base / "project"
            fixture._init_team_repo(team)
            ids = [f"RULE-{i}" for i in range(7)]
            changes = {}
            for kid in ids:
                (team / f"wiki/technical/{kid}.md").write_text(
                    f"---\nid: {kid}\ntitle: {kid}\ntype: rule\nstatus: active\n---\n\n必须遵守 {kid}。\n",
                    encoding="utf-8",
                )
                change = create_change(team, kid)
                _rewrite_change_meta(change, {"stage": "proposed"})
                changes[kid] = parse_frontmatter(change)[0]["change_id"]
            fixture._git(team, "add", ".")
            fixture._git(team, "commit", "-qm", "baseline rules fixture")
            for kid in ids:
                record_publication(team, changes[kid], kid, published_ref="HEAD")
            init_project(project, project_id="consumer", team_repository_id="team-knowledge", knowledge_ids=ids)
            lock_latest(project, team)
            result = project_rules(project, team)
            self.assertTrue(result["complete"])
            self.assertEqual([row["knowledge_id"] for row in result["rules"]], ids)


if __name__ == "__main__":
    unittest.main()
