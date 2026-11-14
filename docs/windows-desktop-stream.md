# Windows Codex Desktop state stream

Private Windows owner delivery and native Dot receipt observation accept the
qualified Desktop snapshot envelopes **11 and 13**. Unix delivery remains on
version 11; its long-lived observer is unchanged.

Version 13 was observed read-only from a same-user local Desktop owner. It uses
the existing `thread-stream-state-changed` snapshot envelope and canonical
`turnHistory.history` with `islands`, entry references and `entitiesByKey`.
The existing start/steer request versions remain 2/1 in that installed client.
No message was submitted to collect the schema.

The decoder first correlates owner, local host and conversation. Version 13
also binds the inner state ID and host, requires the observed canonical
containers, and validates current-turn identity/status before delivery. Future
versions and unknown structures remain failures, not an alternate queue route.
Only an empty `turns` overlay is qualified. A nonempty overlay is rejected,
because the canonical selector cannot establish its current-turn semantics.
The newest island must have `newerBoundary.status=exhausted`, with resolvable
turn references, identities, statuses and item arrays. An unknown newest edge
cannot mean idle. Older pages may remain unloaded (`isComplete=false` is allowed);
the decoder does not require the whole old history to be fetched.
Existing expected-turn checks, exact input fingerprint verification, ambiguity
rejection and no-resend journals remain in force.

`Protocol("Desktop stream version")` means a correlated native stream event
was not one of the qualified versions. It is distinct from unavailable owner,
queue acceptance, tool permission denial and actual recipient confirmation.
Do not remove the guard or replay failed business messages to test compatibility.

Regression cases in `delivery/codex/snapshot_tests.rs` use synthetic data only:
legacy/canonical active and idle snapshots, foreign-envelope filtering, unknown
versions, malformed canonical history, conflicting inner identity, and canonical
receiving-input proof. Complete runtime acceptance still requires the packaged
Windows app and existing recipients; CI alone is not that acceptance.

`delivery/codex/desktop_windows_tests.rs` additionally uses unique same-user
named pipes with the real IPC transport, without opening `codex-ipc`. It covers
11/13 active steering, idle queue handoff, start/steer request versions 2/1,
foreign-event filtering, rejected/uncertain/timed-out mutations without retries,
unfollow on success/failure, and read-only canonical receiving-input proof.
It does not test a real installed Codex or authorize replaying earlier failures.
