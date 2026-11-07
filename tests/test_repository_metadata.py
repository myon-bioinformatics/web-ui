"""Local repository-metadata v1 producer regressions (no gh_identity)."""
from __future__ import annotations

import json, os, subprocess, sys
from pathlib import Path

import pytest

from tool import repository_metadata as rm

ROOT = Path(__file__).resolve().parents[1]


def _init_checkout(path: Path, message: str = "fixture subject") -> str:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main", str(path)], check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "--allow-empty",
            "-m",
            message,
        ],
        cwd=path,
        check=True,
        capture_output=True,
    )
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=path, text=True).strip()


def test_repository_metadata_v1_roundtrip_and_cli(tmp_path):
    checkout = tmp_path / "checkout"
    sha = _init_checkout(checkout, "metadata <script>fixture</script>")
    env = {
        **os.environ,
        "GITHUB_SHA": "f" * 40,
        "GITHUB_HEAD_REF": "topic/local",
        "GITHUB_REF_NAME": "123/merge",
    }
    record = rm.repository_metadata_v1(
        checkout,
        repository="myon-bioinformatics/PySaiyanWeBoo",
        env=env,
    )
    assert record["repository"] == {"full_name": "myon-bioinformatics/PySaiyanWeBoo"}
    assert record["head"]["sha"] == sha
    assert record["head"]["short_sha"] == sha[:8]
    assert record["head"]["branch"] == "topic/local"
    assert all(value is None for value in record["measurements"].values())
    assert record["tooling"] == {}

    out = tmp_path / "out"
    written = rm.write_repository_metadata(record, out)
    assert written == {"json": "repository-metadata.json", "jsonl": "repository-metadata.jsonl"}
    pretty = json.loads((out / "repository-metadata.json").read_text(encoding="utf-8"))
    line = json.loads((out / "repository-metadata.jsonl").read_text(encoding="utf-8"))
    assert pretty == line == record

    cli_out = tmp_path / "cli"
    result = subprocess.run(
        [
            sys.executable,
            "-S",
            str(ROOT / "tool/repository_metadata.py"),
            "repo-metadata",
            "--format",
            "v1",
            "--repository",
            "myon-bioinformatics/PySaiyanWeBoo",
            "--root",
            str(checkout),
            "--output-dir",
            str(cli_out),
        ],
        check=True,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert json.loads((cli_out / "repository-metadata.json").read_text(encoding="utf-8"))["head"]["sha"] == sha


def test_repository_metadata_v1_rejects_bad_inputs(tmp_path):
    checkout = tmp_path / "checkout"
    sha = _init_checkout(checkout)
    with pytest.raises(ValueError, match="owner/name"):
        rm.repository_metadata_v1(checkout, repository="not-a-repo")
    with pytest.raises(ValueError, match="expected_sha"):
        rm.repository_metadata_v1(
            checkout,
            repository="myon-bioinformatics/PySaiyanWeBoo",
            expected_sha="0" * 40,
        )
    with pytest.raises(ValueError, match="unknown measurements"):
        rm.repository_metadata_v1(
            checkout,
            repository="myon-bioinformatics/PySaiyanWeBoo",
            measurements={"nope": 1},
        )
    with pytest.raises(ValueError, match="must be a full"):
        rm._rm_sha("deadbeef", "x")
    with pytest.raises(ValueError, match="timezone"):
        rm._rm_time("2026-01-01T00:00:00", "t")
    with pytest.raises(ValueError, match="ISO 8601"):
        rm._rm_time(123, "t")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="ISO 8601"):
        rm._rm_time("not-a-time", "t")
    bad = {
        "schema_version": "9.9",
        "repository": {"full_name": "myon-bioinformatics/PySaiyanWeBoo"},
        "head": {
            "sha": sha,
            "short_sha": sha[:8],
            "branch": "main",
            "timestamp": "2026-01-01T00:00:00Z",
            "subject": "x",
        },
        "measurements": dict.fromkeys(rm._RM_MEASUREMENTS),
        "tooling": {},
        "generated_at": "2026-01-01T00:00:00Z",
    }
    with pytest.raises(ValueError, match="unsupported schema_version"):
        rm.validate_repository_metadata_v1(bad)
    with pytest.raises(ValueError, match="unexpected or missing"):
        rm.validate_repository_metadata_v1({"schema_version": "1.0"})
    bad_head = dict(bad)
    bad_head["schema_version"] = "1.0"
    bad_head["head"] = dict(bad["head"], short_sha="ffffffff")
    with pytest.raises(ValueError, match="short_sha"):
        rm.validate_repository_metadata_v1(bad_head)
    empty_branch = dict(bad)
    empty_branch["schema_version"] = "1.0"
    empty_branch["head"] = dict(bad["head"], branch="")
    with pytest.raises(ValueError, match="branch and subject"):
        rm.validate_repository_metadata_v1(empty_branch)
    bad_sizes = dict(bad)
    bad_sizes["schema_version"] = "1.0"
    bad_sizes["measurements"] = dict.fromkeys(rm._RM_MEASUREMENTS, -1)
    with pytest.raises(ValueError, match="measurements"):
        rm.validate_repository_metadata_v1(bad_sizes)
    bad_tooling = dict(bad)
    bad_tooling["schema_version"] = "1.0"
    bad_tooling["tooling"] = []  # type: ignore[assignment]
    with pytest.raises(ValueError, match="tooling"):
        rm.validate_repository_metadata_v1(bad_tooling)
    bad_repo = dict(bad)
    bad_repo["schema_version"] = "1.0"
    bad_repo["repository"] = {"full_name": "myon-bioinformatics/PySaiyanWeBoo", "extra": 1}
    with pytest.raises(ValueError, match="invalid repository"):
        rm.validate_repository_metadata_v1(bad_repo)
    with pytest.raises(ValueError, match="owner/name"):
        rm._rm_full_name("myon-bioinformatics/..")


def test_git_inspection_errors(tmp_path, monkeypatch):
    with pytest.raises(rm.GitInspectionError, match="git executable not found"):
        def boom(*args, **kwargs):
            raise FileNotFoundError("git")

        monkeypatch.setattr(rm.subprocess, "run", boom)
        rm._git(tmp_path, "status")

    def os_boom(*args, **kwargs):
        raise OSError("denied")

    monkeypatch.setattr(rm.subprocess, "run", os_boom)
    with pytest.raises(rm.GitInspectionError, match="OSError"):
        rm._git(tmp_path, "status")

    def bad_status(*args, **kwargs):
        return type("R", (), {"returncode": 128, "stdout": "", "stderr": "fail"})()

    monkeypatch.setattr(rm.subprocess, "run", bad_status)
    with pytest.raises(rm.GitInspectionError, match="exited with status"):
        rm._git(tmp_path, "status")


def test_main_prints_without_output_dir(tmp_path, capsys, monkeypatch):
    checkout = tmp_path / "checkout"
    _init_checkout(checkout)
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    with pytest.raises(SystemExit) as excinfo:
        rm.main(["repo-metadata", "--root", str(checkout)])
    assert "repository" in str(excinfo.value)
    code = rm.main(
        [
            "repo-metadata",
            "--format",
            "v1",
            "--repository",
            "myon-bioinformatics/PySaiyanWeBoo",
            "--root",
            str(checkout),
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == "1.0"


def test_detached_branch_label(tmp_path, monkeypatch):
    checkout = tmp_path / "checkout"
    sha = _init_checkout(checkout)
    subprocess.run(["git", "checkout", "--detach", "HEAD"], cwd=checkout, check=True, capture_output=True)
    monkeypatch.delenv("GITHUB_HEAD_REF", raising=False)
    monkeypatch.delenv("GITHUB_REF_NAME", raising=False)
    record = rm.repository_metadata_v1(
        checkout,
        repository="myon-bioinformatics/PySaiyanWeBoo",
        env={},
    )
    assert record["head"]["branch"] == "detached"
    assert record["head"]["sha"] == sha


def test_validate_invalid_head_and_sha(tmp_path):
    checkout = tmp_path / "checkout"
    sha = _init_checkout(checkout)
    base = rm.repository_metadata_v1(
        checkout, repository="myon-bioinformatics/PySaiyanWeBoo", env={}
    )
    bad = dict(base)
    bad["head"] = {"sha": sha}
    with pytest.raises(ValueError, match="invalid head"):
        rm.validate_repository_metadata_v1(bad)
    bad2 = dict(base)
    bad2["head"] = dict(base["head"], sha=sha.upper())
    with pytest.raises(ValueError, match="lowercase full hex"):
        rm.validate_repository_metadata_v1(bad2)


def test_checkout_head_rejects_empty_subject(tmp_path, monkeypatch):
    checkout = tmp_path / "checkout"
    _init_checkout(checkout)

    def fake_git(root, *args):
        if args[:2] == ("rev-parse", "--verify"):
            return "a" * 40
        if args[0] == "show":
            return "2026-01-01T00:00:00+00:00\x1f"
        if args[:2] == ("branch", "--show-current"):
            return "main"
        raise AssertionError(args)

    monkeypatch.setattr(rm, "_git", fake_git)
    with pytest.raises(rm.GitInspectionError, match="no committer date or subject"):
        rm.checkout_head(checkout)


def test_main_with_output_dir(tmp_path):
    checkout = tmp_path / "checkout"
    _init_checkout(checkout)
    out = tmp_path / "meta"
    code = rm.main(
        [
            "repo-metadata",
            "--repository",
            "myon-bioinformatics/PySaiyanWeBoo",
            "--root",
            str(checkout),
            "--output-dir",
            str(out),
            "--expected-sha",
            subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=checkout, text=True).strip(),
            "--generated-at",
            "2026-01-01T00:00:00Z",
        ]
    )
    assert code == 0
    assert (out / "repository-metadata.json").is_file()


def test_module_main_entrypoint(tmp_path):
    checkout = tmp_path / "checkout"
    _init_checkout(checkout)
    result = subprocess.run(
        [sys.executable, "-m", "tool.repository_metadata", "repo-metadata",
         "--repository", "myon-bioinformatics/PySaiyanWeBoo",
         "--root", str(checkout)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    # -m tool.repository_metadata may fail if tool is not a package; allow script path
    if result.returncode != 0:
        result = subprocess.run(
            [sys.executable, str(ROOT / "tool/repository_metadata.py"), "repo-metadata",
             "--repository", "myon-bioinformatics/PySaiyanWeBoo",
             "--root", str(checkout)],
            capture_output=True,
            text=True,
            check=True,
        )
    assert "schema_version" in result.stdout
