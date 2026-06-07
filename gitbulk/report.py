from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.table import Table

from .models import OperationResult, Report, RepoStatus


console = Console()


def print_status_table(statuses: list[RepoStatus]) -> None:
    table = Table(title="Git Repo Status", show_lines=False)
    table.add_column("Repo", style="cyan", no_wrap=True)
    table.add_column("Branch", style="green")
    table.add_column("Dirty", style="red", justify="center")
    table.add_column("Ahead", style="yellow", justify="right")
    table.add_column("Behind", style="yellow", justify="right")
    table.add_column("Last Commit", style="dim")

    for s in statuses:
        dirty_mark = "[red]✓[/red]" if s.dirty else ""
        branch_style = "green" if s.error is None else "red"
        repo_name = Path(s.path).name
        if s.error:
            table.add_row(
                f"[dim]{repo_name}[/dim]",
                f"[red]ERROR[/red]",
                "",
                "",
                "",
                f"[red]{s.error}[/red]",
            )
        else:
            table.add_row(
                repo_name,
                f"[{branch_style}]{s.branch}[/{branch_style}]",
                dirty_mark,
                str(s.ahead) if s.ahead > 0 else "",
                str(s.behind) if s.behind > 0 else "",
                s.last_commit_age,
            )

    console.print(table)


def print_results_table(report: Report) -> None:
    table = Table(title=f"Results: {report.command}", show_lines=False)
    table.add_column("Repo", style="cyan", no_wrap=True)
    table.add_column("Status", style="green", justify="center")
    table.add_column("Exit Code", justify="right")
    table.add_column("Details", style="dim")

    for r in report.results:
        repo_name = Path(r.path).name
        if r.skipped:
            table.add_row(
                repo_name,
                "[yellow]skipped[/yellow]",
                "-",
                r.skip_reason or "",
            )
        elif r.ok:
            table.add_row(
                repo_name,
                "[green]✓ ok[/green]",
                str(r.exit_code),
                r.stdout_tail if r.stdout else "",
            )
        else:
            details = r.stderr_tail if r.stderr else r.stdout_tail
            table.add_row(
                repo_name,
                "[red]✗ fail[/red]",
                str(r.exit_code),
                details[:80] if details else "",
            )

    console.print(table)


def print_summary(report: Report) -> None:
    total = len(report.results)
    success = report.success_count
    fail = report.fail_count
    skipped = report.skip_count
    duration = (report.finished_at - report.started_at).total_seconds()

    summary_parts = []
    if success > 0:
        summary_parts.append(f"[green]{success} ok[/green]")
    if fail > 0:
        summary_parts.append(f"[red]{fail} fail[/red]")
    if skipped > 0:
        summary_parts.append(f"[yellow]{skipped} skipped[/yellow]")
    summary_parts.append(f"[dim]{total} total[/dim]")
    summary_parts.append(f"[dim]{duration:.2f}s[/dim]")

    console.print("  ".join(summary_parts))


def print_fail_details(report: Report) -> None:
    failed = [r for r in report.results if not r.ok and not r.skipped]
    if not failed:
        return

    console.print()
    console.print("[bold red]Failures:[/bold red]")
    for r in failed:
        repo_name = Path(r.path).name
        console.print()
        console.print(f"  [cyan]{repo_name}[/cyan] (exit code {r.exit_code})")
        if r.stderr:
            for line in r.stderr_tail.splitlines():
                console.print(f"    [dim]stderr:[/dim] {line}")
        if r.stdout and not r.stderr:
            for line in r.stdout_tail.splitlines():
                console.print(f"    [dim]stdout:[/dim] {line}")


def save_json_report(report: Report, output_path: str) -> None:
    path = Path(output_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)


def print_repo_list(repos, group: Optional[str] = None) -> None:
    title = f"Repositories" + (f" (group: {group})" if group else "")
    table = Table(title=title, show_lines=False)
    table.add_column("Path", style="cyan")
    table.add_column("Branch", style="green")
    table.add_column("Remote", style="yellow")
    table.add_column("Groups", style="magenta")

    for repo in repos:
        groups_str = ", ".join(repo.groups) if repo.groups else "-"
        table.add_row(repo.path, repo.branch, repo.remote, groups_str)

    console.print(table)
