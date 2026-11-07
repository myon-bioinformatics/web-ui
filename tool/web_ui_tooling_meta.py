"""Emit advisory tooling metadata for local/CI diagnostics.

This is intentionally observational: versions are reported, not strictly pinned
or rejected, except where a test explicitly checks a required major API.

Runtime/CLI probing used to call vendored gh_identity.tool_versions(); that
copy was removed. Probes live here (stdlib only) under the historical
``canonical`` name so existing tests can still patch shutil/subprocess.
"""
from __future__ import annotations

import json, platform, re, shutil, subprocess, sys
from datetime import datetime, timezone; from importlib import metadata as importlib_metadata


RUNTIME_KEYS = ("python",)
COMMANDS = ("git", "gh", "node", "npx")
DISTRIBUTIONS = (("pytest", "pytest"), ("stagehand", "stagehand"))
_PACKAGE_VERSION = re.compile(
    r"(?:[0-9]+!)?[0-9]+(?:\.[0-9]+)*(?:(?:a|b|rc)[0-9]+)?(?:\.post[0-9]+)?(?:\.dev[0-9]+)?"
    r"(?:\+(?:[0-9A-Za-z][0-9A-Za-z.-]*)?)?"
)
_TOOL_ARGS = {
    "git": "--version",
    "gh": "--version",
    "node": "--version",
    "npm": "--version",
    "npx": "--version",
}
_VERSION = r"[0-9]+(?:\.[0-9]+)+(?:[-+._][0-9A-Za-z][0-9A-Za-z.-]*)?"
_TOOL_PATTERNS = {
    "git": re.compile(r"git version (?P<v>" + _VERSION + r")(?:\s.*)?"),
    "gh": re.compile(r"gh version (?P<v>" + _VERSION + r")(?:\s.*)?"),
    "node": re.compile(r"v(?P<v>" + _VERSION + r")"),
    "npm": re.compile(r"(?P<v>" + _VERSION + r")"),
    "npx": re.compile(r"(?P<v>" + _VERSION + r")"),
    "python": re.compile(
        r"(?P<v>(?:[0-9]+!)?[0-9]+(?:\.[0-9]+)*(?:(?:a|b|rc)[0-9]+)?(?:\.post[0-9]+)?"
        r"(?:\.dev[0-9]+)?(?:\+(?:[0-9A-Za-z][0-9A-Za-z.-]*)?)?)"
    ),
}


def tool_versions(commands=(), *, include_python=False, timeout=5.0):
    """Explicitly requested, allowlisted tool versions; missing tools are omitted."""
    if isinstance(commands, (str, bytes)):
        raise TypeError("commands must be a sequence of command names")
    unknown = [command for command in commands if command not in _TOOL_ARGS]
    if unknown:
        raise ValueError("unsupported tooling command: " + ", ".join(map(str, unknown)))
    observed = {}
    if include_python:
        match = _TOOL_PATTERNS["python"].fullmatch(platform.python_version())
        if match:
            observed["python"] = match.group("v")
    for command in commands:
        executable = shutil.which(command)
        if not executable:
            continue
        try:
            result = subprocess.run(
                [executable, _TOOL_ARGS[command]],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        text = (result.stdout.strip() or result.stderr.strip()) if result.returncode == 0 else ""
        first = next((line.strip() for line in text.splitlines() if line.strip()), "")
        match = _TOOL_PATTERNS[command].fullmatch(first)
        if match and len(match.group("v")) <= 32:
            observed[command] = match.group("v")
    return observed


# Historical alias: tests patch canonical.shutil / canonical.subprocess /
# canonical.tool_versions the same way they patched the old vendored module.
canonical = sys.modules[__name__]


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


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess CLI
    print(json.dumps(collect(), indent=2, ensure_ascii=False))
