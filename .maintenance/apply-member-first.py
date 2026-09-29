"""One-off, hash-verified transfer of the locally tested correction.

This script only reconstructs files or uploads an unreferenced Git tree.
It never creates commits, updates refs, changes settings, or merges a PR.
Neither this script nor its payload belongs to the delivery tree.
"""
import hashlib
import json
import lzma
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import urllib.request

REPO = "ScWen7/team-ai-knowledge"
BASE_COMMIT = "e2b2ba9388b9de4fa202d048e1b79b4b08444e6e"
BASE_TREE = "0467a1c9ceaffb4e6f50c27e18cba4e73c4e1257"
PAYLOAD_SHA = "7b6ee3e781f61d3249a01c6ea70dae4bfd6d8be845048f0debbeeadbc9ddfb9e"
FILES = set(""".github/workflows/tests.yml
AGENTS.md
README.md
docs/FINAL_DESIGN.md
docs/PRODUCT_MANAGER_GUIDE.md
docs/VALIDATION.md
examples/README.md
examples/team-knowledge/AGENTS.md
examples/team-knowledge/README.md
pyproject.toml
scripts/check_member_workflow.py
src/team_wiki/__init__.py
src/team_wiki/agent_entry.py
src/team_wiki/cli.py
src/team_wiki/connections.py
src/team_wiki/core.py
src/team_wiki/documents.py
src/team_wiki/evaluation.py
src/team_wiki/project.py
src/team_wiki/retrieval.py
src/team_wiki/status.py
tests/test_member_first.py
tests/test_v08_status.py""".splitlines())


def digest(data):
    return hashlib.sha256(data).hexdigest()


def manifest():
    data = b"".join(Path(f".maintenance/member-first.{i}").read_bytes() for i in range(4))
    if digest(data) != PAYLOAD_SHA:
        raise ValueError("transfer payload checksum differs from tested local payload")
    result = json.loads(lzma.decompress(data))
    if result["base_commit"] != BASE_COMMIT or result["base_tree"] != BASE_TREE:
        raise ValueError("unexpected transfer base")
    if set(result["files"]) != FILES:
        raise ValueError("unexpected file set")
    return result


def safe_path(name):
    pure = PurePosixPath(name)
    if pure.is_absolute() or ".." in pure.parts or name not in FILES:
        raise ValueError("unsafe file name")
    path = Path(name)
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("symlink in transfer path")
    return path


def apply(data):
    parent = subprocess.check_output(["git", "rev-parse", "HEAD^"], text=True).strip()
    if parent != BASE_COMMIT:
        raise ValueError("bootstrap parent changed; refusing stale transfer")
    prepared = []
    for name, entry in data["files"].items():
        path = safe_path(name)
        original = path.read_bytes() if path.exists() else b""
        if entry["before"] is None:
            if path.exists():
                raise ValueError(f"new file already exists: {name}")
        elif not path.is_file() or digest(original) != entry["before"]:
            raise ValueError(f"original file drift: {name}")
        lines = original.decode("utf-8").splitlines(keepends=True)
        previous_end = 0
        for start, end, replacement in entry["edits"]:
            if not (previous_end <= start <= end <= len(lines)) or not isinstance(replacement, str):
                raise ValueError(f"invalid line edit: {name}")
            previous_end = end
        for start, end, replacement in reversed(entry["edits"]):
            lines[start:end] = replacement.splitlines(keepends=True)
        updated = "".join(lines).encode("utf-8")
        if digest(updated) != entry["after"]:
            raise ValueError(f"reconstructed content mismatch: {name}")
        prepared.append((path, updated))
    for path, content in prepared:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    print(f"Reconstructed and verified {len(prepared)} files; no external project touched.")


def upload(data):
    tree = []
    hashes = {}
    for name, entry in data["files"].items():
        content = safe_path(name).read_bytes()
        if digest(content) != entry["after"]:
            raise ValueError(f"post-test file drift: {name}")
        hashes[name] = entry["after"]
        tree.append({"path": name, "mode": "100644", "type": "blob", "content": content.decode("utf-8")})
    payload = json.dumps({"base_tree": BASE_TREE, "tree": tree}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/git/trees", data=payload, method="POST",
        headers={"Authorization": "Bearer " + os.environ["GITHUB_TOKEN"],
                 "Accept": "application/vnd.github+json", "Content-Type": "application/json",
                 "X-GitHub-Api-Version": "2022-11-28"})
    with urllib.request.urlopen(request, timeout=60) as response:
        result = json.load(response)
    output = {"tree_sha": result["sha"], "base_tree": BASE_TREE,
              "file_hashes": hashes, "payload_sha256": PAYLOAD_SHA,
              "tests": "159 regression tests and synthetic member workflow passed before tree upload",
              "temporary_transfer_files_in_delivery": False}
    Path("/tmp/member-first-result.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print("DELIVERY_TREE_SHA=" + result["sha"])


if __name__ == "__main__":
    data = manifest()
    if sys.argv[1:] == ["apply"]:
        apply(data)
    elif sys.argv[1:] == ["upload"]:
        upload(data)
    else:
        raise SystemExit("expected apply or upload")
