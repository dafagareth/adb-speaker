# Security

adb-speaker is experimental. Fixes target the current development branch; older
releases do not have a separate maintenance policy.

## Reporting

Use [GitHub private vulnerability reporting](https://github.com/dafagareth/adb-speaker/security/advisories/new)
if it is enabled. If the form is unavailable, open an issue asking for a private
contact channel, without exploit details, logs containing secrets, or credentials.
No response-time guarantee is offered.

Include the affected revision, reproduction steps, impact, and whether the issue
requires access to an authorized ADB device or the local Linux account.

## Trust boundary

Run packages from sources you trust. ADB authorization grants debugging access to
the phone; revoke that authorization when it is no longer needed. adb-speaker runs
a temporary receiver with the ADB shell's permissions, without installing an APK.

Checksums detect archive changes, not publisher identity. The receiver source
marker detects stale bundled source, not whether a DEX was built from that source.
