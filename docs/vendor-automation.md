# Public vendor placement in CI

Ordinary push/PR CI verifies checked-in vendor bytes against `vendor.lock.json`,
recreates the allowlisted files from their pinned upstream commits, and runs the
existing Python suite. Checkout credentials are not persisted. There is no
scheduled upstream promotion, repository writeback, or legacy provenance projection.

`vendor.lock.json` (schema `vendor-lock/1`) is the only provenance record: each
entry carries `repository`, full 40-hex `ref`/`commit`, `source`, `destination`,
`blob_sha`, and `sha256`. CI checks the lock with the parent repository's
`vendor_sync.py check --manifest vendor.lock.json`, checked out from
`myon-bioinformatics/myon-bioinformatics` at
`1eda992aa6fa31a902e2c06428e53ab17e8fe3c1`.

The `resolve-vendor` job materializes locked files once per run and publishes a
verified vendor snapshot artifact. The primary `tooling` job downloads that
snapshot before pytest. A separate `test-locked` job exercises the checked-in
baseline without downloading the snapshot.

Canonical evidence staging uses the parent's `vendor_stage.py` at the same pin.
Locked evidence uses a `locked-` artifact prefix and is retained on failure.

ALM agents can reproduce verification in a disposable checkout:

```bash
git clone https://github.com/myon-bioinformatics/myon-bioinformatics.git .vendor-sync-tools
git -C .vendor-sync-tools checkout --detach 1eda992aa6fa31a902e2c06428e53ab17e8fe3c1
python -S .vendor-sync-tools/vendor_sync.py check --manifest vendor.lock.json
python -S .vendor-sync-tools/vendor_sync.py materialize --manifest vendor.lock.json
python -S .vendor-sync-tools/vendor_sync.py check --manifest vendor.lock.json
```

Run the existing Python suite with uv after verification: `uv run pytest -v`.

## Retired Ironmate sources

Ironmate #81 removed the upstream metadata prototypes. The Ironmate `LICENSE`
entry uses its verified full commit as `ref`. Promotion and automatic upstream
update jobs were removed; lock entries change only through reviewed commits.
