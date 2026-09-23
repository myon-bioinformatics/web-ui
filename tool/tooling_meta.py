"""Emit advisory tooling metadata for local/CI diagnostics.

This is intentionally observational: versions are reported, not strictly pinned
or rejected, except where a test explicitly checks a required major API.
"""
from __future__ import annotations

import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMMAND_TIMEOUT = float(os.environ.get("WEB_UI_TOOL_TIMEOUT", "10"))


def _command_version(command: str, *args: str) -> str | None:
    executable = shutil.which(command)
    if not executable:
        return None
    try:
        result = subprocess.run(
            [executable, *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = (result.stdout or result.stderr).strip().splitlines()
    return text[0] if text else None


def _git(*args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def collect() -> dict[str, object]:
    packages = {}
    for name in ("pytest", "stagehand"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "repository": {
            "sha": _git("rev-parse", "HEAD"),
            "short_sha": _git("rev-parse", "--short=8", "HEAD"),
            "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        },
        "runtime": {"python": platform.python_version()},
        "commands": {
            "git": _command_version("git", "--version"),
            "gh": _command_version("gh", "--version"),
            "node": _command_version("node", "--version"),
            "npx": _command_version("npx", "--version"),
        },
        "packages": packages,
    }


if __name__ == "__main__":
    print(json.dumps(collect(), indent=2, ensure_ascii=False))
