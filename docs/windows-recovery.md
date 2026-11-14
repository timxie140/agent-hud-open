# Windows GUI crash recovery

This is a Windows-only supervision component, not a Codex/DSH message relay or
a Windows service. A packaged GUI launch delegates to the sibling
`agent-hud-recovery.exe`, which starts and holds the exact GUI process handle.
MCP, client-hook and demo entry points retain their existing lifecycle.

Each GUI attempt has fresh private kernel events and a random run identity.
The child verifies the monitor's executable path, same-user identity and process
creation time. It signals ready only after setup and its maintenance listener
are available. User Quit first sets the per-run stop event; the final normal
event-loop exit does so as well. Closing Settings/Statistics is not a GUI-process
exit and does not trigger recovery.

Recovery requires ready, an allowlisted native crash exit status, and no stop,
maintenance or session-ending intent. The default is at most three restarts in
ten minutes, delayed 3, 10 and 30 seconds. Intervals use monotonic time. Unknown
termination, zero exit, failed startup and hangs do not trigger restart or a kill.
Exit codes alone cannot identify every external actor; the policy is conservative,
not a claim to distinguish arbitrary forced termination with certainty.

A hidden top-level window receives session-ending messages. Query cancellation
clears its pending flag; confirmed shutdown/logoff inhibits relaunch. This does
not block Windows shutdown. No Codex, DSH, proxy or business process is stopped,
and no chat, queue, subscription or message is recreated or replayed.

## Upgrade and uninstall

Both NSIS PREINSTALL and PREUNINSTALL invoke the installed helper's
`--stop-for-update`. It validates the recorded monitor/GUI identities, requests
maintenance, and waits for both to exit. An execution failure, stale/ambiguous
identity, startup gap, inaccessible cross-session event or timeout aborts the
installer instead of killing unknown processes or replacing a running helper.

An older pre-recovery installation has no helper and therefore no monitor to
stop. All helper-enabled packages include PREUNINSTALL, so their old uninstaller
also stops recovery when invoked before a newer installer's PREINSTALL. Direct
file replacement or unrelated installers are not a supported upgrade procedure.

State and bounded rotating metadata logs live under the current user's
`AgentHUDPrivate/recovery`, keyed by install path. Per-run state is not shared
across GUI attempts; old events cannot stop a later attempt. Existing reparse
paths and oversized manifests are rejected. Checks do not provide an atomic
defense against a malicious same-user process concurrently replacing junctions.
No message bodies, credentials, command arguments or environment contents are logged.

## Build and qualification

Windows resource packaging uses the OS's .NET Framework compiler and includes
the helper and matching PDB. Temporary compiler output stays outside bundle
resources and is removed after the protocol-only smoke test. No app is started
by packaging. A development launch without the sibling helper stays unmanaged
and logs that limitation.

Run `src/tooling/windows/recovery/tests/Run-Isolated.ps1 -Base <private-test-dir>`
to compile the actual core with private fixture processes. It covers clean and
unknown exits, ready/crash races, stop-before-crash, distinct run IDs, backoff and
circuit breaking, local session messages, maintenance, wrong process identities,
stale and oversized manifests, reparse paths and duplicate monitors. The Windows
workflow runs it before native Rust compilation and complete NSIS packaging.

These are isolated component tests, not production GUI/installer acceptance.
Real shutdown/logoff, cross-logon sessions and complete installed Tauri lifetime
remain separately qualified. Do not kill a working HUD to run these fixtures.

The Desktop stream-v13 communication repair is an independent prerequisite for
the current Windows candidate. A watchdog cannot repair a protocol rejection.
Do not install a recovery-only branch over a newer messaging fix; combine the
accepted fixes, build the full Windows package and preserve rollback first.
