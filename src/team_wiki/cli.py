import argparse
import json
import sys
import yaml
from pathlib import Path

from . import __version__
from .core import (
    adopt_knowledge,
    context_plan,
    context_budget,
    create_change,
    doctor,
    finalize_work,
    index_workspace,
    init_team,
    observe_knowledge,
    prepare_work,
    record_evidence,
    register_source,
    read_yaml,
    related,
    search_report,
)
from .stale import build_stale_report, format_stale_report
from .impact import refresh_source
from .candidate import apply_patch_plan, candidate_context, create_candidate, create_patch_plan, patch_plan_context, plan_patch
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
    project_rules,
    project_status,
    run_project_work,
)
from .connector import connector_status, create_git_connector, sync_git_connector
from .evidence import bind_evidence, correct_evidence, list_bindings, read_evidence
from .intake import apply_disposition, audit_intake, decide_intake, intake_source, intake_status, source_pipeline_status
from .documents import govern_documents
from .agent_entry import setup_agent_entry
from .evaluation import evaluate
from .connections import connected_query
from .review import list_reviews, resolve_review, upsert_review
from .scope import SourceScope, SourceScopeError
from .status import build_status_report, format_status_report


FROZEN_COMMANDS = frozenset({
    "ingest", "refresh-source", "source-status",
    "intake-source", "intake-status", "intake-apply", "intake-decide", "intake-audit",
    "evidence-show", "evidence-correct", "evidence-bind", "evidence-bindings",
    "candidate-create", "candidate-show",
    "patch-plan", "patch-plan-direct", "patch-context", "patch-apply",
    "dependency-impact", "adoption-status",
    "connector-add-git", "connector-status", "connector-sync",
    "scope-list", "scope-read", "scope-search",
    "prepare", "adopt", "evidence", "observe", "finalize", "budget",
    "project-prepare", "project-context", "project-adopt", "project-observe",
    "project-finalize", "project-work",
})


def dump(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def main():
    p = argparse.ArgumentParser(prog="team-wiki", epilog="旧协议命令(ingest、intake-*、evidence-*、candidate-*、patch-*、connector-*、scope-*、dependency-impact、prepare/adopt/observe/finalize、project-work 等)已冻结：不出现在帮助中，仍可调用但不再扩展。")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="<command>")

    x = sub.add_parser("init", help="创建团队知识库"); x.add_argument("root"); x.add_argument("--repository-id")
    x = sub.add_parser("status", help="已观测待处理事项，不要求登记或采用记录"); x.add_argument("root"); x.add_argument("--history", action="store_true", help="显式查看时间与旧采用记录线索"); x.add_argument("--zero-adoption-days", type=int, default=90); x.add_argument("--stale-active-days", type=int, default=180); x.add_argument("--draft-days", type=int, default=60); x.add_argument("--review-days", type=int, default=14); x.add_argument("--inbox-limit", type=int, default=3)
    x = sub.add_parser("doctor", help="检查知识库结构与健康"); x.add_argument("root"); x.add_argument("--report", choices=["default", "stale"], default="default"); x.add_argument("--zero-adoption-days", type=int, default=90); x.add_argument("--stale-active-days", type=int, default=180); x.add_argument("--draft-days", type=int, default=60)
    x = sub.add_parser("ingest"); x.add_argument("root"); x.add_argument("file"); x.add_argument("--title"); x.add_argument("--move", action="store_true"); x.add_argument("--connector", default="manual"); x.add_argument("--upstream-id"); x.add_argument("--logical-path")
    x = sub.add_parser("refresh-source"); x.add_argument("root"); x.add_argument("source_id"); x.add_argument("file"); x.add_argument("--owner", default="unassigned")
    x = sub.add_parser("source-status"); x.add_argument("root"); x.add_argument("source_id")
    x = sub.add_parser("intake-source"); x.add_argument("root"); x.add_argument("source_id"); x.add_argument("--max-chars", type=int, default=4000)
    x = sub.add_parser("intake-status"); x.add_argument("root"); x.add_argument("intake_id")
    x = sub.add_parser("intake-apply"); x.add_argument("root"); x.add_argument("intake_id"); x.add_argument("chunk_id"); x.add_argument("--status", required=True); x.add_argument("--note"); x.add_argument("--knowledge", action="append", default=[])
    x = sub.add_parser("intake-decide"); x.add_argument("root"); x.add_argument("intake_id"); x.add_argument("--keep", action="append", default=[]); x.add_argument("--keep-evidence", action="append", default=[]); x.add_argument("--with-knowledge", action="append", default=[], metavar="CHUNK_OR_EVIDENCE:K-ID"); x.add_argument("--reset", action="store_true"); x.add_argument("--keep-all", action="store_true")
    x = sub.add_parser("intake-audit"); x.add_argument("root"); x.add_argument("intake_id")
    x = sub.add_parser("evidence-show"); x.add_argument("root"); x.add_argument("evidence_id"); x.add_argument("--raw", action="store_true")
    x = sub.add_parser("evidence-correct"); x.add_argument("root"); x.add_argument("evidence_id"); x.add_argument("--text-file", required=True); x.add_argument("--reason", required=True); x.add_argument("--verified-by", required=True)
    x = sub.add_parser("evidence-bind"); x.add_argument("root"); x.add_argument("evidence_id"); x.add_argument("--target-kind", required=True); x.add_argument("--target-id", required=True); x.add_argument("--relation", required=True); x.add_argument("--note", default="")
    x = sub.add_parser("evidence-bindings"); x.add_argument("root"); x.add_argument("--evidence-id"); x.add_argument("--target-id")
    x = sub.add_parser("candidate-create"); x.add_argument("root"); x.add_argument("--proposed-id", required=True); x.add_argument("--title", required=True); x.add_argument("--type", required=True); x.add_argument("--statement", required=True); x.add_argument("--owner", default="unassigned"); x.add_argument("--scope", default="team")
    x = sub.add_parser("candidate-show"); x.add_argument("root"); x.add_argument("candidate_id")
    x = sub.add_parser("patch-plan"); x.add_argument("root"); x.add_argument("candidate_id", nargs="?"); x.add_argument("--comparison", required=True); x.add_argument("--summary", required=True); x.add_argument("--owner", default="unassigned"); x.add_argument("--target-id"); x.add_argument("--target-path")
    x = sub.add_parser("patch-plan-direct"); x.add_argument("root"); x.add_argument("--knowledge", required=True); x.add_argument("--comparison", required=True); x.add_argument("--summary", required=True); x.add_argument("--statement", required=True); x.add_argument("--evidence", action="append", default=[], metavar="EVIDENCE_ID"); x.add_argument("--title"); x.add_argument("--type", default="rule"); x.add_argument("--owner", default="unassigned"); x.add_argument("--scope", default="team"); x.add_argument("--target-path")
    x = sub.add_parser("patch-context"); x.add_argument("root"); x.add_argument("plan_id")
    x = sub.add_parser("patch-apply"); x.add_argument("root"); x.add_argument("plan_id"); x.add_argument("content_file")
    x = sub.add_parser("dependency-impact"); x.add_argument("root"); x.add_argument("knowledge_id"); x.add_argument("--direct-only", action="store_true")
    x = sub.add_parser("publish", help="为已提交的规则生成发布记录(规则发布链)"); x.add_argument("root"); x.add_argument("change_id"); x.add_argument("knowledge_id"); x.add_argument("--ref", default="HEAD"); x.add_argument("--requirement", default="notice"); x.add_argument("--effective-at")
    x = sub.add_parser("publication-list", help="列出发布记录"); x.add_argument("root"); x.add_argument("--knowledge-id")
    x = sub.add_parser("adoption-status"); x.add_argument("root"); x.add_argument("knowledge_id")


    x = sub.add_parser("project-init", help="接入原有资料，不要求先整理元信息"); x.add_argument("root"); x.add_argument("--project-id", required=True); x.add_argument("--team-root", help="本机明确授权的团队库路径，只保存到忽略的 local.yml"); x.add_argument("--team-repository-id"); x.add_argument("--knowledge-id", action="append"); x.add_argument("--docs", action="append"); x.add_argument("--apply", action="store_true", help="应用可确定的元信息补全并生成导航")
    x = sub.add_parser("agent-entry", help="安装当前 Agent 的知识使用约定"); x.add_argument("root"); x.add_argument("--apply", action="store_true"); x.add_argument("--entry-file", choices=["AGENTS.md", "CLAUDE.md"], default="AGENTS.md")
    x = sub.add_parser("eval", help="用 .knowledge/eval.yml 的真实问题测量检索召回"); x.add_argument("root"); x.add_argument("-k", type=int, default=5)
    x = sub.add_parser("govern", help="预览或应用项目文档治理"); x.add_argument("root"); x.add_argument("--docs", action="append"); x.add_argument("--apply", action="store_true")
    x = sub.add_parser("project-rules", help="完整读取已订阅底线；可从本机路径映射解析团队库"); x.add_argument("root"); x.add_argument("team_root", nargs="?"); x.add_argument("--phase", choices=["start", "release"], default="start")
    x = sub.add_parser("project-lock", help="锁定已订阅底线的发布版本"); x.add_argument("root"); x.add_argument("team_root"); x.add_argument("--knowledge-id", action="append")
    x = sub.add_parser("project-status", help="查看底线锁定与更新状态"); x.add_argument("root"); x.add_argument("team_root")
    x = sub.add_parser("project-update", help="接受或延后一条底线更新"); x.add_argument("root"); x.add_argument("team_root"); x.add_argument("knowledge_id"); x.add_argument("--decision", required=True, choices=["accept", "defer"]); x.add_argument("--reason", default="")
    x = sub.add_parser("project-gate", help="检查 start/release 阶段的底线要求"); x.add_argument("root"); x.add_argument("team_root"); x.add_argument("--phase", required=True, choices=["start", "release"])
    x = sub.add_parser("project-prepare"); x.add_argument("root"); x.add_argument("team_root"); x.add_argument("--goal", required=True)
    x = sub.add_parser("project-context"); x.add_argument("root"); x.add_argument("team_root"); x.add_argument("work_id"); x.add_argument("knowledge_id")
    x = sub.add_parser("project-adopt"); x.add_argument("root"); x.add_argument("work_id"); x.add_argument("knowledge_id"); x.add_argument("--used-for", required=True)
    x = sub.add_parser("project-observe"); x.add_argument("root"); x.add_argument("work_id"); x.add_argument("knowledge_id"); x.add_argument("--outcome", required=True); x.add_argument("--note", required=True); x.add_argument("--evidence", action="append", default=[])
    x = sub.add_parser("project-finalize"); x.add_argument("root"); x.add_argument("team_root"); x.add_argument("work_id")
    x = sub.add_parser("project-work"); x.add_argument("root"); x.add_argument("team_root"); x.add_argument("--phase", required=True, choices=["start", "finish"]); x.add_argument("--goal"); x.add_argument("--work-id", dest="work_id_arg"); x.add_argument("--read", action="append", default=[]); x.add_argument("--adopt", action="append", default=[]); x.add_argument("--used-for", action="append", default=[]); x.add_argument("--observe", action="append", default=[], metavar="K-ID:OUTCOME[:NOTE]"); x.add_argument("--evidence", action="append", default=[], metavar="K-ID:EVIDENCE_ID")

    x = sub.add_parser("connector-add-git"); x.add_argument("root"); x.add_argument("connector_id"); x.add_argument("--repository-id", required=True); x.add_argument("--include", action="append", default=[]); x.add_argument("--logical-root"); x.add_argument("--auto-intake", action="store_true")
    x = sub.add_parser("connector-status"); x.add_argument("root"); x.add_argument("connector_id")
    x = sub.add_parser("connector-sync"); x.add_argument("root"); x.add_argument("connector_id"); x.add_argument("repo_path"); x.add_argument("--owner", default="unassigned")

    x = sub.add_parser("index", help="更新团队库导航；项目库仅检查"); x.add_argument("root")
    x = sub.add_parser("change", help="创建知识变更记录(规则发布链)"); x.add_argument("root"); x.add_argument("title"); x.add_argument("--owner", default="unassigned")
    x = sub.add_parser("prepare"); x.add_argument("root"); x.add_argument("--goal", required=True); x.add_argument("--consumer")
    x = sub.add_parser("search", help="查找候选资料，随后由当前 Agent 读原文回答"); x.add_argument("root"); x.add_argument("--connected", action="store_true", help="同时查找本机明确接入的库，分库返回"); x.add_argument("query"); x.add_argument("--status", action="append"); x.add_argument("--scope"); x.add_argument("--limit", type=int)
    x = sub.add_parser("related", help="显式引用与反向引用"); x.add_argument("root"); x.add_argument("knowledge_id"); x.add_argument("--limit", type=int, default=5)
    x = sub.add_parser("context", help="检索计划(直接命中+显式关联)"); x.add_argument("root"); x.add_argument("--connected", action="store_true"); x.add_argument("query"); x.add_argument("--max-context", type=int); x.add_argument("--limit", type=int, default=5); x.add_argument("--status", action="append"); x.add_argument("--scope")
    x = sub.add_parser("budget"); x.add_argument("--max-context", type=int)
    x = sub.add_parser("adopt"); x.add_argument("root"); x.add_argument("work_id"); x.add_argument("knowledge_id"); x.add_argument("--used-for", required=True)
    x = sub.add_parser("evidence"); x.add_argument("root"); x.add_argument("work_id"); x.add_argument("--kind", required=True); x.add_argument("--locator", required=True); x.add_argument("--summary", required=True)
    x = sub.add_parser("observe"); x.add_argument("root"); x.add_argument("work_id"); x.add_argument("knowledge_id"); x.add_argument("--outcome", required=True); x.add_argument("--note", required=True); x.add_argument("--evidence", action="append", default=[])
    x = sub.add_parser("finalize"); x.add_argument("root"); x.add_argument("work_id"); x.add_argument("--owner", default="unassigned")

    x = sub.add_parser("review-list", help="列出待处理 Review"); x.add_argument("root"); x.add_argument("--state")
    x = sub.add_parser("review-upsert", help="创建或更新 Review"); x.add_argument("root"); x.add_argument("kind"); x.add_argument("title"); x.add_argument("--description", required=True); x.add_argument("--owner", default="unassigned"); x.add_argument("--scope-key", default="team"); x.add_argument("--evidence-version"); x.add_argument("--observation")
    x = sub.add_parser("review-resolve", help="处理 Review"); x.add_argument("root"); x.add_argument("review_id"); x.add_argument("--action", required=True); x.add_argument("--note", required=True); x.add_argument("--evidence-version"); x.add_argument("--dismiss", action="store_true")

    x = sub.add_parser("scope-list"); x.add_argument("root"); x.add_argument("--wiki-root", default=".project-wiki")
    x = sub.add_parser("scope-read"); x.add_argument("root"); x.add_argument("path"); x.add_argument("--wiki-root", default=".project-wiki"); x.add_argument("--start-line", type=int, default=1); x.add_argument("--end-line", type=int)
    x = sub.add_parser("scope-search"); x.add_argument("root"); x.add_argument("pattern"); x.add_argument("--wiki-root", default=".project-wiki"); x.add_argument("--limit", type=int, default=100)

    a = p.parse_args()
    if a.cmd in FROZEN_COMMANDS:
        print(f"notice: `{a.cmd}` 属于已冻结的旧协议命令，不再扩展；日常使用见 README。", file=sys.stderr)
    try:
        if a.cmd == "budget":
            dump(context_budget(a.max_context)); return
        root = Path(a.root).resolve()
        if a.cmd == "init": init_team(root, a.repository_id); index_workspace(root); print(root)
        elif a.cmd == "status":
            report = build_status_report(
                root,
                zero_adoption_days=a.zero_adoption_days,
                stale_active_days=a.stale_active_days,
                draft_days=a.draft_days,
                review_days=a.review_days,
                inbox_limit=a.inbox_limit, include_history=a.history,
            )
            print(format_status_report(report))
            dump({
                "total": len(report.decisions),
                "blocking_count": len(report.blocking),
                "attention_count": len(report.attention),
                "decisions": [d.as_dict() for d in report.decisions],
            })
        elif a.cmd == "doctor":
            if a.report == "stale":
                report = build_stale_report(
                    root,
                    zero_adoption_days=a.zero_adoption_days,
                    stale_active_days=a.stale_active_days,
                    draft_days=a.draft_days,
                )
                print(format_stale_report(report))
                dump({
                    "zero_adoption_publications": report.zero_adoption_publications,
                    "stale_active_knowledge": report.stale_active_knowledge,
                    "long_lived_drafts": report.long_lived_drafts,
                    "total": report.total,
                })
                raise SystemExit(0)
            r = doctor(root); dump({"ok": r.ok, "errors": r.errors, "warnings": r.warnings}); raise SystemExit(0 if r.ok else 1)
        elif a.cmd == "ingest": print(register_source(root, Path(a.file).resolve(), a.title, a.move, connector_id=a.connector, upstream_id=a.upstream_id, logical_path=a.logical_path)); index_workspace(root)
        elif a.cmd == "refresh-source": dump(refresh_source(root, a.source_id, Path(a.file).resolve(), owner=a.owner))
        elif a.cmd == "source-status": dump(source_pipeline_status(root, a.source_id))
        elif a.cmd == "intake-source": print(intake_source(root, a.source_id, max_chars=a.max_chars))
        elif a.cmd == "intake-status": dump(intake_status(root, a.intake_id))
        elif a.cmd == "intake-apply": dump(apply_disposition(root, a.intake_id, a.chunk_id, status=a.status, note=a.note, knowledge_ids=a.knowledge))
        elif a.cmd == "intake-decide":
            with_knowledge: dict[str, list[str]] = {}
            for item in a.with_knowledge:
                key, _, kid = str(item).partition(":")
                if not key or not kid:
                    raise ValueError(f"--with-knowledge expects CHUNK_OR_EVIDENCE:K-ID, got: {item}")
                with_knowledge.setdefault(key, []).append(kid)
            dump(decide_intake(
                root, a.intake_id,
                keep=a.keep, keep_evidence=a.keep_evidence,
                knowledge=with_knowledge, skip_rest=not a.keep_all, reset=a.reset,
            ))
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
            if not a.candidate_id:
                raise ValueError("patch-plan requires a candidate_id (or use patch-plan-direct)")
            print(create_patch_plan(root, a.candidate_id, comparison=a.comparison, summary=a.summary, owner=a.owner, target_knowledge_id=a.target_id, target_path=a.target_path))
        elif a.cmd == "patch-plan-direct":
            print(plan_patch(
                root, knowledge_id=a.knowledge, comparison=a.comparison,
                summary=a.summary, statement=a.statement, title=a.title,
                knowledge_type=a.type, evidence_ids=a.evidence, owner=a.owner,
                scope=a.scope, target_path=a.target_path,
            )["plan_id"])
        elif a.cmd == "patch-context": dump(patch_plan_context(root, a.plan_id))
        elif a.cmd == "patch-apply": print(apply_patch_plan(root, a.plan_id, Path(a.content_file).resolve()))
        elif a.cmd == "dependency-impact": dump(dependency_impact(root, a.knowledge_id, transitive=not a.direct_only))
        elif a.cmd == "publish":
            print(record_publication(root, a.change_id, a.knowledge_id, published_ref=a.ref, adoption_requirement=a.requirement, effective_at=a.effective_at))
        elif a.cmd == "publication-list": dump(list_publications(root, knowledge_id=a.knowledge_id))
        elif a.cmd == "adoption-status": dump(adoption_status(root, a.knowledge_id))
        elif a.cmd == "project-init":
            result = init_project(root, project_id=a.project_id, team_repository_id=a.team_repository_id, knowledge_ids=a.knowledge_id, document_paths=a.docs, apply=a.apply, team_root=Path(a.team_root).expanduser() if a.team_root else None)
            dump(result); raise SystemExit(0 if result["ok"] else 1)
        elif a.cmd == "agent-entry": dump(setup_agent_entry(root, apply=a.apply, entry_file=a.entry_file))
        elif a.cmd == "eval":
            result = evaluate(root, k=a.k); dump(result); raise SystemExit(0 if not result["failures"] else 1)
        elif a.cmd == "govern":
            result = govern_documents(root, paths=a.docs, apply=a.apply)
            dump(result); raise SystemExit(0 if result["ok"] else 1)
        elif a.cmd == "project-rules":
            result = project_rules(root, Path(a.team_root).resolve() if a.team_root else None, phase=a.phase)
            dump(result); raise SystemExit(0 if result["ok"] else 1)
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
        elif a.cmd == "project-work":
            used_for = dict(str(x).partition("=")[::2] for x in a.used_for)
            evidence_by_knowledge: dict[str, list[str]] = {}
            for item in a.evidence:
                key, _, value = str(item).partition(":")
                if not key or not value:
                    raise ValueError(f"--evidence expects K-ID:EVIDENCE_ID, got: {item}")
                evidence_by_knowledge.setdefault(key, []).append(value)
            observations = []
            for item in a.observe:
                parts = str(item).split(":", 2)
                if len(parts) < 2 or not parts[0] or not parts[1]:
                    raise ValueError(f"--observe expects K-ID:OUTCOME[:NOTE], got: {item}")
                knowledge_id = parts[0]
                observations.append({
                    "knowledge_id": knowledge_id,
                    "outcome": parts[1],
                    "note": parts[2] if len(parts) > 2 else used_for.get(knowledge_id, ""),
                    "used_for": used_for.get(knowledge_id, ""),
                    "evidence_ids": evidence_by_knowledge.get(knowledge_id, []),
                })
            dump(run_project_work(
                root, Path(a.team_root).resolve(), phase=a.phase,
                goal=a.goal, work_id=a.work_id_arg,
                read_knowledge=a.read, adopt=a.adopt, observations=observations,
            ))
        elif a.cmd == "connector-add-git":
            print(create_git_connector(root, a.connector_id, repository_id=a.repository_id, include_paths=a.include or ["."], logical_root=a.logical_root, auto_intake=a.auto_intake))
        elif a.cmd == "connector-status": dump(connector_status(root, a.connector_id))
        elif a.cmd == "connector-sync": dump(sync_git_connector(root, a.connector_id, Path(a.repo_path).resolve(), owner=a.owner))
        elif a.cmd == "index":
            index_workspace(root)
            project = read_yaml(root / ".knowledge/config.yml").get("profile") == "project"
            print("项目文档检查完成；检索直接读取文件，导航维护请使用 govern。" if project else "Markdown 导航已更新。")
        elif a.cmd == "change": print(create_change(root, a.title, a.owner)); index_workspace(root)
        elif a.cmd == "prepare": print(prepare_work(root, a.goal, consumer_id=a.consumer))
        elif a.cmd == "search" and a.connected:
            dump(connected_query(root, a.query, statuses=a.status, scope=a.scope, limit=a.limit if a.limit is not None else 5))
        elif a.cmd == "search":
            results, issues = search_report(root, a.query, statuses=a.status, scope=a.scope, limit=a.limit)
            dump(results)
            for issue in issues:
                print(f"warning: {issue['path']}: {issue['message']}", file=sys.stderr)
        elif a.cmd == "related": dump(related(root, a.knowledge_id, a.limit))
        elif a.cmd == "context" and a.connected:
            dump(connected_query(root, a.query, context=True, statuses=a.status, scope=a.scope, limit=a.limit))
        elif a.cmd == "context": dump(context_plan(root, a.query, a.max_context, a.limit, statuses=a.status, scope=a.scope))
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
    except (KeyError, ValueError, OSError, yaml.YAMLError, SourceScopeError) as exc:
        p.error(str(exc))


if __name__ == "__main__":
    main()
