# Contract compatibility policy

## Version lanes

`contract/v1` remains available and CI-validated while it is supported.

A future breaking contract starts in a separate `contract/v2` directory.
Creating v2 does not rewrite or silently repurpose v1.

During a migration period, CI SHOULD validate supported version lanes in
parallel. Downstream consumers can remain pinned to v1 until they explicitly
adopt v2.

Deprecation of a contract lane must be documented before its CI coverage or
published assets are removed.
