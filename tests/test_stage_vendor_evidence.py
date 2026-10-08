import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "tool" / "stage_vendor_evidence.py"
spec = importlib.util.spec_from_file_location("stage_vendor_evidence", SOURCE)
stage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage)

def setup(root, *, receipt=False):
    (root / ".vendor-sync-tools").mkdir()
    (root / "vendor.lock.json").write_text("{}")
    (root / "vendor").mkdir()
    (root / "vendor" / "one.py").write_text("one")
    (root / "tool" / "vendor").mkdir(parents=True)
    (root / "tool" / "vendor" / "provenance.json").write_text("{}")
    if receipt:
        (root / "vendor-promotion.json").write_text("{}")

def runner(cmd, **kwargs):
    runtime = ["vendor-promotion.json"] if "--runtime-evidence" in cmd else []
    return SimpleNamespace(stdout=json.dumps({"schema": "vendor-evidence/1",
        "locked": ["vendor.lock.json", "vendor/one.py"],
        "candidate": ["vendor.lock.json", "vendor/one.py"], "runtime": runtime}))

@pytest.mark.parametrize("kind,receipt,expected", [
    ("locked", False, False), ("candidate", False, False), ("candidate", True, True)])
def test_staging_membership(tmp_path, kind, receipt, expected):
    setup(tmp_path, receipt=receipt)
    stage.stage(tmp_path, kind, "build/out", runner=runner)
    evidence = json.loads((tmp_path / "build/out/vendor-evidence.json").read_text())
    assert ("vendor-promotion.json" in evidence["runtime"]) == expected
    assert (tmp_path / "build/out/vendor/one.py").read_text() == "one"
    assert (tmp_path / "build/out/tool/vendor/provenance.json").exists()

def test_existing_output_rejected(tmp_path):
    setup(tmp_path)
    (tmp_path / "out").mkdir()
    with pytest.raises(ValueError, match="existing"):
        stage.stage(tmp_path, "locked", "out", runner=runner)

def test_unsafe_member_rejected(tmp_path):
    setup(tmp_path)
    def unsafe(cmd, **kwargs):
        return SimpleNamespace(stdout=json.dumps({"schema": "vendor-evidence/1",
            "locked": ["../escape"], "candidate": [], "runtime": []}))
    with pytest.raises(ValueError, match="unsafe"):
        stage.stage(tmp_path, "locked", "out", runner=unsafe)
    assert not (tmp_path / "out").exists()
