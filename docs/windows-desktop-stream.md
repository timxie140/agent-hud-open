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
