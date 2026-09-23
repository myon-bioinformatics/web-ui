"""Exact PNG visual-regression checker for deterministic Chromium captures.

Baseline files live under tests/visual-baseline/. When a baseline is absent,
candidate mode reports it without failing. Pass --require-baseline to make
missing or changed screenshots fail.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if not data.startswith(PNG_SIGNATURE) or len(data) < 24:
        raise ValueError(f"{path} is not a valid PNG")
    return struct.unpack(">II", data[16:24])


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compare(candidate_dir: Path, baseline_dir: Path, require_baseline: bool) -> int:
    candidates = sorted(candidate_dir.glob("web-ui-*.png"))
    if not candidates:
        print("no candidate screenshots found", file=sys.stderr)
        return 2

    failed = False
    report = []
    for candidate in candidates:
        baseline = baseline_dir / candidate.name
        item = {
            "name": candidate.name,
            "candidate_sha256": digest(candidate),
            "candidate_size": png_size(candidate),
        }
        if not baseline.exists():
            item["status"] = "missing-baseline"
            failed = failed or require_baseline
        else:
            item["baseline_sha256"] = digest(baseline)
            item["baseline_size"] = png_size(baseline)
            item["status"] = "match" if item["candidate_sha256"] == item["baseline_sha256"] else "changed"
            failed = failed or item["status"] == "changed"
        report.append(item)

    print(json.dumps(report, indent=2))
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-dir", type=Path, default=Path("."))
    parser.add_argument("--baseline-dir", type=Path, default=Path("tests/visual-baseline"))
    parser.add_argument("--require-baseline", action="store_true")
    args = parser.parse_args()
    return compare(args.candidate_dir, args.baseline_dir, args.require_baseline)


if __name__ == "__main__":
    raise SystemExit(main())
