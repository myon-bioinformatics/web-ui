import re
import shutil

import pytest

from tool.tooling_meta import collect


def test_required_github_tooling_is_visible():
    assert shutil.which("git")
    assert shutil.which("gh")


def test_advisory_metadata_contains_repository_sha():
    metadata = collect()
    sha = metadata["repository"]["sha"]
    short_sha = metadata["repository"]["short_sha"]
    assert re.fullmatch(r"[0-9a-f]{40}", sha)
    assert re.fullmatch(r"[0-9a-f]{8}", short_sha)
    assert sha.startswith(short_sha)


def test_stagehand_v4_python_surface():
    stagehand = pytest.importorskip("stagehand")
    assert hasattr(stagehand, "Stagehand") or hasattr(stagehand, "AsyncStagehand")
