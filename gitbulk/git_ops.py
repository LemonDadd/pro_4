from __future__ import annotations

import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from git import GitCommandError, InvalidGitRepositoryError, Repo

from .models import OperationResult, RepoStatus


def _format_age(commit_datetime: datetime) -> str:
    if commit_datetime.tzinfo is not None:
        now = datetime.now(commit_datetime.tzinfo)
    else:
        now = datetime.now()
    delta = now - commit_datetime
    if delta.days > 365:
        return f"{delta.days // 365}y ago"
    if delta.days > 30:
        return f"{delta.days // 30}mo ago"
    if delta.days > 0:
        return f"{delta.days}d ago"
    if delta.seconds > 3600:
        return f"{delta.seconds // 3600}h ago"
    if delta.seconds > 60:
        return f"{delta.seconds // 60}m ago"
    return f"{delta.seconds}s ago"


def get_repo(repo_path: str) -> Repo:
    return Repo(repo_path)


def is_git_repo(repo_path: str) -> bool:
    try:
        Repo(repo_path)
        return True
    except InvalidGitRepositoryError:
        return False


def get_status(repo_path: str, fetch: bool = False) -> RepoStatus:
    try:
        repo = Repo(repo_path)
    except InvalidGitRepositoryError:
        return RepoStatus(
            path=repo_path,
            branch="N/A",
            dirty=False,
            ahead=0,
            behind=0,
            last_commit_age="N/A",
            error="Not a git repository",
        )

    try:
        if fetch:
            for remote in repo.remotes:
                try:
                    remote.fetch()
                except GitCommandError:
                    pass

        branch = repo.active_branch.name if not repo.head.is_detached else "HEAD (detached)"
        dirty = repo.is_dirty(untracked_files=True)

        ahead = 0
        behind = 0
        try:
            tracking = repo.active_branch.tracking_branch()
            if tracking is not None:
                ahead = sum(
                    1 for _ in repo.iter_commits(f"{tracking.name}..{repo.active_branch.name}")
                )
                behind = sum(
                    1 for _ in repo.iter_commits(f"{repo.active_branch.name}..{tracking.name}")
                )
        except (GitCommandError, ValueError):
            pass

        last_commit = repo.head.commit
        last_commit_age = _format_age(last_commit.committed_datetime)

        return RepoStatus(
            path=repo_path,
            branch=branch,
            dirty=dirty,
            ahead=ahead,
            behind=behind,
            last_commit_age=last_commit_age,
        )
    except Exception as e:
        return RepoStatus(
            path=repo_path,
            branch="N/A",
            dirty=False,
            ahead=0,
            behind=0,
            last_commit_age="N/A",
            error=str(e),
        )


def pull_repo(
    repo_path: str,
    rebase: bool = False,
    no_ff_only: bool = False,
    remote: str = "origin",
    branch: Optional[str] = None,
    dry_run: bool = False,
) -> OperationResult:
    if dry_run:
        return OperationResult(
            path=repo_path,
            ok=True,
            exit_code=0,
            stdout="[dry-run] Would pull from remote",
            meta={"action": "pull", "rebase": rebase, "no_ff_only": no_ff_only},
        )

    try:
        repo = Repo(repo_path)
    except InvalidGitRepositoryError:
        return OperationResult(
            path=repo_path,
            ok=False,
            exit_code=1,
            stderr="Not a git repository",
            meta={"action": "pull"},
        )

    try:
        if branch and repo.active_branch.name != branch:
            return OperationResult(
                path=repo_path,
                ok=False,
                exit_code=1,
                stderr=f"Current branch is '{repo.active_branch.name}', expected '{branch}'",
                meta={"action": "pull"},
            )

        kwargs = {}
        if rebase:
            kwargs["rebase"] = True
        if no_ff_only:
            kwargs["ff-only"] = False

        result = repo.git.pull(remote, repo.active_branch.name, **kwargs)
        return OperationResult(
            path=repo_path,
            ok=True,
            exit_code=0,
            stdout=result,
            meta={"action": "pull", "rebase": rebase},
        )
    except GitCommandError as e:
        return OperationResult(
            path=repo_path,
            ok=False,
            exit_code=e.status if hasattr(e, "status") else 1,
            stderr=str(e.stderr) if hasattr(e, "stderr") else str(e),
            stdout=str(e.stdout) if hasattr(e, "stdout") else "",
            meta={"action": "pull"},
        )
    except Exception as e:
        return OperationResult(
            path=repo_path,
            ok=False,
            exit_code=1,
            stderr=str(e),
            meta={"action": "pull"},
        )


def checkout_branch(
    repo_path: str,
    branch: str,
    dry_run: bool = False,
) -> OperationResult:
    if dry_run:
        return OperationResult(
            path=repo_path,
            ok=True,
            exit_code=0,
            stdout=f"[dry-run] Would checkout {branch}",
            meta={"action": "checkout", "branch": branch},
        )

    try:
        repo = Repo(repo_path)
    except InvalidGitRepositoryError:
        return OperationResult(
            path=repo_path,
            ok=False,
            exit_code=1,
            stderr="Not a git repository",
            meta={"action": "checkout"},
        )

    try:
        if repo.active_branch.name == branch:
            return OperationResult(
                path=repo_path,
                ok=True,
                exit_code=0,
                stdout=f"Already on branch '{branch}'",
                meta={"action": "checkout", "branch": branch},
            )

        repo.git.checkout(branch)
        return OperationResult(
            path=repo_path,
            ok=True,
            exit_code=0,
            stdout=f"Switched to branch '{branch}'",
            meta={"action": "checkout", "branch": branch},
        )
    except GitCommandError as e:
        return OperationResult(
            path=repo_path,
            ok=False,
            exit_code=e.status if hasattr(e, "status") else 1,
            stderr=str(e.stderr) if hasattr(e, "stderr") else str(e),
            stdout=str(e.stdout) if hasattr(e, "stdout") else "",
            meta={"action": "checkout", "branch": branch},
        )


def create_tag(
    repo_path: str,
    tag_name: str,
    message: Optional[str] = None,
    push: bool = False,
    remote: str = "origin",
    dry_run: bool = False,
) -> OperationResult:
    if dry_run:
        msg = f"[dry-run] Would create tag {tag_name}"
        if push:
            msg += f" and push to {remote}"
        return OperationResult(
            path=repo_path,
            ok=True,
            exit_code=0,
            stdout=msg,
            meta={"action": "tag", "tag": tag_name, "push": push},
        )

    try:
        repo = Repo(repo_path)
    except InvalidGitRepositoryError:
        return OperationResult(
            path=repo_path,
            ok=False,
            exit_code=1,
            stderr="Not a git repository",
            meta={"action": "tag"},
        )

    try:
        if message:
            repo.git.tag("-a", tag_name, "-m", message)
        else:
            repo.git.tag(tag_name)

        stdout_lines = [f"Created tag '{tag_name}'"]

        if push:
            repo.git.push(remote, tag_name)
            stdout_lines.append(f"Pushed tag '{tag_name}' to {remote}")

        return OperationResult(
            path=repo_path,
            ok=True,
            exit_code=0,
            stdout="\n".join(stdout_lines),
            meta={"action": "tag", "tag": tag_name, "push": push},
        )
    except GitCommandError as e:
        return OperationResult(
            path=repo_path,
            ok=False,
            exit_code=e.status if hasattr(e, "status") else 1,
            stderr=str(e.stderr) if hasattr(e, "stderr") else str(e),
            stdout=str(e.stdout) if hasattr(e, "stdout") else "",
            meta={"action": "tag", "tag": tag_name},
        )


def exec_command(
    repo_path: str,
    command: str,
    timeout: int = 300,
    dry_run: bool = False,
) -> OperationResult:
    if dry_run:
        return OperationResult(
            path=repo_path,
            ok=True,
            exit_code=0,
            stdout=f"[dry-run] Would execute: {command}",
            meta={"action": "exec", "command": command},
        )

    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return OperationResult(
            path=repo_path,
            ok=result.returncode == 0,
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            meta={"action": "exec", "command": command},
        )
    except subprocess.TimeoutExpired as e:
        return OperationResult(
            path=repo_path,
            ok=False,
            exit_code=-1,
            stdout=e.stdout or "",
            stderr=f"Command timed out after {timeout}s\n{e.stderr or ''}",
            meta={"action": "exec", "command": command, "timeout": timeout},
        )
    except Exception as e:
        return OperationResult(
            path=repo_path,
            ok=False,
            exit_code=1,
            stderr=str(e),
            meta={"action": "exec", "command": command},
        )


def is_dirty(repo_path: str) -> bool:
    try:
        repo = Repo(repo_path)
        return repo.is_dirty(untracked_files=True)
    except InvalidGitRepositoryError:
        return False
