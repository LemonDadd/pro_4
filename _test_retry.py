import threading

from gitbulk.executor import run_parallel, retry_failed
from gitbulk.models import OperationResult


call_count = {}
lock = threading.Lock()


class FakeRepo:
    def __init__(self, path):
        self.path = path


repos = [FakeRepo("/tmp/svc-user"), FakeRepo("/tmp/svc-order"), FakeRepo("/tmp/web-admin")]


def flaky_task(repo):
    name = repo.path.split("/")[-1]
    with lock:
        call_count[name] = call_count.get(name, 0) + 1
        attempt = call_count[name]

    if name == "svc-user":
        if attempt < 2:
            return OperationResult(
                path=repo.path, ok=False, exit_code=1, stderr="temporary error"
            )
        return OperationResult(
            path=repo.path, ok=True, stdout="success on retry"
        )
    elif name == "svc-order":
        return OperationResult(
            path=repo.path, ok=False, exit_code=2, stderr="persistent error"
        )
    else:
        return OperationResult(
            path=repo.path, ok=True, stdout="first try ok"
        )


def skipped_task(repo):
    name = repo.path.split("/")[-1]
    if name == "svc-user":
        return OperationResult(
            path=repo.path,
            ok=False,
            skipped=True,
            skip_reason="dirty",
        )
    return OperationResult(path=repo.path, ok=True, stdout="ok")


print("=== Test 1: retry with flaky task ===")
call_count.clear()
report = run_parallel(repos, flaky_task, max_workers=2, command_name="test")
print(f"After first run: success={report.success_count}, fail={report.fail_count}")

report2 = retry_failed(report, repos, flaky_task, max_workers=2, max_retries=2)
print(f"After 2 retries: success={report2.success_count}, fail={report2.fail_count}")

for r in sorted(report2.results, key=lambda x: x.path):
    name = r.path.split("/")[-1]
    dur = r.meta.get("durationMs", "?") if r.meta else "?"
    att = r.meta.get("attempt", 0) if r.meta else 0
    print(f"  {name}: ok={r.ok}, exit={r.exit_code}, durationMs={dur}, attempt={att}")


print()
print("=== Test 2: skipped repos should NOT be retried ===")
call_count.clear()
report_skip = run_parallel(repos, skipped_task, max_workers=2, command_name="test_skip")
print(f"After first run: success={report_skip.success_count}, fail={report_skip.fail_count}, skipped={report_skip.skip_count}")

report_skip2 = retry_failed(report_skip, repos, skipped_task, max_workers=2, max_retries=3)
print(f"After 3 retries: success={report_skip2.success_count}, fail={report_skip2.fail_count}, skipped={report_skip2.skip_count}")
assert report_skip2.skip_count == 1, "skipped count should remain 1"
print("✓ Skipped repos are correctly not retried")


print()
print("=== Test 3: max_retries=0 should be no-op ===")
call_count.clear()
report_no_retry = run_parallel(repos, flaky_task, max_workers=2, command_name="test")
before = report_no_retry.fail_count
report_no_retry2 = retry_failed(report_no_retry, repos, flaky_task, max_retries=0)
after = report_no_retry2.fail_count
assert before == after, "fail count should be same with max_retries=0"
print("✓ max_retries=0 is a no-op")

print()
print("All tests passed!")
