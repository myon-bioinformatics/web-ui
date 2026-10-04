"""Consumer projection, canonical ownership, and standalone JSON regressions."""
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from tool import tooling_meta

ROOT = Path(__file__).resolve().parents[1]
canonical = tooling_meta.canonical


@pytest.mark.parametrize("partial", [False, True])
def test_partial_or_empty_tooling_omits_unavailable_keys(monkeypatch, partial):
    monkeypatch.setattr(canonical.platform, "python_version", lambda: "3.12.8" if partial else "invalid")
    probes = []

    def run(argv, **kwargs):
        probes.append(argv)
        assert kwargs["shell"] is False
        assert kwargs["timeout"] == 5.0
        assert argv[1:] == ["--version"]
        return SimpleNamespace(returncode=0, stdout="git version 2.45.1\n", stderr="")

    monkeypatch.setattr(canonical.shutil, "which", lambda name: "git-fixture" if partial and name == "git" else None)
    monkeypatch.setattr(canonical.subprocess, "run", run)

    def package(name):
        if partial and name == "pytest":
            return "9.0.0"
        raise canonical.importlib_metadata.PackageNotFoundError(name)

    monkeypatch.setattr(canonical.importlib_metadata, "version", package)
    result = tooling_meta.collect()
    assert set(result) == {"generated_at_utc", "runtime", "commands", "packages"}
    assert result["runtime"] == ({"python": "3.12.8"} if partial else {})
    assert result["commands"] == ({"git": "2.45.1"} if partial else {})
    assert result["packages"] == ({"pytest": "9.0.0"} if partial else {})
    assert probes == ([["git-fixture", "--version"]] if partial else [])
    assert json.loads(json.dumps(result)) == result
    assert all(isinstance(v, str) and v != "unknown" for group in ("runtime", "commands", "packages") for v in result[group].values())


def test_consumer_only_requests_allowlisted_observations(monkeypatch):
    calls = []

    def collect(**kwargs):
        calls.append(kwargs)
        return {"python": "3.12.8", "git": "2.45.1", "gh": "2.60.0",
                "node": "22.0.0", "npx": "10.0.0", "pytest": "9.0.0", "stagehand": "4.1.0"}

    monkeypatch.setattr(canonical, "collect_portable_tooling", collect)
    result = tooling_meta.collect()
    assert calls == [{"include_python": True, "commands": ("git", "gh", "node", "npx"),
                      "distributions": (("pytest", "pytest"), ("stagehand", "stagehand"))}]
    assert result["runtime"] == {"python": "3.12.8"}
    assert result["commands"] == {"git": "2.45.1", "gh": "2.60.0", "node": "22.0.0", "npx": "10.0.0"}
    assert result["packages"] == {"pytest": "9.0.0", "stagehand": "4.1.0"}


@pytest.mark.parametrize("collision", ["runtime", "command", "package", "duplicate-command"])
def test_duplicate_canonical_owners_fail_before_probing(monkeypatch, collision):
    def unexpected(*args, **kwargs):
        pytest.fail("collision must fail before observations")

    monkeypatch.setattr(canonical.platform, "python_version", unexpected)
    monkeypatch.setattr(canonical, "observe_command_version", unexpected)
    monkeypatch.setattr(canonical, "observe_package_version", unexpected)
    if collision == "duplicate-command":
        monkeypatch.setattr(tooling_meta, "COMMANDS", ("git", "git"))
    else:
        key = {"runtime": "python", "command": "git", "package": "pytest"}[collision]
        monkeypatch.setattr(tooling_meta, "DISTRIBUTIONS", tooling_meta.DISTRIBUTIONS + ((key, "other"),))
    with pytest.raises(ValueError, match="exactly one canonical source"):
        tooling_meta.collect()


@pytest.mark.parametrize("key", ["python", "git", "pytest"])
def test_caller_cannot_overwrite_canonical_keys_even_if_unavailable(monkeypatch, tmp_path, key):
    def unexpected(*args, **kwargs):
        pytest.fail("overlap must fail before checkout or tooling observations")

    monkeypatch.setattr(canonical, "git", unexpected)
    monkeypatch.setattr(canonical, "collect_portable_tooling", unexpected)
    with pytest.raises(ValueError, match="caller tooling overlaps canonical tooling: " + key):
        canonical.record_from_checkout(tmp_path, "myon-bioinformatics/web-ui", tooling={key: "unknown"},
                                       include_python_tooling=True, tooling_commands=tooling_meta.COMMANDS,
                                       tooling_distributions=tooling_meta.DISTRIBUTIONS)


def test_standalone_json_is_stdlib_only_and_does_not_need_checkout(tmp_path):
    env = {**os.environ, "PATH": str(tmp_path), "PYTHONPATH": ""}
    result = subprocess.run([sys.executable, "-S", str(ROOT / "tool/tooling_meta.py")],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    record = json.loads(result.stdout)
    assert set(record) == {"generated_at_utc", "runtime", "commands", "packages"}
    assert record["runtime"] == {"python": canonical.platform.python_version()}
    assert record["commands"] == {}
    assert record["packages"] == {}
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("failure", ["nonzero", "malformed", "timeout", "oserror"])
def test_failed_canonical_observations_are_omitted(monkeypatch, failure):
    monkeypatch.setattr(canonical.platform, "python_version", lambda: "3.12.8")
    monkeypatch.setattr(canonical.shutil, "which", lambda name: name)

    def run(argv, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
        if failure == "oserror":
            raise OSError("private path must not escape")
        return SimpleNamespace(returncode=1 if failure == "nonzero" else 0,
                               stdout="private malformed output" if failure == "malformed" else "git version 2.45.1",
                               stderr="")

    monkeypatch.setattr(canonical.subprocess, "run", run)
    monkeypatch.setattr(canonical.importlib_metadata, "version", lambda _: "private malformed package")
    first = tooling_meta.collect()
    second = tooling_meta.collect()
    for record in (first, second):
        assert record["runtime"] == {"python": "3.12.8"}
        assert record["commands"] == record["packages"] == {}
        del record["generated_at_utc"]
    assert json.dumps(first) == json.dumps(second)
