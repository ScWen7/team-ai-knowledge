"""Safe repository source access adapted from giodra96/project-wiki.

Upstream inspiration/code structure:
  giodra96/project-wiki@09f24a20... scripts/wiki_scope.py (MIT)

V0.2 keeps only the deterministic source-scope subset needed by team-wiki:
path normalization, .wikiignore matching, safe UTF-8 reads, listing and search.
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
import weakref
from pathlib import Path, PurePosixPath
from typing import Iterable, Iterator


class SourceScopeError(RuntimeError):
    pass


class SourceScope:
    def __init__(self, repository_root: Path, wiki_root: str = ".project-wiki") -> None:
        self.repository_root = Path(os.path.abspath(repository_root))
        self.wiki_root = self.repository_root / wiki_root
        ignore_file = self.wiki_root / ".wikiignore"
        try:
            self.rules = ignore_file.read_bytes()
        except FileNotFoundError:
            self.rules = b""
        self.has_rules = any(
            line.strip() and not line.startswith(b"#") for line in self.rules.splitlines()
        )
        self.cache: dict[str, bool] = {}
        self._matcher: tempfile.TemporaryDirectory | None = None
        self._cleanup: weakref.finalize | None = None

    def close(self) -> None:
        if self._matcher is not None:
            assert self._cleanup is not None
            self._cleanup()
            self._matcher = None

    def __enter__(self) -> "SourceScope":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def normalize(self, path: str | Path) -> str:
        text = str(path)
        directory = text.endswith("/")
        if "\0" in text:
            raise SourceScopeError("source paths cannot contain NUL characters")
        candidate = Path(text)
        if candidate.is_absolute():
            candidate = Path(os.path.abspath(candidate))
            try:
                text = candidate.relative_to(self.repository_root).as_posix()
            except ValueError:
                raise SourceScopeError("source path is outside the repository") from None
        else:
            pure = PurePosixPath(text)
            if ".." in pure.parts:
                raise SourceScopeError("source paths must be relative to the repository root")
            text = pure.as_posix()
        return text.rstrip("/") + ("/" if directory else "")

    def ignored_many(self, paths: Iterable[str | Path]) -> list[bool]:
        normalized = [self.normalize(path) for path in paths]
        missing = list(dict.fromkeys(p for p in normalized if p not in self.cache))
        if missing:
            if not self.has_rules:
                self.cache.update((p, False) for p in missing)
            else:
                self.cache.update(self._match(missing))
        return [self.cache[p] for p in normalized]

    def ignored(self, path: str | Path) -> bool:
        return self.ignored_many([path])[0]

    def _match(self, paths: list[str]) -> dict[str, bool]:
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
        command = [
            "git", "-c", f"core.excludesFile={os.devnull}", "-c", "core.ignoreCase=false"
        ]
        try:
            if self._matcher is None:
                temporary = tempfile.TemporaryDirectory(prefix="team-wiki-scope-")
                root = Path(temporary.name)
                init = subprocess.run(
                    [*command, "init", "--quiet", "--template=", temporary.name],
                    env=env, capture_output=True, check=False,
                )
                if init.returncode:
                    temporary.cleanup()
                    raise SourceScopeError("cannot initialize isolated ignore matcher")
                (root / ".gitignore").write_bytes(self.rules)
                self._matcher = temporary
                self._cleanup = weakref.finalize(self, temporary.cleanup)
            result = subprocess.run(
                [*command, "check-ignore", "--no-index", "--verbose", "--non-matching", "-z", "--stdin"],
                cwd=self._matcher.name,
                env=env,
                input=b"".join(os.fsencode(p) + b"\0" for p in paths),
                capture_output=True,
                check=False,
            )
            if result.returncode not in (0, 1):
                raise SourceScopeError("cannot evaluate .wikiignore")
        except FileNotFoundError as exc:
            raise SourceScopeError("Git is required to evaluate .wikiignore") from exc
        fields = result.stdout.split(b"\0")[:-1]
        if len(fields) != 4 * len(paths):
            raise SourceScopeError("unexpected output from ignore matcher")
        return {
            os.fsdecode(fields[i + 3]): bool(fields[i + 2]) and not fields[i + 2].startswith(b"!")
            for i in range(0, len(fields), 4)
        }

    def source_files(self, start: Path | None = None, *, skip_wiki: bool = True) -> Iterator[Path]:
        start = Path(os.path.abspath(start or self.repository_root))
        try:
            start.relative_to(self.repository_root)
        except ValueError:
            raise SourceScopeError("start path is outside repository") from None
        pending = [start]
        while pending:
            directory = pending.pop()
            with os.scandir(directory) as scanner:
                entries = sorted(scanner, key=lambda e: e.name)
            candidates: list[tuple[Path, bool]] = []
            for entry in entries:
                path = Path(entry.path)
                if entry.name == ".git" or (skip_wiki and path == self.wiki_root):
                    continue
                is_dir = entry.is_dir(follow_symlinks=False)
                candidates.append((path, is_dir))
            ignored = self.ignored_many(
                p.relative_to(self.repository_root).as_posix() + ("/" if is_dir else "")
                for p, is_dir in candidates
            )
            for (path, is_dir), excluded in zip(candidates, ignored):
                if excluded:
                    continue
                if is_dir:
                    pending.append(path)
                else:
                    yield path

    def read_source(self, path: str | Path, *, start_line: int = 1, end_line: int | None = None) -> str | None:
        normalized = self.normalize(path)
        if self.ignored(normalized):
            return None
        candidate = self.repository_root / normalized
        try:
            resolved = candidate.resolve(strict=True)
        except FileNotFoundError:
            return None
        repo_resolved = self.repository_root.resolve()
        if not resolved.is_relative_to(repo_resolved):
            return None
        resolved_name = resolved.relative_to(repo_resolved).as_posix()
        if self.ignored(resolved_name):
            return None
        try:
            content = resolved.read_text(encoding="utf-8")
        except (UnicodeError, OSError):
            return None
        if "\0" in content:
            return None
        return "".join(content.splitlines(keepends=True)[start_line - 1:end_line])

    def search(self, pattern: str, *, limit: int = 100) -> list[dict[str, object]]:
        regex = re.compile(pattern)
        results: list[dict[str, object]] = []
        for path in self.source_files():
            rel = path.relative_to(self.repository_root).as_posix()
            content = self.read_source(rel)
            if content is None:
                continue
            for line_no, line in enumerate(content.splitlines(), 1):
                if regex.search(line):
                    results.append({"path": rel, "line": line_no, "text": line[:500]})
                    if len(results) >= limit:
                        return results
        return results
