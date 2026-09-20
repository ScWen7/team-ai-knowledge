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
from .node_core import context_budget
from .scope import SourceScope, SourceScopeError


def dump(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def main():
    p = argparse.ArgumentParser(prog="team-wiki")
    sub = p.add_subparsers(dest="cmd", required=True)

    x = sub.add_parser("init"); x.add_argument("root"); x.add_argument("--repository-id")
    x = sub.add_parser("doctor"); x.add_argument("root")
    x = sub.add_parser("ingest"); x.add_argument("root"); x.add_argument("file"); x.add_argument("--title"); x.add_argument("--move", action="store_true")
    x = sub.add_parser("index"); x.add_argument("root")
    x = sub.add_parser("change"); x.add_argument("root"); x.add_argument("title"); x.add_argument("--owner", default="unassigned")
    x = sub.add_parser("prepare"); x.add_argument("root"); x.add_argument("--goal", required=True)
    x = sub.add_parser("search"); x.add_argument("root"); x.add_argument("query")
    x = sub.add_parser("related"); x.add_argument("root"); x.add_argument("knowledge_id"); x.add_argument("--limit", type=int, default=5)
    x = sub.add_parser("context"); x.add_argument("root"); x.add_argument("query"); x.add_argument("--max-context", type=int); x.add_argument("--limit", type=int, default=5)
    x = sub.add_parser("budget"); x.add_argument("--max-context", type=int)
    x = sub.add_parser("adopt"); x.add_argument("root"); x.add_argument("work_id"); x.add_argument("knowledge_id"); x.add_argument("--used-for", required=True)
    x = sub.add_parser("evidence"); x.add_argument("root"); x.add_argument("work_id"); x.add_argument("--kind", required=True); x.add_argument("--locator", required=True); x.add_argument("--summary", required=True)
    x = sub.add_parser("observe"); x.add_argument("root"); x.add_argument("work_id"); x.add_argument("knowledge_id"); x.add_argument("--outcome", required=True); x.add_argument("--note", required=True); x.add_argument("--evidence", action="append", default=[])
    x = sub.add_parser("finalize"); x.add_argument("root"); x.add_argument("work_id"); x.add_argument("--owner", default="unassigned")
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
        elif a.cmd == "ingest": print(register_source(root, Path(a.file).resolve(), a.title, a.move)); index_workspace(root)
        elif a.cmd == "index": index_workspace(root); print("indexed")
        elif a.cmd == "change": print(create_change(root, a.title, a.owner)); index_workspace(root)
        elif a.cmd == "prepare": print(prepare_work(root, a.goal))
        elif a.cmd == "search": dump(search(root, a.query))
        elif a.cmd == "related": dump(related(root, a.knowledge_id, a.limit))
        elif a.cmd == "context": dump(context_plan(root, a.query, a.max_context, a.limit))
        elif a.cmd == "adopt": dump(adopt_knowledge(root, a.work_id, a.knowledge_id, a.used_for))
        elif a.cmd == "evidence": print(record_evidence(root, a.work_id, a.kind, a.locator, a.summary))
        elif a.cmd == "observe": dump(observe_knowledge(root, a.work_id, a.knowledge_id, a.outcome, a.note, a.evidence))
        elif a.cmd == "finalize": dump(finalize_work(root, a.work_id, a.owner))
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
