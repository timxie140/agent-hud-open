# Windows Codex queue activation

Windows automatic HUD delivery (`steer-or-enqueue`, used for Dot and native
DSH messages) steers a verified active Desktop turn. If the owner is idle or
proven absent, it persists the message once in Codex's native queue. It then
requests `codex://threads/wake/<thread UUID>` through the existing Windows
protocol handler so the original Desktop client can consume that queue.
No second conversation or alternative owner is created.

The temporary app-server must also use the currently registered Codex runtime
after a Store update; see [runtime update handling](windows-codex-runtime-updates.md).

The previous Windows adapter only added the queue item. An idle thread could
therefore keep the accepted message until the user manually opened or started
it. The Unix adapter already used Codex's wake URI; this change adds the missing
Windows activation step with queue checks.

## Guard conditions

The native URI names a thread, not a queue item. Before requesting activation,
HUD checks that:

- the pre-add queue was empty, with no additional page;
- the add response identifies the accepted submission and matches the original
  `agent-hud:<request ID>` and text input;
- the post-add queue contains exactly that submission, with the same ID, client
  message ID and unchanged text input, and no additional page.

A known backlog, edited/replaced input, concurrent additional item, unknown
response, pagination or failed inspection withholds wake. The accepted message
remains queued and its receipt explains why. HUD does not delete, reorder,
re-add or start queue items. Explicit `enqueue` requests and new-thread queueing
keep their previous behavior.

Owner refusal, unsupported protocol and uncertain delivery still fail closed;
they do not fall through into a second queue submission. The existing durable
attempt journal prevents automatic resends or repeated wake calls for the same
request after retries or restarts.

## Evidence and limitations

Opening the URI only requests activation. The receipt remains **queued**, even
if the operating system accepts the link; it does not claim **started** or
**received**. A failed link request also leaves the already accepted queue
intact. Native input observation and the usual delivery receipt must confirm
actual receipt separately.

Codex's wake handler controls readiness, ownership, permissions, queue admission
and consumption. HUD does not bypass these checks or call `thread/resume`,
`thread/queue/start` or `turn/start` in its temporary app-server. Codex exposes
no atomic wake-if-this-item-is-head operation: another client can change the
queue after the last read. The guards avoid waking a known old backlog; they
cannot make cross-client changes atomic or guarantee start latency.

## Validation

Windows-only isolated tests use fake queue RPC and link-opening ports. They
check submission identity and content, operation order, one add/one activation,
backlog holds, concurrent/malformed results, rejection, uncertain acceptance and
activation failure. No live profile, queue, native pipe or URI is used.
Existing journal tests check restart deduplication and uncertain non-resend;
Windows pipe fixtures retain refusal/no-fallback coverage.

Native Windows CI compilation and tests do not establish real-machine receipt.
Before switching the running HUD, preserve the installed build and configuration.
Real acceptance must use a single new maintenance message to an authorized idle
existing thread with no old queue, observe its native input without manual Steer,
and verify the reply. Do not replay the delayed business message as a test.
