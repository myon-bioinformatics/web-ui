"""Helpers the test modules share (a test module imports them as ``from support import ...``; pytest puts this directory on the path)."""
from __future__ import annotations

import re
import shutil
import subprocess


def node26() -> str | None:
    """The path of an existing Node 26 or newer, else None: the Node-side tests skip, nothing is installed."""
    node = shutil.which("node")
    if not node:
        return None
    try:
        done = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    match = re.match(r"v?(\d+)", done.stdout.strip())
    return node if match and int(match.group(1)) >= 26 else None


def flutter_case(tid, sid, name, result="success", **done):
    """The two NDJSON events (testStart, testDone) of one case in a ``flutter test --reporter json`` stream."""
    return [{"type": "testStart", "test": {"id": tid, "suiteID": sid, "name": name}}, {"type": "testDone", "testID": tid, "result": result, **done}]
