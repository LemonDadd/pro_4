import os
import tempfile
from pathlib import Path

import pytest
import yaml
from git import Repo

from gitbulk.config import generate_manifest, load_manifest
from gitbulk.git_ops import (
    create_tag,
    exec_command,
    get_status,
    is_dirty,
    is_git_repo,
    pull_repo,
    sync_fork,
)
from gitbulk.models import OperationResult, Report
from gitbulk.executor import run_parallel


@pytest.fixture
def temp_repos(tmp_path):
    repos = []
    for i in range(3):
        repo_path = tmp_path / f"repo-{i}"
        repo_path.mkdir()
        repo = Repo.init(repo_path)
        repo.config_writer().set_value("user", "email", "test@test.com").release()
        repo.config_writer().set_value("user", "name", "Test").release()
        (repo_path / "README.md").write_text(f"# Repo {i}\n")
        repo.index.add(["README.md"])
        repo.index.commit(f"initial commit {i}")
        repos.append(str(repo_path))

    manifest_path = tmp_path / "repos.yaml"
    manifest_data = {
        "defaults": {"branch": "main", "remote": "origin"},
        "groups": {
            "group-a": [f"./repo-0", "./repo-1"],
            "group-b": [f"./repo-2"],
        },
        "repos": [
            {"path": "./repo-0"},
            {"path": "./repo-1", "branch": "develop"},
            {"path": "./repo-2"},
        ],
    }
    with open(manifest_path, "w") as f:
        yaml.dump(manifest_data, f)

    return {
        "repos": repos,
        "manifest_path": str(manifest_path),
        "tmp_path": tmp_path,
    }


class TestManifest:
    def test_load_manifest(self, temp_repos):
        manifest = load_manifest(temp_repos["manifest_path"])
        assert len(manifest.repos) == 3
        assert "group-a" in manifest.groups
        assert "group-b" in manifest.groups
        assert manifest.defaults["branch"] == "main"

    def test_repo_override(self, temp_repos):
        manifest = load_manifest(temp_repos["manifest_path"])
        repo1 = [r for r in manifest.repos if "repo-1" in r.path][0]
        assert repo1.branch == "develop"

    def test_filter_by_group(self, temp_repos):
        manifest = load_manifest(temp_repos["manifest_path"])
        group_a = manifest.filter_by_group("group-a")
        assert len(group_a) == 2
        group_b = manifest.filter_by_group("group-b")
        assert len(group_b) == 1

    def test_repo_groups_assignment(self, temp_repos):
        manifest = load_manifest(temp_repos["manifest_path"])
        repo0 = [r for r in manifest.repos if "repo-0" in r.path][0]
        assert "group-a" in repo0.groups
        repo2 = [r for r in manifest.repos if "repo-2" in r.path][0]
        assert "group-b" in repo2.groups

    def test_default_upstream_remote(self, temp_repos):
        manifest = load_manifest(temp_repos["manifest_path"])
        for repo in manifest.repos:
            assert repo.upstream_remote == "upstream"

    def test_upstream_remote_override(self, tmp_path):
        manifest_path = tmp_path / "repos.yaml"
        repo_dir = tmp_path / "myrepo"
        repo_dir.mkdir()
        Repo.init(repo_dir)
        manifest_data = {
            "defaults": {
                "branch": "main",
                "remote": "origin",
                "upstream_remote": "my-upstream",
            },
            "repos": [
                {"path": "./myrepo", "upstream_remote": "custom-upstream"},
            ],
        }
        with open(manifest_path, "w") as f:
            yaml.dump(manifest_data, f)

        manifest = load_manifest(str(manifest_path))
        repo = manifest.repos[0]
        assert repo.upstream_remote == "custom-upstream"


class TestGitOps:
    def test_is_git_repo(self, temp_repos):
        assert is_git_repo(temp_repos["repos"][0])
        assert not is_git_repo(str(temp_repos["tmp_path"]))

    def test_get_status(self, temp_repos):
        status = get_status(temp_repos["repos"][0])
        assert status.branch == "main"
        assert not status.dirty
        assert status.error is None

    def test_get_status_dirty(self, temp_repos):
        repo_path = temp_repos["repos"][0]
        (Path(repo_path) / "dirty.txt").write_text("dirty\n")
        status = get_status(repo_path)
        assert status.dirty

    def test_is_dirty(self, temp_repos):
        repo_path = temp_repos["repos"][0]
        assert not is_dirty(repo_path)
        (Path(repo_path) / "dirty.txt").write_text("dirty\n")
        assert is_dirty(repo_path)

    def test_create_tag(self, temp_repos):
        repo_path = temp_repos["repos"][0]
        result = create_tag(repo_path, "v1.0.0", message="test tag")
        assert result.ok
        repo = Repo(repo_path)
        assert "v1.0.0" in [t.name for t in repo.tags]

    def test_create_tag_dry_run(self, temp_repos):
        repo_path = temp_repos["repos"][0]
        result = create_tag(repo_path, "v2.0.0", dry_run=True)
        assert result.ok
        repo = Repo(repo_path)
        assert "v2.0.0" not in [t.name for t in repo.tags]

    def test_exec_command(self, temp_repos):
        repo_path = temp_repos["repos"][0]
        result = exec_command(repo_path, "echo hello")
        assert result.ok
        assert "hello" in result.stdout

    def test_exec_command_fail(self, temp_repos):
        repo_path = temp_repos["repos"][0]
        result = exec_command(repo_path, "exit 1")
        assert not result.ok
        assert result.exit_code == 1

    def test_exec_command_interactive_blocked(self, temp_repos):
        repo_path = temp_repos["repos"][0]
        result = exec_command(repo_path, "vim", allow_interactive=False)
        assert not result.ok
        assert result.exit_code == 126
        assert "blocked" in result.stderr.lower()
        assert result.meta.get("blocked") is True

    def test_exec_command_interactive_allowed(self, temp_repos):
        repo_path = temp_repos["repos"][0]
        result = exec_command(repo_path, "echo vim_is_ok", allow_interactive=True)
        assert result.ok
        assert "vim_is_ok" in result.stdout

    def test_exec_command_interactive_tail_f(self, temp_repos):
        repo_path = temp_repos["repos"][0]
        result = exec_command(repo_path, "tail -f /dev/null", allow_interactive=False)
        assert not result.ok
        assert result.exit_code == 126

    def test_sync_fork_no_upstream(self, temp_repos):
        repo_path = temp_repos["repos"][0]
        result = sync_fork(repo_path, upstream_remote="upstream")
        assert not result.ok
        assert "not found" in result.stderr
        assert "upstream" in result.stderr

    def test_sync_fork_dry_run(self, temp_repos):
        repo_path = temp_repos["repos"][0]
        result = sync_fork(repo_path, dry_run=True)
        assert result.ok
        assert "dry-run" in result.stdout
        assert "merge" in result.stdout.lower()

    def test_sync_fork_dry_run_rebase(self, temp_repos):
        repo_path = temp_repos["repos"][0]
        result = sync_fork(repo_path, use_rebase=True, dry_run=True)
        assert result.ok
        assert "rebase" in result.stdout.lower()

    def test_sync_fork_dirty_repo(self, tmp_path):
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        repo = Repo.init(repo_dir)
        repo.config_writer().set_value("user", "email", "test@test.com").release()
        repo.config_writer().set_value("user", "name", "Test").release()
        (repo_dir / "file.txt").write_text("hello\n")
        repo.index.add(["file.txt"])
        repo.index.commit("initial")
        repo.create_remote("upstream", "https://example.com/upstream.git")

        (repo_dir / "dirty.txt").write_text("dirty\n")

        result = sync_fork(str(repo_dir), upstream_remote="upstream")
        assert not result.ok
        assert "dirty" in result.stderr.lower()

    def test_pull_repo_no_remote(self, temp_repos):
        repo_path = temp_repos["repos"][0]
        result = pull_repo(repo_path)
        assert not result.ok


class TestExecutor:
    def test_run_parallel(self, temp_repos):
        repos = temp_repos["repos"]

        def _task(repo_path):
            return OperationResult(path=repo_path, ok=True, stdout="ok")

        report = run_parallel(
            repos=repos,
            task_fn=_task,
            max_workers=2,
            command_name="test",
        )
        assert isinstance(report, Report)
        assert len(report.results) == 3
        assert report.success_count == 3
        assert report.fail_count == 0

    def test_run_parallel_with_failures(self, temp_repos):
        repos = temp_repos["repos"]

        def _task(repo_path):
            if "repo-1" in repo_path:
                return OperationResult(path=repo_path, ok=False, exit_code=1, stderr="error")
            return OperationResult(path=repo_path, ok=True)

        report = run_parallel(
            repos=repos,
            task_fn=_task,
            max_workers=2,
            command_name="test",
        )
        assert report.success_count == 2
        assert report.fail_count == 1

    def test_run_sequential(self, temp_repos):
        repos = temp_repos["repos"]

        def _task(repo_path):
            return OperationResult(path=repo_path, ok=True)

        report = run_parallel(
            repos=repos,
            task_fn=_task,
            max_workers=1,
            command_name="test",
        )
        assert len(report.results) == 3
        assert report.success_count == 3


class TestReport:
    def test_report_to_dict(self, temp_repos):
        from datetime import datetime

        results = [
            OperationResult(path="/a", ok=True, stdout="out", stderr=""),
            OperationResult(path="/b", ok=False, exit_code=1, stdout="", stderr="err"),
        ]
        report = Report(
            command="test",
            started_at=datetime.now(),
            finished_at=datetime.now(),
            results=results,
        )
        d = report.to_dict()
        assert d["command"] == "test"
        assert d["summary"]["success"] == 1
        assert d["summary"]["fail"] == 1
        assert d["summary"]["total"] == 2
        assert len(d["results"]) == 2

    def test_operation_result_tails(self):
        lines = "\n".join([f"line {i}" for i in range(10)])
        result = OperationResult(path="/a", ok=True, stdout=lines, stderr=lines)
        assert len(result.stdout_tail.splitlines()) == 5
        assert len(result.stderr_tail.splitlines()) == 5


class TestGenerateManifest:
    def test_generate_manifest(self, tmp_path):
        for i in range(3):
            repo_dir = tmp_path / f"repo-{i}"
            repo_dir.mkdir()
            Repo.init(repo_dir)

        output_path = tmp_path / "repos.yaml"
        manifest = generate_manifest(
            scan_dir=tmp_path,
            output_path=output_path,
            default_branch="main",
            default_remote="origin",
        )

        assert len(manifest.repos) == 3
        assert output_path.exists()

        with open(output_path) as f:
            data = yaml.safe_load(f)
        assert "defaults" in data
        assert "repos" in data
        assert len(data["repos"]) == 3
