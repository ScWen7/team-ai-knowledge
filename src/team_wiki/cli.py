import argparse
import json
from pathlib import Path

from .core import (
    adopt_knowledge,
    context_plan,
    create_change,
    doctor,
    finalize_work,
    index_workspace,
    init_team,
    observe_knowledge,
    prepare_work,
    record_evidence,
    register_source,
    related,
    search,
)
from .impact import refresh_source
from .candidate import apply_patch_plan, candidate_context, create_candidate, create_patch_plan, patch_plan_context
from .batch import batch_context, create_candidate_batch
from .dependency import dependency_impact
from .publication import adoption_status, list_publications, record_publication
from .project import (
    finalize_project_work,
    handle_update,
    init_project,
    lock_latest,
    prepare_project_work,
    project_adopt,
    project_context,
    project_gate,
    project_observe,
    project_status,
)
from .connector import connector_status, create_git_connector, sync_git_connector
from .evidence import bind_evidence, correct_evidence, list_bindings, read_evidence
from .intake import apply_disposition, audit_intake, intake_source, intake_status, source_pipeline_status
from .node_core import context_budget
from .review import list_reviews, resolve_review, upsert_review
from .scope import SourceScope, SourceScopeError


def dump(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def main():
    p = argparse.ArgumentParser(prog="team-wiki")
    sub = p.add_subparsers(dest="cmd", required=True)

    x = sub.add_parser("init"); x.add_argument("root"); x.add_argument("--repository-id")
    x = sub.add_parser("doctor"); x.add_argument("root")
    x = sub.add_parser("ingest"); x.add_argument("root"); x.add_argument("file"); x.add_argument("--title"); x.add_argument("--move", action="store_true"); x.add_argument("--connector", default="manual"); x.add_argument("--upstream-id"); x.add_argument("--logical-path")
    x = sub.add_parser("refresh-source"); x.add_argument("root"); x.add_argument("source_id"); x.add_argument("file"); x.add_argument("--owner", default="unassigned")
    x = sub.add_parser("source-status"); x.add_argument("root"); x.add_argument("source_id")
    x = sub.add_parser("intake-source"); x.add_argument("root"); x.add_argument("source_id"); x.add_argument("--max-chars", type=int, default=4000)
    x = sub.add_parser("intake-status"); x.add_argument("root"); x.add_argument("intake_id")
    x = sub.add_parser("intake-apply"); x.add_argument("root"); x.add_argument("intake_id"); x.add_argument("chunk_id"); x.add_argument("--status", required=True); x.add_argument("--note"); x.add_argument("--knowledge", action="append", default=[])
    x = sub.add_parser("intake-audit"); x.add_argument("root"); x.add_argument("intake_id")
    x = sub.add_parser("evidence-show"); x.add_argument("root"); x.add_argument("evidence_id"); x.add_argument("--raw", action="store_true")
    x = sub.add_parser("evidence-correct"); x.add_argument("root"); x.add_argument("evidence_id"); x.add_argument("--text-file", required=True); x.add_argument("--reason", required=True); x.add_argument("--verified-by", required=True)
    x = sub.add_parser("evidence-bind"); x.add_argument("root"); x.add_argument("evidence_id"); x.add_argument("--target-kind", required=True); x.add_argument("--target-id", required=True); x.add_argument("--relation", required=True); x.add_argument("--note", default="")
    x = sub.add_parser("evidence-bindings"); x.add_argument("root"); x.add_argument("--evidence-id"); x.add_argument("--target-id")
    x = sub.add_parser("candidate-create"); x.add_argument("root"); x.add_argument("--proposed-id", required=True); x.add_argument("--title", required=True); x.add_argument("--type", required=True); x.add_argument("--statement", required=True); x.add_argument("--owner", default="unassigned"); x.add_argument("--scope", default="team")
    x = sub.add_parser("candidate-show"); x.add_argument("root"); x.add_argument("candidate_id")
    x = sub.add_parser("patch-plan"); x.add_argument("root"); x.add_argument("candidate_id"); x.add_argument("--comparison", required=True); x.add_argument("--summary", required=True); x.add_argument("--owner", default="unassigned"); x.add_argument("--target-id"); x.add_argument("--target-path")
    x = sub.add_parser("patch-context"); x.add_argument("root"); x.add_argument("plan_id")
    x = sub.add_parser("patch-apply"); x.add_argument("root"); x.add_argument("plan_id"); x.add_argument("content_file")
    x = sub.add_parser("batch-create"); x.add_argument("root"); x.add_argument("candidate_ids", nargs="+"); x.add_argument("--title", required=True); x.add_argument("--statement", required=True); x.add_argument("--owner", default="unassigned"); x.add_argument("--scope", default="team")
    x = sub.add_parser("batch-show"); x.add_argument("root"); x.add_argument("batch_id")
    x = sub.add_parser("dependency-impact"); x.add_argument("root"); x.add_argument("knowledge_id"); x.add_argument("--direct-only", action="store_true")
    x = sub.add_parser("publish"); x.add_argument("root"); x.add_argument("change_id"); x.add_argument("knowledge_id"); x.add_argument("--ref", default="HEAD"); x.add_argument("--requirement", default="notice"); x.add_argument("--effective-at")
    x = sub.add_parser("publication-list"); x.add_argument("root"); x.add_argument("--knowledge-id")
    x = sub.add_parser("adoption-status"); x.add_argument("root"); x.add_argument("knowledge_id")


    x = sub.add_parser("project-init"); x.add_argument("root"); x.add_argument("--project-id", required=True); x.add_argument("--team-repository-id", required=True); x.add_argument("--knowledge-id", action="append", required=True)
    x = sub.add_parser("project-lock"); x.add_argument("root"); x.add_argument("team_root"); x.add_argument("--knowledge-id", action="append")
    x = sub.add_parser("project-status"); x.add_argument("root"); x.add_argument("team_root")
    x = sub.add_parser("project-update"); x.add_argument("root"); x.add_argument("team_root"); x.add_argument("knowledge_id"); x.add_argument("--decision", required=True, choices=["accept", "defer"]); x.add_argument("--reason", default="")
    x = sub.add_parser("project-gate"); x.add_argument("root"); x.add_argument("team_root"); x.add_argument("--phase", required=True, choices=["start", "release"])
    x = sub.add_parser("project-prepare"); x.add_argument("root"); x.add_argument("team_root"); x.add_argument("--goal", required=True)
    x = sub.add_parser("project-context"); x.add_argument("root"); x.add_argument("team_root"); x.add_argument("work_id"); x.add_argument("knowledge_id")
    x = sub.add_parser("project-adopt"); x.add_argument("root"); x.add_argument("work_id"); x.add_argument("knowledge_id"); x.add_argument("--used-for", required=True)
    x = sub.add_parser("project-observe"); x.add_argument("root"); x.add_argument("work_id"); x.add_argument("knowledge_id"); x.add_argument("--outcome", required=True); x.add_argument("--note", required=True); x.add_argument("--evidence", action="append", default=[])
    x = sub.add_parser("project-finalize"); x.add_argument("root"); x.add_argument("team_root"); x.add_argument("work_id")

    x = sub.add_parser("connector-add-git"); x.add_argument("root"); x.add_argument("connector_id"); x.add_argument("--repository-id", required=True); x.add_argument("--include", action="append", default=[]); x.add_argument("--logical-root"); x.add_argument("--auto-intake", action="store_true")
    x = sub.add_parser("connector-status"); x.add_argument("root"); x.add_argument("connector_id")
    x = sub.add_parser("connector-sync"); x.add_argument("root"); x.add_argument("connector_id"); x.add_argument("repo_path"); x.add_argument("--owner", default="unassigned")

    x = sub.add_parser("index"); x.add_argument("root")
    x = sub.add_parser("change"); x.add_argument("root"); x.add_argument("title"); x.add_argument("--owner", default="unassigned")
    x = sub.add_parser("prepare"); x.add_argument("root"); x.add_argument("--goal", required=True); x.add_argument("--consumer")
    x = sub.add_parser("search"); x.add_argument("root"); x.add_argument("query")
    x = sub.add_parser("related"); x.add_argument("root"); x.add_argument("knowledge_id"); x.add_argument("--limit", type=int, default=5)
    x = sub.add_parser("context"); x.add_argument("root"); x.add_argument("query"); x.add_argument("--max-context", type=int); x.add_argument("--limit", type=int, default=5)
    x = sub.add_parser("budget"); x.add_argument("--max-context", type=int)
    x = sub.add_parser("adopt"); x.add_argument("root"); x.add_argument("work_id"); x.add_argument("knowledge_id"); x.add_argument("--used-for", required=True)
    x = sub.add_parser("evidence"); x.add_argument("root"); x.add_argument("work_id"); x.add_argument("--kind", required=True); x.add_argument("--locator", required=True); x.add_argument("--summary", required=True)
    x = sub.add_parser("observe"); x.add_argument("root"); x.add_argument("work_id"); x.add_argument("knowledge_id"); x.add_argument("--outcome", required=True); x.add_argument("--note", required=True); x.add_argument("--evidence", action="append", default=[])
    x = sub.add_parser("finalize"); x.add_argument("root"); x.add_argument("work_id"); x.add_argument("--owner", default="unassigned")

    x = sub.add_parser("review-list"); x.add_argument("root"); x.add_argument("--state")
    x = sub.add_parser("review-upsert"); x.add_argument("root"); x.add_argument("kind"); x.add_argument("title"); x.add_argument("--description", required=True); x.add_argument("--owner", default="unassigned"); x.add_argument("--scope-key", default="team"); x.add_argument("--evidence-version"); x.add_argument("--observation")
    x = sub.add_parser("review-resolve"); x.add_argument("root"); x.add_argument("review_id"); x.add_argument("--action", required=True); x.add_argument("--note", required=True); x.add_argument("--evidence-version"); x.add_argument("--dismiss", action="store_true")

    x = sub.add_parser("scope-list"); x.add_argument("root"); x.add_argument("--wiki-root", default=".project-wiki")
    x = sub.add_parser("scope-read"); x.add_argument("root"); x.add_argument("path"); x.add_argument("--wiki-root", default=".project-wiki"); x.add_argument("--start-line", type=int, default=1); x.add_argument("--end-line", type=int)
    x = sub.add_parser("scope-search"); x.add_argument("root"); x.add_argument("pattern"); x.add_argument("--wiki-root", default=".project-wiki"); x.add_argument("--limit", type=int, default=100)

    a = p.parse_args()
    if a.cmd == "budget":
        dump(context_budget(a.max_context)); return

    root = Path(a.root).resolve()
    try:
        if a.cmd == "init": init_team(root, a.repository_id); index_workspace(root); print(root)
        elif a.cmd == "doctor":
            r = doctor(root); dump({"ok": r.ok, "errors": r.errors, "warnings": r.warnings}); raise SystemExit(0 if r.ok else 1)
        elif a.cmd == "ingest": print(register_source(root, Path(a.file).resolve(), a.title, a.move, connector_id=a.connector, upstream_id=a.upstream_id, logical_path=a.logical_path)); index_workspace(root)
        elif a.cmd == "refresh-source": dump(refresh_source(root, a.source_id, Path(a.file).resolve(), owner=a.owner))
        elif a.cmd == "source-status": dump(source_pipeline_status(root, a.source_id))
        elif a.cmd == "intake-source": print(intake_source(root, a.source_id, max_chars=a.max_chars))
        elif a.cmd == "intake-status": dump(intake_status(root, a.intake_id))
        elif a.cmd == "intake-apply": dump(apply_disposition(root, a.intake_id, a.chunk_id, status=a.status, note=a.note, knowledge_ids=a.knowledge))
        elif a.cmd == "intake-audit": dump(audit_intake(root, a.intake_id))
        elif a.cmd == "evidence-show": dump(read_evidence(root, a.evidence_id, corrected=not a.raw))
        elif a.cmd == "evidence-correct":
            new_text = Path(a.text_file).read_text(encoding="utf-8")
            print(correct_evidence(root, a.evidence_id, new_text=new_text, reason=a.reason, verified_by=a.verified_by))
        elif a.cmd == "evidence-bind":
            print(bind_evidence(root, a.evidence_id, target_kind=a.target_kind, target_id=a.target_id, relation=a.relation, note=a.note))
        elif a.cmd == "evidence-bindings": dump(list_bindings(root, evidence_id=a.evidence_id, target_id=a.target_id))
        elif a.cmd == "candidate-create":
            print(create_candidate(root, proposed_id=a.proposed_id, title=a.title, knowledge_type=a.type, statement=a.statement, owner=a.owner, scope=a.scope))
        elif a.cmd == "candidate-show": dump(candidate_context(root, a.candidate_id))
        elif a.cmd == "patch-plan":
            print(create_patch_plan(root, a.candidate_id, comparison=a.comparison, summary=a.summary, owner=a.owner, target_knowledge_id=a.target_id, target_path=a.target_path))
        elif a.cmd == "patch-context": dump(patch_plan_context(root, a.plan_id))
        elif a.cmd == "patch-apply": print(apply_patch_plan(root, a.plan_id, Path(a.content_file).resolve()))
        elif a.cmd == "batch-create":
            print(create_candidate_batch(root, a.candidate_ids, title=a.title, merged_statement=a.statement, owner=a.owner, scope=a.scope))
        elif a.cmd == "batch-show": dump(batch_context(root, a.batch_id))
        elif a.cmd == "dependency-impact": dump(dependency_impact(root, a.knowledge_id, transitive=not a.direct_only))
        elif a.cmd == "publish":
            print(record_publication(root, a.change_id, a.knowledge_id, published_ref=a.ref, adoption_requirement=a.requirement, effective_at=a.effective_at))
        elif a.cmd == "publication-list": dump(list_publications(root, knowledge_id=a.knowledge_id))
        elif a.cmd == "adoption-status": dump(adoption_status(root, a.knowledge_id))
        elif a.cmd == "project-init":
            init_project(root, project_id=a.project_id, team_repository_id=a.team_repository_id, knowledge_ids=a.knowledge_id)
            print(root)
        elif a.cmd == "project-lock":
            print(lock_latest(root, Path(a.team_root).resolve(), knowledge_ids=a.knowledge_id))
        elif a.cmd == "project-status":
            dump(project_status(root, Path(a.team_root).resolve()))
        elif a.cmd == "project-update":
            dump(handle_update(root, Path(a.team_root).resolve(), a.knowledge_id, decision=a.decision, reason=a.reason))
        elif a.cmd == "project-gate":
            result = project_gate(root, Path(a.team_root).resolve(), phase=a.phase); dump(result); raise SystemExit(0 if result["ok"] else 1)
        elif a.cmd == "project-prepare":
            print(prepare_project_work(root, Path(a.team_root).resolve(), goal=a.goal))
        elif a.cmd == "project-context":
            dump(project_context(root, Path(a.team_root).resolve(), a.work_id, a.knowledge_id))
        elif a.cmd == "project-adopt":
            dump(project_adopt(root, a.work_id, a.knowledge_id, used_for=a.used_for))
        elif a.cmd == "project-observe":
            dump(project_observe(root, a.work_id, a.knowledge_id, outcome=a.outcome, note=a.note, evidence_ids=a.evidence))
        elif a.cmd == "project-finalize":
            dump(finalize_project_work(root, Path(a.team_root).resolve(), a.work_id))
        elif a.cmd == "connector-add-git":
            print(create_git_connector(root, a.connector_id, repository_id=a.repository_id, include_paths=a.include or ["."], logical_root=a.logical_root, auto_intake=a.auto_intake))
        elif a.cmd == "connector-status": dump(connector_status(root, a.connector_id))
        elif a.cmd == "connector-sync": dump(sync_git_connector(root, a.connector_id, Path(a.repo_path).resolve(), owner=a.owner))
        elif a.cmd == "index": index_workspace(root); print("indexed")
        elif a.cmd == "change": print(create_change(root, a.title, a.owner)); index_workspace(root)
        elif a.cmd == "prepare": print(prepare_work(root, a.goal, consumer_id=a.consumer))
        elif a.cmd == "search": dump(search(root, a.query))
        elif a.cmd == "related": dump(related(root, a.knowledge_id, a.limit))
        elif a.cmd == "context": dump(context_plan(root, a.query, a.max_context, a.limit))
        elif a.cmd == "adopt": dump(adopt_knowledge(root, a.work_id, a.knowledge_id, a.used_for))
        elif a.cmd == "evidence": print(record_evidence(root, a.work_id, a.kind, a.locator, a.summary))
        elif a.cmd == "observe": dump(observe_knowledge(root, a.work_id, a.knowledge_id, a.outcome, a.note, a.evidence))
        elif a.cmd == "finalize": dump(finalize_work(root, a.work_id, a.owner))
        elif a.cmd == "review-list": dump(list_reviews(root, state=a.state))
        elif a.cmd == "review-upsert":
            path = upsert_review(root, kind=a.kind, title=a.title, description=a.description, owner=a.owner, scope_key=a.scope_key, evidence_version=a.evidence_version, observation=a.observation)
            index_workspace(root); print(path)
        elif a.cmd == "review-resolve":
            path = resolve_review(root, a.review_id, action=a.action, note=a.note, evidence_version=a.evidence_version, dismiss=a.dismiss)
            index_workspace(root); print(path)
        elif a.cmd == "scope-list":
            with SourceScope(root, a.wiki_root) as scope: dump([p.relative_to(root).as_posix() for p in scope.source_files()])
        elif a.cmd == "scope-read":
            with SourceScope(root, a.wiki_root) as scope:
                content = scope.read_source(a.path, start_line=a.start_line, end_line=a.end_line)
                if content is None: raise SystemExit(2)
                print(content, end="")
        elif a.cmd == "scope-search":
            with SourceScope(root, a.wiki_root) as scope: dump(scope.search(a.pattern, limit=a.limit))
    except (KeyError, ValueError, SourceScopeError) as exc:
        p.error(str(exc))


if __name__ == "__main__":
    main()
