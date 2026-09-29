#!/usr/bin/env python3
"""Compare direct file search with the previous scan-and-score baseline.

The script creates one synthetic corpus per requested size below
``.tmp/retrieval-benchmark`` and removes only each run's temporary directory.
It checks exact result equality before and after one file changes. Timings are
local measurements, not a claim about semantic accuracy or universal speedup.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from team_wiki import core
from team_wiki.retrieval import search_knowledge


QUERY = "蓝鲸支付回调幂等策略"


def legacy_scan(root: Path, query: str) -> list[dict[str, object]]:
    """V0.8-style per-document parse and field-weighted scoring baseline."""
    terms = core.tokenize_query(query)
    if not terms:
        return []
    results: list[dict[str, object]] = []
    for path in core.iter_knowledge_files(root):
        meta, body = core.parse_frontmatter(path)
        fields = {key: value.lower() for key, value in core._knowledge_fields(meta, body).items()}
        score = 0
        for term in terms:
            weight = core.FIELD_WEIGHTS["body"]
            if term in fields["title"]:
                weight = core.FIELD_WEIGHTS["title"]
            elif term in fields["tags"]:
                weight = core.FIELD_WEIGHTS["tags"]
            elif term in fields["summary"]:
                weight = core.FIELD_WEIGHTS["summary"]
            hits = sum(fields[key].count(term) for key in fields)
            if hits:
                score += hits * weight * len(term)
        if score:
            results.append(
                {
                    "score": score,
                    "id": meta.get("id"),
                    "title": meta.get("title") or path.stem,
                    "status": meta.get("status", "unclassified"),
                    "path": str(path.relative_to(root)),
                }
            )
    return sorted(results, key=lambda row: (-row["score"], row["path"]))


def build_corpus(root: Path, document_count: int) -> Path:
    target: Path | None = None
    for index in range(document_count):
        path = root / "wiki" / "samples" / f"group-{index % 17:02d}" / f"item-{index:05d}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        if index == document_count // 2:
            title = "蓝鲸支付回调幂等策略"
            body = "支付平台重复发送支付回调时，使用幂等键避免重复入账。"
            target = path
        else:
            title = f"普通样本文档 {index}"
            body = f"样本编号 {index} 的隔离维护说明。"
        path.write_text(
            f"---\nid: BENCH-{index:05d}\ntitle: {title}\nstatus: active\n"
            f"summary: 合成基准资料\ntags: [样本, 基准]\n---\n\n{body}\n",
            encoding="utf-8",
        )
    assert target is not None
    return target


def measure(call, repeat: int) -> tuple[float, list[dict[str, object]]]:
    durations: list[float] = []
    result: list[dict[str, object]] = []
    for _ in range(repeat):
        started = time.perf_counter()
        result = call()
        durations.append((time.perf_counter() - started) * 1000)
    return statistics.median(durations), result


def run_size(base: Path, document_count: int, repeat: int) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix=f"{document_count}-", dir=base) as temp_dir:
        root = Path(temp_dir) / "knowledge"
        target = build_corpus(root, document_count)

        legacy_ms, baseline = measure(lambda: legacy_scan(root, QUERY), repeat)
        file_search_ms, current = measure(lambda: search_knowledge(root, QUERY), repeat)
        if current != baseline:
            raise AssertionError(f"file search differs from scan baseline at {document_count} documents")

        content = target.read_text(encoding="utf-8")
        target.write_text(content.replace("避免重复入账。", "避免重复入账，并记录核对时间。"), encoding="utf-8")
        file_after_change_ms, current_after_change = measure(
            lambda: search_knowledge(root, QUERY), repeat
        )
        legacy_after_change_ms, baseline_after_change = measure(
            lambda: legacy_scan(root, QUERY), repeat
        )
        if current_after_change != baseline_after_change:
            raise AssertionError(f"updated file search differs from scan baseline at {document_count} documents")

        return {
            "documents": document_count,
            "query": QUERY,
            "result_count": len(current),
            "repeat": repeat,
            "file_search_median_ms": round(file_search_ms, 3),
            "legacy_scan_median_ms": round(legacy_ms, 3),
            "file_search_after_one_file_change_median_ms": round(file_after_change_ms, 3),
            "legacy_scan_after_change_median_ms": round(legacy_after_change_ms, 3),
            "results_equal_before_change": True,
            "results_equal_after_change": True,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--counts", nargs="+", type=int, default=[100, 1000])
    parser.add_argument("--repeat", type=int, default=3)
    args = parser.parse_args()
    if any(value <= 0 for value in args.counts):
        parser.error("--counts must be positive")
    if args.repeat <= 0:
        parser.error("--repeat must be positive")

    temp_root = REPOSITORY_ROOT / ".tmp" / "retrieval-benchmark"
    temp_root.mkdir(parents=True, exist_ok=True)
    output = {
        "method": "direct file search versus scan-and-score baseline",
        "note": "Synthetic equality and local latency measurements; not a semantic accuracy claim or universal speed guarantee.",
        "runs": [run_size(temp_root, count, args.repeat) for count in args.counts],
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
