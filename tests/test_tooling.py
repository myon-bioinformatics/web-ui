import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import shutil

import pytest

from tool.tooling_meta import collect


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
        [sys.executable, "-S", str(ROOT / "tool/vendor/repository_metadata_generator.py"),
         "--repository", "myon-bioinformatics/web-ui", "--root", str(checkout),
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

    # Advisory collection can probe git --version, but never head/branch identity.
    from tool import tooling_meta
    probes = []
    def observe(command, *args):
        probes.append((command, args))
        return "fixture version"
    monkeypatch.setattr(tooling_meta, "_command_version", observe)
    metadata = collect()
    assert set(metadata) == {"generated_at_utc", "runtime", "commands", "packages"}
    assert metadata["runtime"]["python"]
    assert set(metadata["packages"]) == {"pytest", "stagehand"}
    assert probes == [(name, ("--version",)) for name in ("git", "gh", "node", "npx")]


def test_canonical_vendor_provenance():
    vendor = ROOT / "tool/vendor"
    provenance = json.loads((vendor / "provenance.json").read_text())
    assert provenance["source_repository"] == "myon-bioinformatics/Ironmate"
    assert provenance["source_commit"] == "0aee64da2f8d0119a3ef9b955e5c3818f28aaf92"
    assert set(provenance["files"]) == {
        "repository_metadata_contract.py", "repository_metadata_generator.py", "LICENSE"
    }
    for name, info in provenance["files"].items():
        data = (vendor / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == info["sha256"]
        assert hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest() == info["git_blob_sha"]


def test_stagehand_v4_python_surface():
    stagehand = pytest.importorskip("stagehand")
    assert hasattr(stagehand, "Stagehand") or hasattr(stagehand, "AsyncStagehand")
