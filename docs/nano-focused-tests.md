# Focused test environment

Use `uv run --locked --only-group world-test --exact python -m pytest -q tests/test_world_motion.py tests/test_world_shared.py` from the repository root.

This optional profile preserves pytest and the anyio plugin used by the full environment. Node 26+ is required to exercise all 41 selected tests without skips; set PYTHONPATH=. when invoking from outside the repository.

The default dependency groups and full CI remain unchanged. This command covers only the named tests; it does not replace the complete suite, Docker or real-browser checks.

## Local reference measurement (2026-11-03)

Linux x86_64, CPython 3.12.14, Node 26.13.0. Full source: 3f83a06266303d5067890f3cad5ff680d9da43b0. Three new environments per profile, shared uv cache, alternating full/nano order. Same test identities/results, no skips, same plugin and common package versions. 41 tests passed per run.

Full to focused installed distributions: 25 to 8. Regular-file logical bytes after tests: 46,217,565 to 10,415,278. Excludes shared interpreter, symlinks and uv cache; includes bytecode. These measurements used an isolated explicitly pinned installation before this group was introduced, so they are reference values, not a measurement of the current lock command.

Install timing was not a fair cold-cache comparison (different sync/install paths and initial cache state); no installation or whole-CI speedup is claimed. Pytest-only was rejected because it dropped the anyio plugin.
