# Deployment reconciliation — November 15, 2026

The starting GitHub demo branch was commit `0ae06b63bb240313b2d23a1a9623100f75512a86`. The running Windows Studio had newer code that was missing from that branch. This package recovers that deployed implementation, adds review documentation and includes the optional native graphics adapter in a portable location.

## What was reconciled

- Recovered 30 modified tracked files and 37 additional files from the deployed Studio tree: Fluent execution and API inspection, thermal/domain setup, chat/context/recovery changes, frontend changes, examples and tests.
- Rebuilt both frontends. All seven generated files matched the live deployment by SHA-256.
- Compared the separate solver worker source. Two files lagged the Studio copy: `mechanical/opencode_connection.py` and `fluent/program.py`. The worker reconciliation record documents their hashes and whether each changed. Updates hold the existing exclusive worker lock, check the expected original hash, compile the replacement and retain a backup.
- Recorded fresh file hashes in [deployment-audit.json](evidence/deployment-audit.json). Runtime source/assets and documentation are separate audit categories: the package adds documentation that was not part of the running process.
- Included `integrations/fluent_post/server.py`, a portable copy of the live external adapter. Only path/configuration resolution differs; six mocked safeguard tests cover the packaged copy. The running host continues using its original adapter path. Its original and packaged digests are recorded separately.

No app restart, new solver run, environment upgrade or deletion of saved CAD/results was needed. Existing chat sessions remain on the running process. No credentials or private runtime database were placed in Git.

## Meaning of a match

File hashes establish that the checked-in runtime source matches the deployed files and that the frontend can be reproduced byte for byte. They do not introspect every already-imported Python object in the running process. The live browser check separately establishes that the authenticated app imports and renders the supplied CAD. The recorded historical solver results are identified by date in [Verification](VERIFICATION.md).

Private settings, logs, installed environments, generated assets and live CAD databases are intentionally outside Git. Frontend assets are reproducible from `package-lock.json`; both build commands are in [Setup](SETUP.md). The audit lists file paths relative to the app/worker, without logins or private account directories.

## Operational handoff

Use [VM_HOSTING.md](../VM_HOSTING.md) for the current private Windows deployment. Studio is launched by the user's Startup shortcut rather than a machine-wide service; the host must be awake and signed in. The app and OpenCode use distinct ports. Tailscale reachability and the application login are both required.

For later updates:

1. Commit intended source and run the relevant checks/builds.
2. Verify there are no active or uncertain solver jobs before updating worker files or restarting Studio.
3. Deploy worker changes with `scripts/deploy-worker.py`, selecting `--solver fluent` when applicable.
4. Stop only the verified Studio process, deploy using `scripts/deploy-studio.py`, and let its configured launcher restart it.
5. Verify login enforcement, import behavior and the new source/build hashes. Retain job data and the previous revision for recovery.

The existing deployment script does not provide a general rollback manager or automatically resolve uncertain jobs. Do not treat a lost web response as permission to start another solver process.
