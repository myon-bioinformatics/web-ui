"""Vendor lock CI workflow regression tests."""
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ".github/workflows/tooling-smoke.yml"
TEST_JOB = "tooling"
PIN = "f907560c2b9b3f7a0f78f4434f547f91cb2ef954"


def _lock_entries(root=ROOT):
    lock = json.loads((root / "vendor.lock.json").read_text(encoding="utf-8"))
    assert lock["schema"] == "vendor-lock/1"
    return lock["files"]


SNAPSHOT = ["vendor.lock.json", *[e["destination"] for e in _lock_entries()]]


def _workflow():
    import yaml

    return yaml.load((ROOT / WORKFLOW).read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def _copy_snapshot(root):
    for name in SNAPSHOT:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, path)


def test_vendor_lock_lists_expected_sources():
    expected = {
        ("myon-bioinformatics/Ironmate", "LICENSE", "tool/vendor/LICENSE"),
        ("myon-bioinformatics/gh_identity", "gh_identity.py", "tool/vendor/gh_identity.py"),
        ("myon-bioinformatics/gh_identity", "LICENSE", "tool/vendor/gh_identity-LICENSE"),
    }
    actual = {(e["repository"], e["source"], e["destination"]) for e in _lock_entries()}
    assert actual == expected
    assert all(e["ref"] == e["commit"] for e in _lock_entries())


def test_public_vendor_ci_updates_without_repository_writes():
    ci = _workflow()
    assert {"push", "pull_request"} <= set(ci["on"])
    assert "schedule" not in ci["on"]
    assert ci.get("permissions", {"contents": "read"}) == {"contents": "read"}
    jobs = ci["jobs"]
    for job in (jobs["resolve-vendor"], jobs[TEST_JOB]):
        assert "continue-on-error" not in job
    resolve = jobs["resolve-vendor"]["steps"]
    test = jobs[TEST_JOB]["steps"]
    assert jobs["resolve-vendor"]["permissions"] == jobs[TEST_JOB]["permissions"] == {"contents": "read"}
    assert not any(s.get("name") == "Update public vendor files for this run" for s in resolve)
    assert not any("vendor_sync.py promote" in s.get("run", "") for steps in (resolve, test) for s in steps)
    assert not any("vendor_sync.py update" in s.get("run", "") for steps in (resolve, test) for s in steps)
    assert not any("sync_vendor_provenance" in s.get("run", "") for steps in (resolve, test) for s in steps)
    recreate = next(s for s in resolve if s.get("name") == "Recreate locked vendor files from GitHub")
    assert recreate["shell"] == "bash"
    assert recreate["run"].splitlines() == [
        "python -S - <<'PY'",
        "import json",
        "from pathlib import Path",
        "for entry in json.loads(Path('vendor.lock.json').read_text(encoding='utf-8'))['files']:",
        "    Path(entry['destination']).unlink()",
        "PY",
        "python -S .vendor-sync-tools/vendor_sync.py materialize --manifest vendor.lock.json",
        "python -S .vendor-sync-tools/vendor_sync.py check --manifest vendor.lock.json",
    ]
    needs = jobs[TEST_JOB]["needs"]
    assert "resolve-vendor" in ([needs] if isinstance(needs, str) else needs)
    download = next(i for i, s in enumerate(test) if s.get("name") == "Download resolved vendor snapshot")
    verify = next(i for i, s in enumerate(test) if s.get("name") == "Verify resolved vendor snapshot")
    tests = [i for i, s in enumerate(test) if "pytest " in s.get("run", "")]
    assert tests and download < verify < min(tests)
    assert test[download]["with"]["name"] == "vendor-snapshot"
    assert test[verify]["run"].splitlines() == [
        "python -S .vendor-sync-tools/vendor_sync.py check --manifest vendor.lock.json",
    ]
    for steps, name in (
        (resolve, "Preserve resolved vendor snapshot"),
        (test, "Preserve vendor lock used by this run"),
    ):
        upload = next(s for s in steps if s.get("name") == name)
        assert upload["if"] == "always()"
        assert upload["with"]["if-no-files-found"] == "error"
        assert upload["with"]["path"].startswith("build/vendor-evidence-")
    pins = [
        s["with"]["ref"]
        for steps in (resolve, test)
        for s in steps
        if s.get("with", {}).get("repository") == "myon-bioinformatics/myon-bioinformatics"
    ]
    assert pins == [PIN] * 2
    for steps in (resolve, test):
        for step in steps:
            if step.get("uses", "").startswith("actions/checkout@"):
                assert step["with"]["persist-credentials"] == "false"
            assert not any(
                x in step.get("run", "") for x in ("|| true", "|| :", "set +e", "git push", "git commit", "gh pr")
            )
            assert "continue-on-error" not in step
    text = (ROOT / WORKFLOW).read_text(encoding="utf-8")
    assert not any(x in text for x in ("secrets.", "VENDOR_UPDATE_TOKEN", "VENDOR_UPDATES_ENABLED", "GH_TOKEN"))
    assert "vendor-mode" not in text
    assert "provenance.json" not in text


def test_locked_baseline_runs_automatically_without_candidate_snapshot():
    ci = _workflow()
    job = ci["jobs"]["test-locked"]
    assert job["permissions"] == {"contents": "read"}
    assert "continue-on-error" not in job
    assert job.get("needs") == ci["jobs"]["resolve-vendor"].get("needs")
    assert job.get("if") == ci["jobs"]["resolve-vendor"].get("if")
    matrix = job.get("strategy", {}).get("matrix", {})
    assert all(len(values) == 1 for values in matrix.values())
    steps = job["steps"]
    assert not any("vendor_sync.py promote" in s.get("run", "") for s in steps)
    assert not any("vendor_sync.py update" in s.get("run", "") for s in steps)
    assert not any(s.get("uses", "").startswith("actions/download-artifact@") for s in steps)
    verify = next(i for i, s in enumerate(steps) if s.get("name") == "Verify checked-in vendor copies")
    recreate = next(i for i, s in enumerate(steps) if s.get("name") == "Recreate locked vendor files from GitHub")
    tests = [i for i, s in enumerate(steps) if "pytest " in s.get("run", "")]
    assert tests and verify < recreate < min(tests)
    original = next(
        s for s in ci["jobs"]["resolve-vendor"]["steps"]
        if s.get("name") == "Recreate locked vendor files from GitHub"
    )
    assert steps[recreate] == original
    tool = next(s for s in steps if s.get("name") == "Fetch pinned shared vendor tool")
    assert tool["with"]["ref"] == PIN
    for step in steps:
        assert "continue-on-error" not in step
        if step.get("uses", "").startswith("actions/checkout@"):
            assert step["with"]["persist-credentials"] == "false"
        if step.get("uses", "").startswith("actions/upload-artifact@"):
            assert step["with"]["name"].startswith("locked-")
            if step["with"]["name"].startswith(("locked-vendor-", "locked-junit-", "locked-controlled-")):
                assert step["if"] == "always()"
            assert step["with"]["if-no-files-found"] == "error"
    lock = next(s for s in steps if s.get("name") == "Preserve vendor lock used by this run")
    assert lock["with"]["path"] == "build/vendor-evidence-locked"


@pytest.mark.parametrize("job_name", ["resolve-vendor", "tooling", "test-locked"])
def test_pinned_parent_staging_command_and_real_payload(tmp_path, job_name):
    """Execute the workflow staging command against real lock bytes."""
    parent_tool = ROOT / ".vendor-sync-tools/vendor_stage.py"
    if not parent_tool.is_file():
        pytest.skip("pinned parent checkout is supplied by Tooling smoke")
    assert not (ROOT / "tool/stage_vendor_evidence.py").exists()
    _copy_snapshot(tmp_path)
    steps = _workflow()["jobs"][job_name]["steps"]
    staging = next(step for step in steps if step.get("name") == "Stage canonical vendor evidence")
    assert staging["if"] == "always()"
    command = staging["run"].replace(
        ".vendor-sync-tools/vendor_stage.py", shlex.quote(str(parent_tool))
    ).replace("python -S ", shlex.quote(sys.executable) + " -S ")
    syntax = subprocess.run(["bash", "-n"], input=command, text=True, capture_output=True)
    assert syntax.returncode == 0, syntax.stderr
    result = subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", command],
        cwd=tmp_path,
        env=os.environ,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    output = Path(json.loads(result.stdout)["output"])
    evidence = json.loads((output / "vendor-evidence.json").read_text(encoding="utf-8"))
    lock_members = {"vendor.lock.json", *[entry["destination"] for entry in _lock_entries(tmp_path)]}
    assert set(evidence["locked"]) == set(evidence["candidate"]) == lock_members
    assert evidence["kind"] == "locked"
    assert evidence["legacy"] == []
    assert evidence["runtime"] == []
    members = lock_members
    assert set(evidence["sha256"]) == members
    assert {p.relative_to(output).as_posix() for p in output.rglob("*") if p.is_file()} == members | {
        "vendor-evidence.json"
    }
    for member in members:
        data = (output / member).read_bytes()
        assert data == (tmp_path / member).read_bytes()
        assert hashlib.sha256(data).hexdigest() == evidence["sha256"][member]


def test_retired_ironmate_sources_do_not_follow_deleted_main_paths():
    entries = [e for e in _lock_entries() if e["repository"] == "myon-bioinformatics/Ironmate"]
    assert {e["source"] for e in entries} == {"LICENSE"}
    assert all(e["ref"] == e["commit"] for e in entries)
