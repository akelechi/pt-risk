"""Code version recorded in every run: the git commit, marked when the tree has changes."""

from __future__ import annotations

import subprocess
from pathlib import Path

UNVERSIONED = "unversioned"


def _git(root: Path, *args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return completed.stdout.strip() if completed.returncode == 0 else None


def code_version(root: Path) -> str:
    """Git commit sha of `root`, with '+dirty' if tracked files differ from that commit.

    A '+dirty' run cannot be tied to one commit; reproducibility claims need a clean tree.
    """
    sha = _git(root, "rev-parse", "HEAD")
    if not sha:
        return UNVERSIONED
    dirty = _git(root, "status", "--porcelain", "--untracked-files=no")
    return f"{sha}+dirty" if dirty else sha
