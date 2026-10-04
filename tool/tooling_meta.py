"""Emit advisory tooling metadata for local/CI diagnostics.

This is intentionally observational: versions are reported, not strictly pinned
or rejected, except where a test explicitly checks a required major API.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
from datetime import datetime, timezone


# The upstream generator uses a sibling absolute import for its contract.
# Limit this search path change to loading the unchanged vendored producer.
sys.path.insert(0, str(Path(__file__).resolve().parent / "vendor"))
try:
    import repository_metadata_generator as canonical
finally:
    sys.path.pop(0)

RUNTIME_KEYS = ("python",)
COMMANDS = ("git", "gh", "node", "npx")
DISTRIBUTIONS = (("pytest", "pytest"), ("stagehand", "stagehand"))


def collect() -> dict[str, object]:
    # Canonical collection rejects duplicate owners even when a probe is absent.
    # Project its strings into the existing advisory JSON groups without defaults.
    observed = canonical.collect_portable_tooling(
        include_python=True, commands=COMMANDS, distributions=DISTRIBUTIONS,
    )
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "runtime": {key: observed[key] for key in RUNTIME_KEYS if key in observed},
        "commands": {key: observed[key] for key in COMMANDS if key in observed},
        "packages": {key: observed[key] for key, _ in DISTRIBUTIONS if key in observed},
    }


if __name__ == "__main__":
    print(json.dumps(collect(), indent=2, ensure_ascii=False))
