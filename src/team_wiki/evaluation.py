"""Reproducible query evaluation; unreadable corpora cannot produce clean passes.

recall_at_k is macro document recall, all_expected_at_k is query success, MRR
uses the first relevant result. Unhealthy cases are invalid, excluded from
metrics and included in failures, so a CLI check still fails visibly.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from . import core
from .retrieval import search_knowledge_report

EVAL_FILE = ".knowledge/eval.yml"


def _load_cases(root: Path) -> list[dict[str, Any]]:
    path = root / EVAL_FILE
    if (root / ".knowledge").is_symlink() or path.is_symlink() or not path.is_file():
        raise ValueError(f"{EVAL_FILE} not found or unsafe")
    data = core.read_yaml(path)
    cases = data.get("cases") if isinstance(data, dict) else None
    if not isinstance(cases, list) or not cases:
        raise ValueError(f"{EVAL_FILE} must contain a non-empty 'cases' list")
    for index, case in enumerate(cases, 1):
        if not isinstance(case, dict) or not isinstance(case.get("query"), str) or not case["query"].strip():
            raise ValueError(f"{EVAL_FILE} case {index}: query is required")
        expect = case.get("expect", [])
        if isinstance(expect, str):
            expect = [expect]
        if not isinstance(expect, list) or any(not isinstance(x, str) or not x.strip() for x in expect):
            raise ValueError(f"{EVAL_FILE} case {index}: expect must contain non-empty IDs or paths")
        if not isinstance(case.get("expect_none", False), bool):
            raise ValueError(f"{EVAL_FILE} case {index}: expect_none must be boolean")
        if bool(case.get("expect_none")) == bool(expect):
            raise ValueError(f"{EVAL_FILE} case {index}: set either expect or expect_none")
        case["expect"] = list(dict.fromkeys(expect))
    return cases


def evaluate(root: Path, *, k: int = 5) -> dict[str, Any]:
    if isinstance(k, bool) or not isinstance(k, int) or k < 1:
        raise ValueError("k must be positive")
    root = root.resolve()
    rows = []
    health_issues = []
    for case in _load_cases(root):
        try:
            results, issues = search_knowledge_report(
                root, case["query"], statuses=case.get("status"), scope=case.get("scope"), limit=k)
        except (ValueError, OSError, yaml.YAMLError) as exc:
            results, issues = [], [{"path": ".", "kind": "unavailable", "message": str(exc)}]
        if issues:
            health_issues.append({"query": case["query"], "issues": issues})
        keys = [{row["id"], row["path"]} for row in results]
        row = {"query": case["query"], "valid": not issues,
               "returned": [item["path"] for item in results]}
        if case.get("expect_none"):
            row.update(ok=not results and not issues, rank=None)
        else:
            ranks = [next((i for i, key in enumerate(keys, 1) if target in key), None)
                     for target in case["expect"]]
            found = [r for r in ranks if r is not None]
            row.update(ok=len(found) == len(ranks) and not issues,
                       recall=len(found) / len(ranks), rank=min(found) if found else None,
                       missing=[t for t, r in zip(case["expect"], ranks) if r is None])
        if issues:
            row["issues"] = issues
        rows.append(row)
    positive = [r for r in rows if "missing" in r and r["valid"]]
    negative = [r for r in rows if "missing" not in r and r["valid"]]
    invalid = sum(not r["valid"] for r in rows)
    failures = [r for r in rows if not r["ok"]]
    return {
        "k": k, "cases": len(rows), "valid_cases": len(rows) - invalid,
        "invalid_cases": invalid, "ok": not failures,
        "recall_at_k": round(sum(r["recall"] for r in positive) / len(positive), 3) if positive else None,
        "all_expected_at_k": round(sum(r["ok"] for r in positive) / len(positive), 3) if positive else None,
        "mrr": round(sum(1 / r["rank"] for r in positive if r["rank"]) / len(positive), 3) if positive else None,
        "negative_pass": f"{sum(r['ok'] for r in negative)}/{len(negative)}",
        "health_issues": health_issues, "failures": failures,
    }
