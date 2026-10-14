"""Emit advisory tooling metadata for local/CI diagnostics.

This is intentionally observational: versions are reported, not strictly pinned
or rejected, except where a test explicitly checks a required major API.
"""
from __future__ import annotations

import importlib.util
import json
from importlib import metadata as importlib_metadata
from pathlib import Path
import re
import sys
from datetime import datetime, timezone


_VENDOR = Path(__file__).resolve().parent / "vendor" / "gh_identity.py"
_SPEC = importlib.util.spec_from_file_location("gh_identity_vendor", _VENDOR)
canonical = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(canonical)


def observe_command_version(command: str) -> str | None:
    if command not in canonical._RM_TOOL_ARGS:
        raise ValueError("unsupported tooling command: " + command)
    return canonical.tool_versions((command,), include_python=False).get(command)


canonical.observe_command_version = observe_command_version  # type: ignore[attr-defined]

RUNTIME_KEYS = ("python",)
COMMANDS = ("git", "gh", "node", "npx")
DISTRIBUTIONS = (("pytest", "pytest"), ("stagehand", "stagehand"))
_PACKAGE_VERSION = re.compile(
    r"(?:[0-9]+!)?[0-9]+(?:\.[0-9]+)*(?:(?:a|b|rc)[0-9]+)?(?:\.post[0-9]+)?(?:\.dev[0-9]+)?"
    r"(?:\+(?:[0-9A-Za-z][0-9A-Za-z.-]*)?)?"
)


def observe_package_version(distribution: str) -> str | None:
    try:
        value = importlib_metadata.version(distribution)
    except importlib_metadata.PackageNotFoundError:
        return None
    candidate = value.strip()
    match = _PACKAGE_VERSION.fullmatch(candidate)
    if not match or len(match.group(0)) > 32:
        return None
    return match.group(0)


def collect() -> dict[str, object]:
    owners = list(RUNTIME_KEYS) + list(COMMANDS) + [key for key, _ in DISTRIBUTIONS]
    if len(owners) != len(set(owners)):
        raise ValueError("tooling keys must have exactly one canonical source")
    observed = canonical.tool_versions(COMMANDS, include_python=True)
    for key, distribution in DISTRIBUTIONS:
        value = observe_package_version(distribution)
        if value is not None:
            observed[key] = value
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "runtime": {key: observed[key] for key in RUNTIME_KEYS if key in observed},
        "commands": {key: observed[key] for key in COMMANDS if key in observed},
        "packages": {key: observed[key] for key, _ in DISTRIBUTIONS if key in observed},
    }


if __name__ == "__main__":
    print(json.dumps(collect(), indent=2, ensure_ascii=False))
