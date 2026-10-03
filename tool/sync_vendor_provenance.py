"""Explicit legacy-provenance projection from the verified shared vendor lock.

No source acquisition, importing candidate modules, tokens or repository writes.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {('myon-bioinformatics/Ironmate', 'LICENSE', 'tool/vendor/LICENSE'),
 ('myon-bioinformatics/Ironmate',
  'repository_metadata_contract.py',
  'tool/vendor/repository_metadata_contract.py'),
 ('myon-bioinformatics/Ironmate',
  'repository_metadata_generator.py',
  'tool/vendor/repository_metadata_generator.py')}


def records(root):
    lock = json.loads((root / "vendor.lock.json").read_text(encoding="utf-8"))
    if lock["schema"] != "vendor-lock/1":
        raise ValueError("unsupported vendor lock")
    files = lock["files"]
    if len(files) != len(EXPECTED) or {(e["repository"], e["source"], e["destination"]) for e in files} != EXPECTED:
        raise ValueError("unexpected source or destination")
    by_destination = {e["destination"]: e for e in files}
    for e in files:
        if e["ref"] != "refs/heads/main" or not re.fullmatch(r"[0-9a-f]{40}", e["commit"]):
            raise ValueError("invalid source identity")
        data = (root / e["destination"]).read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if blob != e["blob_sha"] or hashlib.sha256(data).hexdigest() != e["sha256"]:
            raise ValueError("locked bytes mismatch: " + e["destination"])
    return by_destination


def project(root):
    entries = records(root)  # Verify every source/LICENSE before writing any metadata.
    record = json.loads((root / "tool/vendor/provenance.json").read_text(encoding="utf-8"))
    selected = [entries["tool/vendor/" + name] for name in record["files"]]
    if len({e["commit"] for e in selected}) != 1:
        raise ValueError("grouped provenance requires one source commit")
    record["source_commit"] = selected[0]["commit"]
    for name in record["files"]:
        entry = entries["tool/vendor/" + name]
        record["files"][name] = {"source_path": entry["source"], "git_blob_sha": entry["blob_sha"], "sha256": entry["sha256"]}
    (root / "tool/vendor/provenance.json").write_text(
        json.dumps(record, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    try:
        project(ROOT)
    except (ValueError, KeyError, OSError) as error:
        print("vendor-provenance: " + str(error), file=sys.stderr)
        raise SystemExit(2)
