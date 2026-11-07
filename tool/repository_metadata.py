"""Local repository-metadata v1 producer (stdlib only).

Replaces the former vendored ``gh_identity.py repo-metadata --format v1``
invocation. Schema and JSON/JSONL identity path stay the Ironmate v1 contract.
"""
from __future__ import annotations

import argparse, json, os, re, subprocess, sys
from datetime import datetime, timezone; from pathlib import Path

REPOSITORY_METADATA_V1_SCHEMA = "1.0"
_RM_OWNER = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?")
_RM_NAME = re.compile(r"[A-Za-z0-9_.-]+")
_RM_SHA = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_RM_MEASUREMENTS = ("github_reported_size_bytes", "working_tree_bytes", "release_artifact_bytes")


class GitInspectionError(RuntimeError):
    """Local git inspection failed."""


def _rm_full_name(full_name: str) -> str:
    if not isinstance(full_name, str) or full_name.count("/") != 1:
        raise ValueError("repository must be owner/name")
    owner, name = full_name.split("/")
    if not _RM_OWNER.fullmatch(owner) or not _RM_NAME.fullmatch(name) or name in (".", ".."):
        raise ValueError("repository must be owner/name")
    return full_name


def _rm_sha(value: str, name: str = "sha") -> str:
    if not isinstance(value, str) or not _RM_SHA.fullmatch(value.lower()):
        raise ValueError(name + " must be a full 40- or 64-hex commit SHA")
    return value.lower()


def _rm_time(value: str, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(name + " must be an ISO 8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(name + " must be an ISO 8601 timestamp") from error
    if parsed.tzinfo is None:
        raise ValueError(name + " must include a timezone")
    return value


def _git(root: str | Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "--no-pager", "-c", "i18n.logOutputEncoding=UTF-8", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
    except FileNotFoundError as error:
        raise GitInspectionError("git executable not found") from error
    except (OSError, subprocess.SubprocessError) as error:
        raise GitInspectionError(type(error).__name__) from error
    if result.returncode != 0:
        raise GitInspectionError("git exited with status " + str(result.returncode))
    return result.stdout.strip()


def checkout_head(root: str | Path = ".") -> dict[str, object]:
    """The commit actually checked out at root (never GITHUB_SHA or other env)."""
    sha = _rm_sha(_git(root, "rev-parse", "--verify", "HEAD^{commit}"), "HEAD")
    fields = _git(root, "show", "-s", "--format=%cI%x1f%s", "HEAD").split("\x1f", 1)
    if len(fields) != 2 or not fields[1]:
        raise GitInspectionError("HEAD has no committer date or subject")
    branch = _git(root, "branch", "--show-current") or None
    return {
        "sha": sha,
        "branch": branch,
        "detached": branch is None,
        "timestamp": _rm_time(fields[0], "timestamp"),
        "subject": fields[1].splitlines()[0],
    }


def validate_repository_metadata_v1(record: dict) -> dict:
    if not isinstance(record, dict) or set(record) != {
        "schema_version",
        "repository",
        "head",
        "measurements",
        "tooling",
        "generated_at",
    }:
        raise ValueError("unexpected or missing top-level fields")
    if record["schema_version"] != REPOSITORY_METADATA_V1_SCHEMA:
        raise ValueError("unsupported schema_version")
    head = record["head"]
    if not isinstance(head, dict) or set(head) != {"sha", "short_sha", "branch", "timestamp", "subject"}:
        raise ValueError("invalid head")
    if not isinstance(head["sha"], str) or not _RM_SHA.fullmatch(head["sha"]):
        raise ValueError("sha must be lowercase full hex")
    if head["short_sha"] != head["sha"][:8]:
        raise ValueError("short_sha must be the first 8 characters of sha")
    if not head["branch"] or not head["subject"]:
        raise ValueError("branch and subject are required")
    _rm_time(head["timestamp"], "timestamp")
    _rm_time(record["generated_at"], "generated_at")
    if not isinstance(record["repository"], dict) or set(record["repository"]) != {"full_name"}:
        raise ValueError("invalid repository")
    _rm_full_name(record["repository"]["full_name"])
    sizes = record["measurements"]
    if not isinstance(sizes, dict) or set(sizes) != set(_RM_MEASUREMENTS) or any(
        value is not None and (type(value) is not int or value < 0) for value in sizes.values()
    ):
        raise ValueError("measurements must be non-negative integers or null")
    tooling = record["tooling"]
    if not isinstance(tooling, dict):
        raise ValueError("tooling values must be short version labels")
    return record


def repository_metadata_v1(
    root: str | Path = ".",
    *,
    repository: str,
    env=None,
    expected_sha: str | None = None,
    generated_at: str | None = None,
    tooling=None,
    measurements=None,
) -> dict:
    env = os.environ if env is None else env
    head = checkout_head(root)
    if expected_sha is not None and head["sha"] != _rm_sha(expected_sha, "expected_sha"):
        raise ValueError("checkout HEAD does not match expected_sha")
    branch = (
        (env.get("GITHUB_HEAD_REF") or "").strip()
        or (env.get("GITHUB_REF_NAME") or "").strip()
        or head["branch"]
        or "detached"
    )
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    sizes = dict.fromkeys(_RM_MEASUREMENTS)
    extra = set(measurements or {}) - set(_RM_MEASUREMENTS)
    if extra:
        raise ValueError("unknown measurements: " + ", ".join(sorted(extra)))
    sizes.update(measurements or {})
    return validate_repository_metadata_v1(
        {
            "schema_version": REPOSITORY_METADATA_V1_SCHEMA,
            "repository": {"full_name": _rm_full_name(repository)},
            "head": {
                "sha": head["sha"],
                "short_sha": head["sha"][:8],
                "branch": branch,
                "timestamp": head["timestamp"],
                "subject": head["subject"],
            },
            "measurements": sizes,
            "tooling": dict(tooling or {}),
            "generated_at": _rm_time(generated_at or now, "generated_at"),
        }
    )


def write_repository_metadata(record: dict, output_dir: str | Path) -> dict[str, str]:
    validate_repository_metadata_v1(record)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    pretty = json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    line = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    (output / "repository-metadata.json").write_text(pretty, encoding="utf-8")
    (output / "repository-metadata.jsonl").write_text(line, encoding="utf-8")
    return {"json": "repository-metadata.json", "jsonl": "repository-metadata.jsonl"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Emit repository-metadata v1 JSON/JSONL")
    parser.add_argument("cmd", choices=("repo-metadata",))
    parser.add_argument("--root", default=".")
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--format", choices=("v1",), default="v1")
    parser.add_argument("--expected-sha")
    parser.add_argument("--generated-at")
    parser.add_argument("--output-dir")
    ns = parser.parse_args(argv)
    if ns.cmd != "repo-metadata":  # pragma: no cover - argparse choices already enforce
        raise SystemExit("unsupported command")
    if ns.format != "v1":  # pragma: no cover - argparse choices already enforce
        raise SystemExit("only --format v1 is supported")
    if not ns.repository:
        raise SystemExit("--repository or GITHUB_REPOSITORY required")
    record = repository_metadata_v1(
        ns.root,
        repository=ns.repository,
        expected_sha=ns.expected_sha,
        generated_at=ns.generated_at,
    )
    if ns.output_dir:
        write_repository_metadata(record, ns.output_dir)
    else:
        print(json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess CLI
    raise SystemExit(main())
