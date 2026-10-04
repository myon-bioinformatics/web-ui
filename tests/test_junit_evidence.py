"""Keep tooling probe failures red while exporting compact failure identities."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_tooling_probe_child_keeps_exit_status_with_junit(tmp_path):
    importer = ROOT / ".junit-tools" / "xprobe.py"
    if not importer.is_file() and os.environ.get("GITHUB_ACTIONS") != "true" and not os.environ.get("WEB_UI_FAILURE_EVIDENCE"):
        pytest.skip("optional local JUnit regression: fetch the pinned importer (docs/junit-evidence.md)")
    assert importer.is_file(), "CI must provision the pinned test-only JUnit importer"
    evidence = Path(os.environ.get("WEB_UI_FAILURE_EVIDENCE", tmp_path / "evidence")).resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    fixture = tmp_path / "test_probe.py"
    fixture.write_text('''
import pytest
from tool.tooling_meta import _command_version

@pytest.fixture
def unavailable(monkeypatch):
    monkeypatch.setattr("tool.tooling_meta.shutil.which", lambda _: None)

def test_unavailable_command(unavailable):
    assert _command_version("synthetic-missing") is None

@pytest.mark.parametrize("command", ["PARAMETER_SENTINEL"], ids=["PARAMETER_SENTINEL"])
def test_wrong_probe_expectation(unavailable, command):
    print("STDOUT_SENTINEL")
    assert _command_version(command) == "ASSERTION_SENTINEL"

@pytest.fixture
def broken_setup():
    raise RuntimeError("SETUP_SENTINEL")

def test_probe_setup_error(broken_setup):
    pass

def test_skip():
    pytest.skip("synthetic skipped probe")
''', encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=str(ROOT), PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTEST_ADDOPTS="")
    command = [sys.executable, "-m", "pytest", str(fixture), "-c", os.devnull,
               "--rootdir", str(tmp_path), "--confcutdir", str(tmp_path), "-q"]
    plain = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    reported = subprocess.run(command + ["--junitxml", str(evidence / "junit.xml"),
                              "-o", "junit_logging=all"], cwd=tmp_path, env=env,
                              capture_output=True, text=True, timeout=60)
    (evidence / "exit.json").write_text(json.dumps({"without_junit": plain.returncode,
                                                "with_junit": reported.returncode}), encoding="utf-8")
    assert plain.returncode == reported.returncode == 1, plain.stdout + plain.stderr + reported.stdout + reported.stderr
    data = importer.read_bytes()
    assert hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest() == "dbc5b7d55005d6288c072a7612584d6170c216f4"
    spec = importlib.util.spec_from_file_location("probe_junit_xprobe", importer)
    xprobe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(xprobe)
    raw = (evidence / "junit.xml").read_text(encoding="utf-8")
    imported = xprobe.cases_from_junit(raw, repository="myon-bioinformatics/web-ui", report_id="controlled-probe")
    assert imported["truncated"] is False
    cases = imported["cases"]
    assert {(c["value"]["test"], c["value"]["kind"]) for c in cases} == {
        ("test_wrong_probe_expectation", "failure"), ("test_probe_setup_error", "error")}
    compact = xprobe.corpus_to_json(cases, jsonl=True)
    (evidence / "failure-identity.jsonl").write_text(compact, encoding="utf-8")
    assert all(c["context"]["commit_sha"] is None for c in cases)
    for sentinel in ("PARAMETER_SENTINEL", "STDOUT_SENTINEL", "ASSERTION_SENTINEL", "SETUP_SENTINEL"):
        assert sentinel in raw and sentinel not in compact
