from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Callable, Iterable

from .models import OperationResult, Report


def run_parallel(
    repos: list,
    task_fn: Callable,
    task_args: dict | None = None,
    max_workers: int = 8,
    command_name: str = "operation",
    fail_fast: bool = False,
) -> Report:
    task_args = task_args or {}
    started_at = datetime.now()
    results: list[OperationResult] = []

    if max_workers <= 1:
        for repo in repos:
            result = _run_task(repo, task_fn, task_args)
            results.append(result)
            if fail_fast and not result.ok and not result.skipped:
                break
    else:
        workers = min(max_workers, len(repos))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_repo = {
                executor.submit(_run_task, repo, task_fn, task_args): repo
                for repo in repos
            }

            for future in as_completed(future_to_repo):
                result = future.result()
                results.append(result)
                if fail_fast and not result.ok and not result.skipped:
                    for f in future_to_repo:
                        f.cancel()
                    break

    results.sort(key=lambda r: r.path)
    finished_at = datetime.now()

    return Report(
        command=command_name,
        started_at=started_at,
        finished_at=finished_at,
        results=results,
    )


def _run_task(repo, task_fn: Callable, task_args: dict) -> OperationResult:
    try:
        return task_fn(repo, **task_args)
    except Exception as e:
        return OperationResult(
            path=getattr(repo, "path", str(repo)),
            ok=False,
            exit_code=1,
            stderr=str(e),
            meta={"error_type": type(e).__name__},
        )


def run_sequential(
    repos: list,
    task_fn: Callable,
    task_args: dict | None = None,
    command_name: str = "operation",
    fail_fast: bool = False,
) -> Report:
    return run_parallel(
        repos=repos,
        task_fn=task_fn,
        task_args=task_args,
        max_workers=1,
        command_name=command_name,
        fail_fast=fail_fast,
    )


def retry_failed(
    report: Report,
    task_fn: Callable,
    task_args: dict | None = None,
    max_workers: int = 4,
    max_retries: int = 2,
) -> Report:
    if max_retries <= 0:
        return report

    task_args = task_args or {}
    current_results = {r.path: r for r in report.results}

    for attempt in range(max_retries):
        failed = [
            r.path for r in report.results
            if not r.ok and not r.skipped
        ]
        if not failed:
            break

        failed_repos = [path for path in failed if path in current_results]
        if not failed_repos:
            break

        retry_results = run_parallel(
            repos=failed_repos,
            task_fn=task_fn,
            task_args=task_args,
            max_workers=max_workers,
            command_name=f"{report.command} (retry {attempt + 1})",
        )

        for r in retry_results.results:
            current_results[r.path] = r

    final_results = list(current_results.values())
    final_results.sort(key=lambda r: r.path)

    return Report(
        command=report.command,
        started_at=report.started_at,
        finished_at=datetime.now(),
        results=final_results,
    )
