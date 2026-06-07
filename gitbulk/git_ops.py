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


INTERACTIVE_COMMANDS = {
    "vim", "vi", "nvim", "nano", "emacs", "ed", "ex",
    "less", "more", "most", "pg",
    "top", "htop", "btop", "iotop", "iftop", "nload",
    "man", "info", "watch",
    "ssh", "sftp", "telnet", "ncftp", "lftp",
    "gdb", "lldb",
    "screen", "tmux", "byobu",
    "sudo", "su",
}

INTERACTIVE_MULTIWORD = [
    ("tail", "-f"),
    ("tail", "-F"),
    ("tailf",),
]

SHELL_COMMANDS = {"sh", "bash", "zsh", "ksh", "dash", "fish"}


def _split_tokens(command: str) -> list[str]:
    tokens = []
    current = []
    quote = None
    i = 0
    while i < len(command):
        ch = command[i]
        if quote:
            if ch == "\\" and i + 1 < len(command):
                current.append(command[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
                i += 1
                continue
            current.append(ch)
            i += 1
        else:
            if ch in ('"', "'"):
                quote = ch
                i += 1
                continue
            if ch.isspace():
                if current:
                    tokens.append("".join(current))
                    current = []
                i += 1
                continue
            current.append(ch)
            i += 1
    if current:
        tokens.append("".join(current))
    return tokens


def _extract_shell_c_arg(tokens: list[str]) -> str | None:
    if not tokens or tokens[0] not in SHELL_COMMANDS:
        return None
    for i, token in enumerate(tokens[1:], start=1):
        if token == "-c":
            if i + 1 < len(tokens):
                return tokens[i + 1]
            return None
        if token.startswith("-c"):
            rest = token[2:]
            if rest:
                return rest
            if i + 1 < len(tokens):
                return tokens[i + 1]
            return None
    return None


def _extract_sudo_command(tokens: list[str]) -> list[str] | None:
    if not tokens or tokens[0] != "sudo":
        return None
    i = 1
    while i < len(tokens):
        token = tokens[i]
        if token.startswith("-"):
            if token in ("-u", "--user", "-g", "--group", "-U", "--other-user"):
                i += 2
            else:
                i += 1
        else:
            return tokens[i:]
    return None


def _is_interactive_simple(tokens: list[str]) -> bool:
    if not tokens:
        return False
    base = tokens[0]
    if base in INTERACTIVE_COMMANDS:
        return True
    for multiword in INTERACTIVE_MULTIWORD:
        if len(tokens) >= len(multiword):
            match = True
            for i, word in enumerate(multiword):
                if tokens[i] != word:
                    match = False
                    break
            if match:
                return True
    return False


def _is_interactive_command(command: str) -> bool:
    cmd_lower = command.strip().lower()
    if not cmd_lower:
        return False

    segments = []
    current_seg = []
    quote = None
    i = 0
    while i < len(cmd_lower):
        ch = cmd_lower[i]
        if quote:
            current_seg.append(ch)
            if ch == "\\" and i + 1 < len(cmd_lower):
                current_seg.append(cmd_lower[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
        else:
            if ch in ('"', "'"):
                quote = ch
                current_seg.append(ch)
                i += 1
                continue

            if cmd_lower[i:i + 2] == "||":
                if current_seg:
                    segments.append(("or", "".join(current_seg).strip()))
                    current_seg = []
                i += 2
                continue

            if cmd_lower[i:i + 2] == "&&":
                if current_seg:
                    segments.append(("and", "".join(current_seg).strip()))
                    current_seg = []
                i += 2
                continue

            if ch == "|":
                if current_seg:
                    segments.append(("pipe", "".join(current_seg).strip()))
                    current_seg = []
                i += 1
                continue

            if ch == ";":
                if current_seg:
                    segments.append(("semicolon", "".join(current_seg).strip()))
                    current_seg = []
                i += 1
                continue

            if ch == "&":
                if current_seg:
                    segments.append(("amp", "".join(current_seg).strip()))
                    current_seg = []
                i += 1
                continue

            current_seg.append(ch)
            i += 1

    if current_seg:
        segments.append(("last", "".join(current_seg).strip()))

    for _, seg_text in segments:
        if _is_interactive_segment(seg_text):
            return True

    return False


def _is_interactive_segment(segment: str) -> bool:
    if not segment:
        return False
    tokens = _split_tokens(segment)
    if not tokens:
        return False

    if _is_interactive_simple(tokens):
        return True

    shell_inner = _extract_shell_c_arg(tokens)
    if shell_inner is not None:
        if _is_interactive_command(shell_inner):
            return True

    sudo_cmd = _extract_sudo_command(tokens)
    if sudo_cmd is not None:
        if _is_interactive_simple(sudo_cmd):
            return True
        shell_inner = _extract_shell_c_arg(sudo_cmd)
        if shell_inner is not None:
            if _is_interactive_command(shell_inner):
                return True

    return False


def exec_command(
    repo_path: str,
    command: str,
    timeout: int = 300,
    allow_interactive: bool = False,
    dry_run: bool = False,
) -> OperationResult:
    if dry_run:
        return OperationResult(
            path=repo_path,
            ok=True,
            exit_code=0,
            stdout=f"[dry-run] Would execute: {command}",
            meta={"action": "exec", "command": command, "allow_interactive": allow_interactive},
        )

    if not allow_interactive and _is_interactive_command(command):
        return OperationResult(
            path=repo_path,
            ok=False,
            exit_code=126,
            stderr="Interactive command blocked. Use --allow-interactive to override.",
            meta={"action": "exec", "command": command, "blocked": True},
        )

    try:
        stdin = subprocess.DEVNULL if not allow_interactive else None
        result = subprocess.run(
            command,
            shell=True,
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=stdin,
        )
        return OperationResult(
            path=repo_path,
            ok=result.returncode == 0,
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            meta={"action": "exec", "command": command, "allow_interactive": allow_interactive},
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


def sync_fork(
    repo_path: str,
    upstream_remote: str = "upstream",
    use_rebase: bool = False,
    branch: Optional[str] = None,
    dry_run: bool = False,
) -> OperationResult:
    if dry_run:
        action = "rebase" if use_rebase else "merge"
        return OperationResult(
            path=repo_path,
            ok=True,
            exit_code=0,
            stdout=f"[dry-run] Would fetch {upstream_remote} and {action} into current branch",
            meta={
                "action": "sync-fork",
                "upstream_remote": upstream_remote,
                "use_rebase": use_rebase,
            },
        )

    try:
        repo = Repo(repo_path)
    except InvalidGitRepositoryError:
        return OperationResult(
            path=repo_path,
            ok=False,
            exit_code=1,
            stderr="Not a git repository",
            meta={"action": "sync-fork"},
        )

    try:
        remote_names = [r.name for r in repo.remotes]
        if upstream_remote not in remote_names:
            return OperationResult(
                path=repo_path,
                ok=False,
                exit_code=1,
                stderr=(
                    f"Upstream remote '{upstream_remote}' not found. "
                    f"Available remotes: {', '.join(remote_names) if remote_names else '(none)'}. "
                    f"Add it with: git remote add {upstream_remote} <upstream-url>"
                ),
                meta={
                    "action": "sync-fork",
                    "upstream_remote": upstream_remote,
                    "available_remotes": remote_names,
                },
            )

        if repo.is_dirty(untracked_files=True):
            return OperationResult(
                path=repo_path,
                ok=False,
                exit_code=1,
                stderr="Working tree is dirty. Commit or stash changes before syncing.",
                meta={"action": "sync-fork", "dirty": True},
            )

        current_branch = None
        if not repo.head.is_detached:
            current_branch = repo.active_branch.name
        if branch and current_branch and branch != current_branch:
            return OperationResult(
                path=repo_path,
                ok=False,
                exit_code=1,
                stderr=(
                    f"Current branch is '{current_branch}', "
                    f"but sync target branch is '{branch}'. "
                    f"Checkout the target branch first."
                ),
                meta={
                    "action": "sync-fork",
                    "current_branch": current_branch,
                    "target_branch": branch,
                },
            )

        fetch_info = repo.remotes[upstream_remote].fetch()
        fetch_summary = f"Fetched {len(fetch_info)} refs from {upstream_remote}"

        if repo.head.is_detached:
            return OperationResult(
                path=repo_path,
                ok=False,
                exit_code=1,
                stderr="HEAD is detached. Check out a branch to sync.",
                meta={"action": "sync-fork", "detached": True},
            )

        upstream_branch = f"{upstream_remote}/{current_branch}"
        try:
            repo.git.rev_parse("--verify", upstream_branch)
        except GitCommandError:
            return OperationResult(
                path=repo_path,
                ok=False,
                exit_code=1,
                stderr=(
                    f"Upstream branch '{upstream_branch}' not found. "
                    f"The remote may not have a branch with this name."
                ),
                meta={
                    "action": "sync-fork",
                    "upstream_branch": upstream_branch,
                },
            )

        stdout_lines = [fetch_summary]

        if use_rebase:
            try:
                result = repo.git.rebase(upstream_branch)
                stdout_lines.append(f"Rebased onto {upstream_branch}")
                if result.strip():
                    stdout_lines.append(result.strip())
            except GitCommandError as e:
                return OperationResult(
                    path=repo_path,
                    ok=False,
                    exit_code=e.status if hasattr(e, "status") else 1,
                    stderr=str(e.stderr) if hasattr(e, "stderr") else str(e),
                    stdout=str(e.stdout) if hasattr(e, "stdout") else "",
                    meta={"action": "sync-fork", "method": "rebase", "upstream_branch": upstream_branch},
                )
        else:
            try:
                result = repo.git.merge(upstream_branch)
                stdout_lines.append(f"Merged {upstream_branch} into {current_branch}")
                if result.strip():
                    stdout_lines.append(result.strip())
            except GitCommandError as e:
                return OperationResult(
                    path=repo_path,
                    ok=False,
                    exit_code=e.status if hasattr(e, "status") else 1,
                    stderr=str(e.stderr) if hasattr(e, "stderr") else str(e),
                    stdout=str(e.stdout) if hasattr(e, "stdout") else "",
                    meta={"action": "sync-fork", "method": "merge", "upstream_branch": upstream_branch},
                )

        return OperationResult(
            path=repo_path,
            ok=True,
            exit_code=0,
            stdout="\n".join(stdout_lines),
            meta={
                "action": "sync-fork",
                "method": "rebase" if use_rebase else "merge",
                "upstream_remote": upstream_remote,
                "upstream_branch": upstream_branch,
            },
        )
    except GitCommandError as e:
        return OperationResult(
            path=repo_path,
            ok=False,
            exit_code=e.status if hasattr(e, "status") else 1,
            stderr=str(e.stderr) if hasattr(e, "stderr") else str(e),
            stdout=str(e.stdout) if hasattr(e, "stdout") else "",
            meta={"action": "sync-fork"},
        )
    except Exception as e:
        return OperationResult(
            path=repo_path,
            ok=False,
            exit_code=1,
            stderr=str(e),
            meta={"action": "sync-fork", "error_type": type(e).__name__},
        )


def is_dirty(repo_path: str) -> bool:
    try:
        repo = Repo(repo_path)
        return repo.is_dirty(untracked_files=True)
    except InvalidGitRepositoryError:
        return False
