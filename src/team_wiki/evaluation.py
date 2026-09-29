"""Measure retrieval quality against real questions kept in the repository.

`.knowledge/eval.yml` is a tracked list. Each case names the query and either
the documents that must be found (`expect`, IDs or repo-relative paths) or
`expect_none: true` when no document should be returned.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import core
from .retrieval import search_knowledge_report

EVAL_FILE = ".knowledge/eval.yml"


def _load_cases(root: Path) -> list[dict[str, Any]]:
    path = root / EVAL_FILE
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{EVAL_FILE} not found")
    data = core.read_yaml(path)
    cases = data.get("cases") if isinstance(data, dict) else None
    if not isinstance(cases, list) or not cases:
        raise ValueError(f"{EVAL_FILE} must contain a non-empty 'cases' list")
    for index, case in enumerate(cases, 1):
        if not isinstance(case, dict) or not isinstance(case.get("query"), str) or not case["query"].strip():
            raise ValueError(f"{EVAL_FILE} case {index}: query is required")
        expect = case.get("expect") or []
        if isinstance(expect, str):
            expect = [expect]
        if bool(case.get("expect_none")) == bool(expect):
            raise ValueError(f"{EVAL_FILE} case {index}: set either expect or expect_none")
        case["expect"] = [str(x) for x in expect]
    return cases


def evaluate(root: Path, *, k: int = 5) -> dict[str, Any]:
    if k < 1:
        raise ValueError("k must be positive")
    root = root.resolve()
    rows = []
    for case in _load_cases(root):
        results, _ = search_knowledge_report(
            root, case["query"], statuses=case.get("status"), scope=case.get("scope"), limit=k)
        keys = [{row["id"], row["path"]} for row in results]
        if case.get("expect_none"):
            rows.append({"query": case["query"], "ok": not results, "rank": None,
                         "returned": [row["path"] for row in results]})
            continue
        ranks = [next((i for i, key in enumerate(keys, 1) if target in key), None)
                 for target in case["expect"]]
        found = [r for r in ranks if r is not None]
        rows.append({"query": case["query"], "ok": len(found) == len(ranks),
                     "rank": min(found) if found else None,
                     "missing": [t for t, r in zip(case["expect"], ranks) if r is None],
                     "returned": [row["path"] for row in results]})
    positive = [r for r in rows if "missing" in r]
    negative = [r for r in rows if "missing" not in r]
    return {
        "k": k,
        "cases": len(rows),
        "recall_at_k": round(sum(r["ok"] for r in positive) / len(positive), 3) if positive else None,
        "mrr": round(sum(1 / r["rank"] for r in positive if r["rank"]) / len(positive), 3) if positive else None,
        "negative_pass": f"{sum(r['ok'] for r in negative)}/{len(negative)}",
        "failures": [r for r in rows if not r["ok"]],
    }
