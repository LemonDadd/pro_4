from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from .models import Manifest, RepoConfig


def load_manifest(manifest_path: str | Path) -> Manifest:
    path = Path(manifest_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Manifest file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    base_dir = path.parent

    defaults = data.get("defaults", {}) or {}
    default_branch = defaults.get("branch", "main")
    default_remote = defaults.get("remote", "origin")

    groups_raw = data.get("groups", {}) or {}
    groups: dict[str, list[str]] = {}
    for gname, paths in groups_raw.items():
        groups[gname] = [str(base_dir / Path(p)) for p in paths]

    repos_raw = data.get("repos", []) or []
    repos: list[RepoConfig] = []

    all_repo_paths: set[str] = set()
    for gpaths in groups.values():
        all_repo_paths.update(gpaths)
    for r in repos_raw:
        rpath = str(base_dir / Path(r["path"]))
        all_repo_paths.add(rpath)

    for repo_path in sorted(all_repo_paths):
        repo_branch = default_branch
        repo_remote = default_remote

        for r in repos_raw:
            rpath = str(base_dir / Path(r["path"]))
            if rpath == repo_path:
                repo_branch = r.get("branch", repo_branch)
                repo_remote = r.get("remote", repo_remote)
                break

        repo_groups = [
            gname for gname, gpaths in groups.items() if repo_path in gpaths
        ]

        repos.append(
            RepoConfig(
                path=repo_path,
                branch=repo_branch,
                remote=repo_remote,
                groups=repo_groups,
            )
        )

    return Manifest(repos=repos, groups=groups, defaults=defaults)


def discover_manifest(start_dir: str | Path = ".") -> Path | None:
    current = Path(start_dir).resolve()
    while True:
        candidate = current / "repos.yaml"
        if candidate.exists():
            return candidate
        candidate_yml = current / "repos.yml"
        if candidate_yml.exists():
            return candidate_yml
        if current.parent == current:
            return None
        current = current.parent


def find_manifest(explicit: str | None = None) -> Path:
    if explicit:
        path = Path(explicit).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Manifest file not found: {path}")
        return path

    discovered = discover_manifest(".")
    if discovered is None:
        raise FileNotFoundError(
            "No repos.yaml found in current directory or any parent directory. "
            "Use --manifest to specify a path, or run 'gitbulk init' to create one."
        )
    return discovered


def generate_manifest(
    scan_dir: str | Path,
    output_path: str | Path,
    default_branch: str = "main",
    default_remote: str = "origin",
) -> Manifest:
    scan_path = Path(scan_dir).resolve()
    output = Path(output_path).resolve()
    base_dir = output.parent

    repos: list[dict[str, Any]] = []
    for entry in sorted(scan_path.iterdir()):
        if not entry.is_dir():
            continue
        git_dir = entry / ".git"
        if not git_dir.exists():
            continue

        rel_path = os.path.relpath(entry, base_dir)
        if not rel_path.startswith(".") and "/" not in rel_path:
            rel_path = f"./{rel_path}"

        repos.append({"path": rel_path})

    manifest_data = {
        "defaults": {
            "branch": default_branch,
            "remote": default_remote,
        },
        "repos": repos,
    }

    with open(output, "w", encoding="utf-8") as f:
        yaml.dump(manifest_data, f, default_flow_style=False, sort_keys=False)

    return load_manifest(output)
