import argparse
import json
from pathlib import Path

from .core import create_change, doctor, index_workspace, init_team, prepare_work, register_source, search


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

    a = p.parse_args(); root = Path(a.root).resolve()
    if a.cmd == "init": init_team(root, a.repository_id); index_workspace(root); print(root)
    elif a.cmd == "doctor":
        r = doctor(root); print(json.dumps({"ok": r.ok, "errors": r.errors, "warnings": r.warnings}, ensure_ascii=False, indent=2)); raise SystemExit(0 if r.ok else 1)
    elif a.cmd == "ingest": print(register_source(root, Path(a.file).resolve(), a.title, a.move)); index_workspace(root)
    elif a.cmd == "index": index_workspace(root); print("indexed")
    elif a.cmd == "change": print(create_change(root, a.title, a.owner)); index_workspace(root)
    elif a.cmd == "prepare": print(prepare_work(root, a.goal))
    elif a.cmd == "search": print(json.dumps(search(root, a.query), ensure_ascii=False, indent=2))

if __name__ == "__main__": main()
