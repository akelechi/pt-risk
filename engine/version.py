"""Code version recorded in every run: the git commit, marked when the tree has changes.

Where there is no git checkout (a deployed bundle), the commit the bundle was built from
is read from `VERCEL_GIT_COMMIT_SHA` when the host provides it.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

UNVERSIONED = "unversioned"
DEPLOYED_COMMIT_ENV = "VERCEL_GIT_COMMIT_SHA"


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
        return os.environ.get(DEPLOYED_COMMIT_ENV) or UNVERSIONED
    dirty = _git(root, "status", "--porcelain", "--untracked-files=no")
    return f"{sha}+dirty" if dirty else sha
