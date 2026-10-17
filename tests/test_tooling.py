import json
import os
from pathlib import Path
import subprocess
import sys
import shutil

import pytest

from tool.web_ui_tooling_meta import collect


def _locked(destination):
    root = Path(__file__).resolve().parents[1]
    lock = json.loads((root / "vendor.lock.json").read_text(encoding="utf-8"))
    return next(e for e in lock["files"] if e["destination"] == destination)


def test_required_github_tooling_is_visible():
    assert shutil.which("git")
    assert shutil.which("gh")


ROOT = Path(__file__).resolve().parents[1]


def test_canonical_repository_metadata_and_separate_tooling(tmp_path, monkeypatch):
    # Use a real isolated checkout to prove the producer -> JSON/JSONL -> JS path.
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(checkout)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
         "commit", "--allow-empty", "-m", "metadata <script>fixture</script>"],
        cwd=checkout, check=True, capture_output=True,
    )
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=checkout, text=True).strip()
    env = {**os.environ, "GITHUB_SHA": "f" * 40, "GITHUB_HEAD_REF": "topic/canonical",
           "GITHUB_REF_NAME": "123/merge"}
    output = tmp_path / "metadata"
    subprocess.run(
        [sys.executable, "-S", str(ROOT / "tool/vendor/gh_identity.py"), "repo-metadata",
         "--format", "v1", "--repository", "myon-bioinformatics/web-ui", "--root", str(checkout),
         "--output-dir", str(output)],
        check=True, env=env, capture_output=True, text=True,
    )
    record_path = output / "repository-metadata.json"
    record = json.loads(record_path.read_text())
    assert record == json.loads((output / "repository-metadata.jsonl").read_text())
    assert record["repository"] == {"full_name": "myon-bioinformatics/web-ui"}
    assert record["head"]["sha"] == sha
    assert record["head"]["short_sha"] == sha[:8]
    assert record["head"]["branch"] == "topic/canonical"
    assert all(value is None for value in record["measurements"].values())
    subprocess.run(
        ["node", str(ROOT / "tests/repository_diagnostics.node.js"), str(record_path)],
        check=True, capture_output=True, text=True,
    )

    # Advisory collection reports tooling versions only; never head/branch identity.
    from tool import web_ui_tooling_meta
    def fake_tool_versions(commands, *, include_python=False, **_):
        observed = {command: "1.2.3" for command in commands}
        if include_python:
            observed["python"] = "1.2.3"
        return observed
    monkeypatch.setattr(web_ui_tooling_meta.canonical, "tool_versions", fake_tool_versions)
    monkeypatch.setattr(web_ui_tooling_meta, "observe_package_version", lambda _: "4.1.0")
    metadata = collect()
    assert set(metadata) == {"generated_at_utc", "runtime", "commands", "packages"}
    assert metadata["runtime"]["python"]
    assert set(metadata["packages"]) == {"pytest", "stagehand"}


def test_stagehand_v4_python_surface():
    stagehand = pytest.importorskip("stagehand")
    assert hasattr(stagehand, "Stagehand") or hasattr(stagehand, "AsyncStagehand")
