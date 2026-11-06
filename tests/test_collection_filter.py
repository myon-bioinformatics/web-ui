import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from support import node26

from collection_filter import filter_request

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "tests/fixtures/collection_filter_cases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES["cases"], ids=lambda c: c["name"])
def test_python_filter_and_cli(case):
    request = copy.deepcopy(case["request"])
    assert filter_request(request) == case["expected"]
    assert request == case["request"]
    result = subprocess.run([sys.executable, "-S", str(ROOT / "collection_filter.py")],
                            input=json.dumps(request, ensure_ascii=False), text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert json.loads(result.stdout) == case["expected"]
    assert result.stdout.endswith("\n")


@pytest.mark.parametrize("payload", CASES["invalid"])
def test_invalid_request_fails_closed(payload):
    result = subprocess.run([sys.executable, "-S", str(ROOT / "collection_filter.py")],
                            input=json.dumps(payload), text=True, capture_output=True)
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.startswith("error: ")


def test_malformed_json_fails_without_partial_output():
    for data in ("{", '{"items": [], "query": NaN}', '{"items": []} trailing'):
        result = subprocess.run([sys.executable, "-S", str(ROOT / "collection_filter.py")],
                                input=data, text=True, capture_output=True)
        assert result.returncode == 2
        assert result.stdout == ""


@pytest.mark.skipif(not node26(), reason="Node 26+ is optional in Python-only environments")
def test_node_reaches_the_same_tool_through_the_shared_launcher():
    # No Node twin: Node runs collection_filter.py via vendor/py_launch.cjs, so both routes share one implementation.
    env = {**os.environ, "PYTHON": sys.executable}
    run = lambda request: subprocess.run(["node", "vendor/py_launch.cjs", "--", "collection_filter.py"], cwd=ROOT, env=env,
                                         input=request, text=True, capture_output=True)
    for case in CASES["cases"]:
        result = run(json.dumps(case["request"], ensure_ascii=False))
        assert result.returncode == 0, (case["name"], result.stderr)
        assert json.loads(result.stdout) == case["expected"]
    for request in CASES["invalid"]:
        result = run(json.dumps(request))
        assert result.returncode == 2
        assert result.stdout == ""

    for malformed in ("{", '{"items": [], "query": NaN}', '{"items": []} trailing'):
        result = run(malformed)
        assert result.returncode == 2
        assert result.stdout == ""
        assert result.stderr.startswith("error: ")
