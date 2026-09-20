"""Python adapter for pure Node knowledge-core modules."""
from __future__ import annotations
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


class NodeCoreError(RuntimeError):
    pass


def _cli_path() -> Path:
    return Path(__file__).with_name("knowledge_core") / "cli.mjs"


def available() -> bool:
    return shutil.which("node") is not None and _cli_path().exists()


def call(command: str, payload: dict[str, Any]) -> Any:
    if not available():
        raise NodeCoreError("Node.js knowledge-core is unavailable")
    cp = subprocess.run(
        ["node", str(_cli_path()), command],
        input=json.dumps(payload, ensure_ascii=False),
        text=True,
        capture_output=True,
        check=False,
    )
    if cp.returncode:
        raise NodeCoreError(cp.stderr.strip() or f"knowledge-core failed: {cp.returncode}")
    return json.loads(cp.stdout)


def context_budget(max_context_size: int | None) -> dict[str, Any]:
    return call("budget", {"maxContextSize": max_context_size})


def related_nodes(node_id: str, nodes: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    return call("related", {"nodeId": node_id, "nodes": nodes, "limit": limit})
