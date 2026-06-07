from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class RepoConfig:
    path: str
    branch: str = "main"
    remote: str = "origin"
    groups: list[str] = field(default_factory=list)


@dataclass
class Manifest:
    repos: list[RepoConfig]
    groups: dict[str, list[str]] = field(default_factory=dict)
    defaults: dict[str, Any] = field(default_factory=dict)

    def get_repo(self, path: str) -> Optional[RepoConfig]:
        for repo in self.repos:
            if repo.path == path:
                return repo
        return None

    def filter_by_group(self, group_name: str) -> list[RepoConfig]:
        if group_name not in self.groups:
            return []
        group_paths = set(self.groups[group_name])
        return [r for r in self.repos if r.path in group_paths]


@dataclass
class RepoStatus:
    path: str
    branch: str
    dirty: bool
    ahead: int
    behind: int
    last_commit_age: str
    error: Optional[str] = None


@dataclass
class OperationResult:
    path: str
    ok: bool
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    meta: dict[str, Any] = field(default_factory=dict)
    skipped: bool = False
    skip_reason: Optional[str] = None

    @property
    def stdout_tail(self, n: int = 5) -> str:
        lines = [l for l in self.stdout.splitlines() if l.strip()]
        return "\n".join(lines[-n:]) if lines else ""

    @property
    def stderr_tail(self, n: int = 5) -> str:
        lines = [l for l in self.stderr.splitlines() if l.strip()]
        return "\n".join(lines[-n:]) if lines else ""


@dataclass
class Report:
    command: str
    started_at: datetime
    finished_at: datetime
    results: list[OperationResult]

    @property
    def success_count(self) -> int:
        return sum(1 for r in self.results if r.ok and not r.skipped)

    @property
    def fail_count(self) -> int:
        return sum(1 for r in self.results if not r.ok and not r.skipped)

    @property
    def skip_count(self) -> int:
        return sum(1 for r in self.results if r.skipped)

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "startedAt": self.started_at.isoformat(),
            "finishedAt": self.finished_at.isoformat(),
            "summary": {
                "success": self.success_count,
                "fail": self.fail_count,
                "skipped": self.skip_count,
                "total": len(self.results),
            },
            "results": [
                {
                    "path": r.path,
                    "ok": r.ok,
                    "exitCode": r.exit_code,
                    "stdoutTail": r.stdout_tail,
                    "stderrTail": r.stderr_tail,
                    "meta": r.meta if r.meta else None,
                    "skipped": r.skipped,
                    "skipReason": r.skip_reason,
                }
                for r in self.results
            ],
        }
