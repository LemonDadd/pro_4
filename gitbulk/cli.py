from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from . import __version__
from .config import find_manifest, generate_manifest, load_manifest
from .executor import run_parallel
from .git_ops import (
    checkout_branch,
    create_tag,
    exec_command,
    get_status,
    is_dirty,
    pull_repo,
    sync_fork,
)
from .models import OperationResult
from .report import (
    console,
    print_fail_details,
    print_repo_list,
    print_results_table,
    print_status_table,
    print_summary,
    save_json_report,
)


app = typer.Typer(
    help="Git multi-repository batch operation tool",
    add_completion=False,
    no_args_is_help=True,
)


def _version_callback(value: bool):
    if value:
        console.print(f"gitbulk v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Optional[bool] = typer.Option(
        None, "--version", callback=_version_callback, is_eager=True,
        help="Show version and exit."
    ),
):
    pass


def _get_repos(manifest_path: Optional[str], group: Optional[str]) -> tuple:
    manifest_file = find_manifest(manifest_path)
    manifest = load_manifest(manifest_file)

    if group:
        repos = manifest.filter_by_group(group)
        if not repos:
            console.print(f"[yellow]Warning: No repos found in group '{group}'[/yellow]")
    else:
        repos = list(manifest.repos)

    if not repos:
        console.print("[red]No repositories to operate on.[/red]")
        raise typer.Exit(code=1)

    return manifest, repos


def _maybe_save_json(report, json_output: Optional[str]):
    if json_output:
        save_json_report(report, json_output)
        console.print(f"[dim]JSON report saved to {json_output}[/dim]")


@app.command("list")
def list_cmd(
    group: Optional[str] = typer.Option(None, "--group", "-g", help="Filter by group name"),
    manifest: Optional[str] = typer.Option(None, "--manifest", "-m", help="Path to repos.yaml"),
):
    """List all repositories in the manifest."""
    _, repos = _get_repos(manifest, group)
    print_repo_list(repos, group)


@app.command()
def status(
    group: Optional[str] = typer.Option(None, "--group", "-g", help="Filter by group name"),
    fetch: bool = typer.Option(False, "--fetch", help="Fetch from remote before status"),
    manifest: Optional[str] = typer.Option(None, "--manifest", "-m", help="Path to repos.yaml"),
    parallel: int = typer.Option(4, "--parallel", "-j", help="Number of parallel workers"),
    json_output: Optional[str] = typer.Option(None, "--json", help="Save JSON report to file"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
):
    """Show status of all repositories."""
    _, repos = _get_repos(manifest, group)

    def _task(repo):
        s = get_status(repo.path, fetch=fetch)
        ok = s.error is None
        return OperationResult(
            path=repo.path,
            ok=ok,
            exit_code=0 if ok else 1,
            stdout=s.last_commit_age,
            stderr=s.error or "",
            meta={
                "branch": s.branch,
                "dirty": s.dirty,
                "ahead": s.ahead,
                "behind": s.behind,
                "last_commit_age": s.last_commit_age,
            },
        )

    report = run_parallel(
        repos=repos,
        task_fn=_task,
        max_workers=parallel,
        command_name="status",
    )

    from .models import RepoStatus
    statuses = []
    for r in report.results:
        meta = r.meta
        statuses.append(RepoStatus(
            path=r.path,
            branch=meta.get("branch", "N/A"),
            dirty=meta.get("dirty", False),
            ahead=meta.get("ahead", 0),
            behind=meta.get("behind", 0),
            last_commit_age=meta.get("last_commit_age", "N/A"),
            error=None if r.ok else r.stderr,
        ))

    print_status_table(statuses)
    print_summary(report)
    _maybe_save_json(report, json_output)


@app.command()
def pull(
    group: Optional[str] = typer.Option(None, "--group", "-g", help="Filter by group name"),
    rebase: bool = typer.Option(False, "--rebase", help="Pull with rebase"),
    no_ff_only: bool = typer.Option(False, "--no-ff-only", help="Disable fast-forward only"),
    manifest: Optional[str] = typer.Option(None, "--manifest", "-m", help="Path to repos.yaml"),
    parallel: int = typer.Option(4, "--parallel", "-j", help="Number of parallel workers"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be done"),
    json_output: Optional[str] = typer.Option(None, "--json", help="Save JSON report to file"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
):
    """Pull latest changes for all repositories."""
    _, repos = _get_repos(manifest, group)

    def _task(repo):
        return pull_repo(
            repo.path,
            rebase=rebase,
            no_ff_only=no_ff_only,
            remote=repo.remote,
            branch=repo.branch,
            dry_run=dry_run,
        )

    report = run_parallel(
        repos=repos,
        task_fn=_task,
        max_workers=parallel,
        command_name="pull",
    )

    print_results_table(report)
    print_summary(report)
    if not dry_run:
        print_fail_details(report)
    _maybe_save_json(report, json_output)

    if report.fail_count > 0:
        raise typer.Exit(code=1)


@app.command()
def checkout(
    branch: str = typer.Argument(..., help="Branch name to checkout"),
    group: Optional[str] = typer.Option(None, "--group", "-g", help="Filter by group name"),
    manifest: Optional[str] = typer.Option(None, "--manifest", "-m", help="Path to repos.yaml"),
    parallel: int = typer.Option(4, "--parallel", "-j", help="Number of parallel workers"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be done"),
    json_output: Optional[str] = typer.Option(None, "--json", help="Save JSON report to file"),
):
    """Checkout a branch in all repositories."""
    _, repos = _get_repos(manifest, group)

    def _task(repo):
        return checkout_branch(repo.path, branch=branch, dry_run=dry_run)

    report = run_parallel(
        repos=repos,
        task_fn=_task,
        max_workers=parallel,
        command_name=f"checkout {branch}",
    )

    print_results_table(report)
    print_summary(report)
    if not dry_run:
        print_fail_details(report)
    _maybe_save_json(report, json_output)

    if report.fail_count > 0:
        raise typer.Exit(code=1)


@app.command("exec")
def exec_cmd(
    command: str = typer.Argument(..., help="Shell command to execute"),
    group: Optional[str] = typer.Option(None, "--group", "-g", help="Filter by group name"),
    parallel: int = typer.Option(8, "--parallel", "-j", help="Number of parallel workers"),
    fail_fast: bool = typer.Option(False, "--fail-fast", help="Stop on first failure"),
    include_dirty: bool = typer.Option(False, "--include-dirty", help="Run on dirty repos too"),
    timeout: int = typer.Option(300, "--timeout", help="Command timeout in seconds"),
    allow_interactive: bool = typer.Option(
        False, "--allow-interactive", help="Allow interactive commands"
    ),
    manifest: Optional[str] = typer.Option(None, "--manifest", "-m", help="Path to repos.yaml"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be done"),
    json_output: Optional[str] = typer.Option(None, "--json", help="Save JSON report to file"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
):
    """Execute a shell command in all repositories."""
    _, repos = _get_repos(manifest, group)

    def _task(repo):
        if not include_dirty and is_dirty(repo.path):
            return OperationResult(
                path=repo.path,
                ok=False,
                exit_code=0,
                skipped=True,
                skip_reason="dirty working tree (use --include-dirty to override)",
            )
        return exec_command(
            repo.path,
            command=command,
            timeout=timeout,
            allow_interactive=allow_interactive,
            dry_run=dry_run,
        )

    report = run_parallel(
        repos=repos,
        task_fn=_task,
        max_workers=parallel,
        command_name=f"exec: {command}",
        fail_fast=fail_fast,
    )

    print_results_table(report)
    print_summary(report)
    if not dry_run:
        print_fail_details(report)
    _maybe_save_json(report, json_output)

    if report.fail_count > 0:
        raise typer.Exit(code=1)


@app.command()
def tag(
    tag_name: str = typer.Argument(..., help="Tag name to create"),
    group: Optional[str] = typer.Option(None, "--group", "-g", help="Filter by group name"),
    message: Optional[str] = typer.Option(None, "--message", "-m", help="Tag message (annotated)"),
    push: bool = typer.Option(False, "--push", help="Push tag to remote after creation"),
    manifest: Optional[str] = typer.Option(None, "--manifest", "-m", help="Path to repos.yaml"),
    parallel: int = typer.Option(4, "--parallel", "-j", help="Number of parallel workers"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be done"),
    json_output: Optional[str] = typer.Option(None, "--json", help="Save JSON report to file"),
):
    """Create a tag in all repositories."""
    _, repos = _get_repos(manifest, group)

    def _task(repo):
        return create_tag(
            repo.path,
            tag_name=tag_name,
            message=message,
            push=push,
            remote=repo.remote,
            dry_run=dry_run,
        )

    report = run_parallel(
        repos=repos,
        task_fn=_task,
        max_workers=parallel,
        command_name=f"tag {tag_name}",
    )

    print_results_table(report)
    print_summary(report)
    if not dry_run:
        print_fail_details(report)
    _maybe_save_json(report, json_output)

    if report.fail_count > 0:
        raise typer.Exit(code=1)


@app.command("sync-fork")
def sync_fork_cmd(
    group: Optional[str] = typer.Option(None, "--group", "-g", help="Filter by group name"),
    rebase: bool = typer.Option(False, "--rebase", help="Use rebase instead of merge"),
    manifest: Optional[str] = typer.Option(None, "--manifest", "-m", help="Path to repos.yaml"),
    parallel: int = typer.Option(4, "--parallel", "-j", help="Number of parallel workers"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be done"),
    json_output: Optional[str] = typer.Option(None, "--json", help="Save JSON report to file"),
):
    """Sync fork with upstream (fetch upstream and merge/rebase)."""
    _, repos = _get_repos(manifest, group)

    def _task(repo):
        return sync_fork(
            repo.path,
            upstream_remote=repo.upstream_remote,
            use_rebase=rebase,
            branch=repo.branch,
            dry_run=dry_run,
        )

    report = run_parallel(
        repos=repos,
        task_fn=_task,
        max_workers=parallel,
        command_name="sync-fork",
    )

    print_results_table(report)
    print_summary(report)
    if not dry_run:
        print_fail_details(report)
    _maybe_save_json(report, json_output)

    if report.fail_count > 0:
        raise typer.Exit(code=1)


@app.command("init")
def init_cmd(
    scan_dir: str = typer.Argument(".", help="Directory to scan for git repos"),
    output: str = typer.Option("repos.yaml", "--output", "-o", help="Output manifest file"),
    default_branch: str = typer.Option("main", "--branch", help="Default branch name"),
    default_remote: str = typer.Option("origin", "--remote", help="Default remote name"),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing manifest"),
):
    """Scan a directory for git repos and generate a manifest."""
    output_path = Path(output).resolve()
    if output_path.exists() and not force:
        console.print(f"[red]Manifest already exists: {output_path}[/red]")
        console.print("[dim]Use --force to overwrite.[/dim]")
        raise typer.Exit(code=1)

    scan_path = Path(scan_dir).resolve()
    if not scan_path.is_dir():
        console.print(f"[red]Directory not found: {scan_path}[/red]")
        raise typer.Exit(code=1)

    manifest = generate_manifest(
        scan_dir=scan_path,
        output_path=output_path,
        default_branch=default_branch,
        default_remote=default_remote,
    )

    console.print(f"[green]Generated manifest: {output_path}[/green]")
    console.print(f"[dim]Found {len(manifest.repos)} repositories[/dim]")
    print_repo_list(manifest.repos)


def entrypoint():
    app()


if __name__ == "__main__":
    entrypoint()
