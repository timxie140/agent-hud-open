//! Codex on Windows: the desktop app's owner pipe, and Codex's queue through
//! a short-lived app-server. Windows has no shared CLI daemon, so a thread
//! only a terminal CLI holds takes no message here, and nothing is
//! interrupted.
use super::*;

#[path = "windows/persisted.rs"]
mod persisted;
#[path = "windows/queue_wake.rs"]
mod queue_wake;
pub(super) use persisted::persisted_input;

pub(super) fn steer_ready(data: &Path, thread: &str, timeout: Duration) -> Result<bool> {
    if !valid_uuid(thread) || !super::thread_open(data, thread) {
        return Ok(false);
    }
    let Some(state) = super::desktop::owned_snapshot(data, thread, timeout)? else {
        return Ok(false);
    };
    Ok(!super::desktop::turn_waits_on_user(&state)
        && super::current_desktop_turn(&state)?.is_some_and(|(_, status)| status == "inProgress"))
}

/// Agent HUD sends to Codex on this host.
pub(crate) const SUPPORTED: bool = true;
/// Exact native snapshot schemas qualified for private Windows owner delivery.
pub(super) const STREAM_VERSIONS: &[u64] = &[11, 13];
/// A new thread's first message goes through Codex's queue here, which the
/// app that opens the thread runs in its own model: none can be named.
pub(crate) const MODEL_AT_START: bool = false;
/// What a send may ask for: start and steer through the desktop app, and
/// Codex's queue. Interrupt is not offered.
pub(crate) const OPERATIONS: &[Operation] = &[
    Operation::Automatic,
    Operation::Start,
    Operation::Steer,
    Operation::SteerOrEnqueue,
    Operation::Enqueue,
];

pub(super) fn deliver(
    data: &Path,
    target: &SessionTarget,
    request: &SendRequest,
    timeout: Duration,
    queue: Option<&QueueRoute>,
) -> Result<Receipt> {
    let thread = target
        .thread_id
        .as_deref()
        .filter(|thread| valid_uuid(thread))
        .ok_or_else(|| Failure::InvalidInput("Codex thread identity".into()))?;
    if request.operation == Operation::SteerOrEnqueue {
        if let Some(receipt) = super::desktop::deliver(data, target, request, thread, timeout)? {
            return Ok(receipt);
        }
    } else if request.operation != Operation::Enqueue {
        return super::desktop::deliver(data, target, request, thread, timeout)?.ok_or_else(|| {
            Failure::Unavailable(
                "No active Codex Desktop owner; Windows CLI owner control is unavailable".into(),
            )
        });
    }
    let route = queue.ok_or_else(|| Failure::Unavailable("Codex executable".into()))?;
    let message_id = format!("agent-hud:{}", request.request_id);
    let reason = queue_wake::enqueue(route, data, thread, &request.text, &message_id, timeout)?;
    Ok(Receipt {
        provider: Provider::Codex,
        session_id: target.session_id.clone(),
        thread_id: target.thread_id.clone(),
        request_id: request.request_id.clone(),
        client_request_id: message_id,
        turn_id: None,
        owner_client_id: None,
        state: DeliveryState::Queued,
        at_ms: millis(SystemTime::now()),
        reason: Some(reason.into()),
    })
}

/// Windows has no shared CLI daemon to start a thread in: the caller starts
/// it through a short-lived app-server, with or without the desktop app.
pub(crate) fn start_in_daemon(
    _data: &Path,
    _folder: &Path,
    _request: &StartRequest,
    _message_id: &str,
    _timeout: Duration,
) -> Option<Result<StartReceipt>> {
    None
}

/// Queues a new thread's first message through a short-lived app-server.
pub(crate) fn queue_created(
    route: &QueueRoute,
    data: &Path,
    thread: &str,
    text: &str,
    message_id: &str,
    timeout: Duration,
) -> Result<()> {
    enqueue_stdio(route, data, thread, text, message_id, timeout)
}
