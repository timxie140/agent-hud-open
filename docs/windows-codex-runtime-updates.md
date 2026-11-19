# Codex updates while Windows HUD remains open

Windows Store installs Codex into a versioned package directory. Updating Codex
can remove that directory while HUD is still running. A path discovered only
when HUD starts is therefore not a stable message transport.

The previous message/start service retained `StartConfig.codex_executable` in its
queue route. After an update, creating the temporary queue app-server could fail
with Windows error 3 (path not found), surfaced to Dot as refused. Native queue
activation is a later stage and cannot repair a failure to start that server.

## Live registered-package discovery

For a current-user registered official Codex package, native `StartConfig::find`
marks the route for live discovery. Before starting each new queue or start
operation, Windows asks `FindPackagesByPackageFamily` for the official package
family and `GetPackagePathByFullName` for its current directory. The package's
manifest supplies the application entry; HUD validates the corresponding
`resources/codex.exe` stays inside that registered package.

This lookup has no process-lifetime path cache or five-minute registration TTL.
It does not scan old WindowsApps versions, use unmatched hash-cache binaries,
change execution policy, add a service, or restart HUD. An ambiguous, removed or
temporarily incomplete registered package fails closed; the next new operation
does a fresh lookup again. It does not silently switch to a PATH CLI.

Discovery provenance is explicit data, rather than inferred from a path's shape.
Saved/custom configurations default to fixed executables. Standalone CLI
discovery without a registered package keeps its existing fixed behavior.
A registered package whose CLI is temporarily unavailable at HUD startup still
keeps a live route; the missing startup path is never executed as a fallback.

Microsoft documents that the package-family lookup is scoped to the current
user: [FindPackagesByPackageFamily](https://learn.microsoft.com/en-us/windows/win32/api/appmodel/nf-appmodel-findpackagesbypackagefamily).
The head-package filter is defined in [package constants](https://learn.microsoft.com/en-us/windows/win32/appxpkg/package-constants).

## Retry boundary and identity

Only a failed `CreateProcess` with native error 2 or 3 may trigger one additional
discovery, and only before a child or protocol input exists. If discovery still
returns the same path, or the second launch fails, HUD stops. Permission errors,
job assignment, initialization, reads and mutation outcomes never trigger this
retry. The same command arguments, environment, CODEX_HOME, pipes and Windows job
assignment are retained.

After a child is created, its selected runtime is fixed. New-session creation
uses that exact executable for both `thread/start` and its later first-message
queue phase. If an update removes it between those phases, the created thread ID
and uncertain result are retained; HUD does not recreate the thread or replay
input with another runtime.

The durable attempt journal remains authoritative. Previously refused/failed,
accepted or uncertain business messages are not automatically replayed after
discovery recovers. Refreshing the runtime is not permission to retry a delivery.

## Verification boundary

Fixtures simulate updates with old files still present, missing paths, a second
concurrent update, custom routes, discovery failure and error 2/3/5 handling.
Manifest and UTF-16 buffer tests use temporary files and fake buffers, never a
real Codex profile or CLI. Native Windows CI must compile and run these tests.

The maintainer's current-user native API read can validate the installed package
without sending a message; it does not qualify the new Rust binary or a live
software update. Real acceptance must keep the same HUD process across a
controlled package-path change, use a single new maintenance message, observe
actual input, and preserve the old build and state for rollback.

Package-path refresh does not relax Desktop IPC schema or permission checks.
A genuinely changed package family or protocol still requires explicit support;
unknown schemas stay refused rather than falling through to another route.
