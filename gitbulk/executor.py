from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from threading import Lock
from typing import Callable, Optional

from .models import OperationResult, Report


ProgressCallback = Optional[Callable[[str, str, Optional[OperationResult]], None]]


def run_parallel(
    repos: list,
    task_fn: Callable,
    task_args: dict | None = None,
    max_workers: int = 8,
    command_name: str = "operation",
    fail_fast: bool = False,
    on_start: ProgressCallback = None,
    on_done: ProgressCallback = None,
    attempt: int = 0,
) -> Report:
    task_args = task_args or {}
    started_at = datetime.now()
    results: list[OperationResult] = []
    lock = Lock()
    cancelled = False

    def _task_wrapper(repo) -> OperationResult:
        nonlocal cancelled
        repo_path = getattr(repo, "path", str(repo))
        if on_start:
            on_start("start", repo_path, None)
        start = time.time()
        try:
            result = task_fn(repo, **task_args)
        except Exception as e:
            result = OperationResult(
                path=repo_path,
                ok=False,
                exit_code=1,
                stderr=str(e),
                meta={"error_type": type(e).__name__},
            )
        duration_ms = int((time.time() - start) * 1000)
        if not isinstance(result.meta, dict):
            result.meta = {}
        result.meta["durationMs"] = duration_ms
        if attempt > 0:
            result.meta["attempt"] = attempt
        if on_done:
            on_done("done", repo_path, result)
        return result

    if max_workers <= 1:
        for repo in repos:
            result = _task_wrapper(repo)
            results.append(result)
            if fail_fast and not result.ok and not result.skipped:
                break
    else:
        workers = min(max_workers, len(repos))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_repo = {
                executor.submit(_task_wrapper, repo): repo
                for repo in repos
            }

            for future in as_completed(future_to_repo):
                result = future.result()
                with lock:
                    results.append(result)
                    if fail_fast and not result.ok and not result.skipped and not cancelled:
                        cancelled = True
                        for f in future_to_repo:
                            f.cancel()

    results.sort(key=lambda r: r.path)
    finished_at = datetime.now()

    return Report(
        command=command_name,
        started_at=started_at,
        finished_at=finished_at,
        results=results,
    )


def retry_failed(
    report: Report,
    repos: list,
    task_fn: Callable,
    task_args: dict | None = None,
    max_workers: int = 4,
    max_retries: int = 2,
    on_retry_start: ProgressCallback = None,
    on_retry_done: ProgressCallback = None,
) -> Report:
    if max_retries <= 0:
        return report

    task_args = task_args or {}
    repo_by_path = {getattr(r, "path", str(r)): r for r in repos}
    current_results = {r.path: r for r in report.results}

    for attempt_num in range(1, max_retries + 1):
        failed_paths = [
            r.path for r in report.results
            if not r.ok and not r.skipped
        ]
        if not failed_paths:
            break

        failed_repos = [
            repo_by_path[path]
            for path in failed_paths
            if path in repo_by_path
        ]
        if not failed_repos:
            break

        if on_retry_start:
            on_retry_start(
                "retry_start",
                f"attempt {attempt_num}/{max_retries}",
                None,
            )

        retry_report = run_parallel(
            repos=failed_repos,
            task_fn=task_fn,
            task_args=task_args,
            max_workers=max_workers,
            command_name=f"{report.command} (retry {attempt_num})",
            on_start=on_retry_start,
            on_done=on_retry_done,
            attempt=attempt_num,
        )

        for r in retry_report.results:
            current_results[r.path] = r

        report = Report(
            command=report.command,
            started_at=report.started_at,
            finished_at=datetime.now(),
            results=list(current_results.values()),
        )

    final_results = list(current_results.values())
    final_results.sort(key=lambda r: r.path)

    return Report(
        command=report.command,
        started_at=report.started_at,
        finished_at=datetime.now(),
        results=final_results,
    )


def run_sequential(
    repos: list,
    task_fn: Callable,
    task_args: dict | None = None,
    command_name: str = "operation",
    fail_fast: bool = False,
    on_start: ProgressCallback = None,
    on_done: ProgressCallback = None,
) -> Report:
    return run_parallel(
        repos=repos,
        task_fn=task_fn,
        task_args=task_args,
        max_workers=1,
        command_name=command_name,
        fail_fast=fail_fast,
        on_start=on_start,
        on_done=on_done,
    )
