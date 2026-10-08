#!/usr/bin/env python3
"""Stage canonical vendor evidence and the explicit legacy projection for CI."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

LEGACY = ("tool/vendor/provenance.json",)

def stage(root, kind, output_name, *, runner=subprocess.run):
    root = Path(root).resolve()
    cmd = [sys.executable, "-S", str(root / ".vendor-sync-tools/vendor_sync.py"),
           "evidence", "--manifest", "vendor.lock.json"]
    if kind == "candidate" and (root / "vendor-promotion.json").is_file():
        cmd += ["--runtime-evidence", "vendor-promotion.json"]
    result = runner(cmd, capture_output=True, text=True, check=True)
    evidence = json.loads(result.stdout)
    if evidence.get("schema") != "vendor-evidence/1":
        raise ValueError("unsupported evidence schema")
    members = evidence[kind] + evidence["runtime"] + list(LEGACY)
    output = (root / output_name).resolve()
    if not output.is_relative_to(root) or output == root or output.exists():
        raise ValueError("invalid or existing output directory")
    for member in members:
        path = Path(member)
        source = (root / path).resolve()
        if path.is_absolute() or ".." in path.parts or not source.is_relative_to(root) or not source.is_file():
            raise ValueError("unsafe or missing evidence member: " + member)
    output.mkdir(parents=True)
    for member in members:
        target = output / member
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / member, target)
    (output / "vendor-evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")



def main():
    p = argparse.ArgumentParser()
    p.add_argument("--kind", choices=("candidate", "locked"), required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    stage(Path.cwd(), args.kind, args.output)

if __name__ == "__main__":
    main()
