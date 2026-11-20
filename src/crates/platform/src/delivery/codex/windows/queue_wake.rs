//! Wake the original desktop client after persisting a single new queue item.
//! The native URI is thread-scoped, not item-scoped. Never wake a known backlog
//! or an unverifiable queue, and never start a turn in this temporary server.
use super::*;
use serde_json::{json, Value};

pub(super) trait QueueRpc {
    fn read(&mut self, method: &str, params: Value) -> Result<Value>;
    fn add(&mut self, params: Value) -> Result<Value>;
}
impl QueueRpc for process::StdioServer {
    fn read(&mut self, method: &str, params: Value) -> Result<Value> {
        self.request(method, params)
    }
    fn add(&mut self, params: Value) -> Result<Value> {
        self.mutation("thread/queue/add", params)
    }
}

pub(super) fn enqueue(
    route: &QueueRoute,
    data: &Path,
    thread: &str,
    text: &str,
    message_id: &str,
    timeout: Duration,
) -> Result<&'static str> {
    let mut server = process::StdioServer::open_route(route, data, timeout)?;
    let reason = enqueue_with(
        &mut server,
        &process::NativeProcessRunner,
        thread,
        text,
        message_id,
        |rpc| can_wake(data, thread, timeout.min(Duration::from_millis(250)), rpc),
    );
    server.end();
    reason
}

fn can_wake(data: &Path, thread: &str, timeout: Duration, rpc: &mut impl QueueRpc) -> bool {
    match super::super::desktop::owned_snapshot(data, thread, timeout) {
        Ok(Some(state)) => {
            state["threadRuntimeStatus"]["type"] != "active"
                && !super::super::desktop::turn_waits_on_user(&state)
                && match super::super::current_desktop_turn(&state) {
                    Ok(None) => true,
                    Ok(Some((_, status))) => {
                        matches!(status.as_str(), "completed" | "failed")
                    }
                    Err(_) => false,
                }
        }
        Ok(None) => unloaded_idle(data, thread, rpc),
        Err(Failure::Unavailable(reason))
            if [
                "Codex Desktop endpoint unavailable (Windows error 2)",
                "Codex Desktop endpoint unavailable (Windows error 3)",
            ]
            .contains(&reason.as_str()) =>
        {
            unloaded_idle(data, thread, rpc)
        }
        Err(_) => false,
    }
}

fn unloaded_idle(data: &Path, thread: &str, rpc: &mut impl QueueRpc) -> bool {
    // The desktop deliberately pauses its queue after an interruption.
    // An unloaded thread with unfinished history is also unsafe to wake.
    let Ok(result) = rpc.read(
        "thread/turns/list",
        json!({"threadId":thread,"limit":1,"sortDirection":"desc","itemsView":"notLoaded"}),
    ) else {
        return false;
    };
    let Some(turns) = result["data"].as_array() else {
        return false;
    };
    match turns.as_slice() {
        [] if result["nextCursor"].is_null() => {}
        [turn] if matches!(turn["status"].as_str(), Some("completed" | "failed")) => {}
        _ => return false,
    }

    // A live writer or an unreadable lock keeps the queue untouched.
    let lock = data
        .join("thread-writer-locks")
        .join(format!("{thread}.lock"));
    match std::fs::File::open(lock) {
        Ok(file) => file.try_lock_shared().is_ok(),
        Err(error) => error.kind() == std::io::ErrorKind::NotFound,
    }
}

/// `open` only requests native activation. Queue/start/receipt remain the
/// desktop client's responsibility. A failure after add must not invite resend.
fn enqueue_with<R: QueueRpc>(
    rpc: &mut R,
    opener: &impl process::ProcessRunner,
    thread: &str,
    text: &str,
    message_id: &str,
    can_wake: impl FnOnce(&mut R) -> bool,
) -> Result<&'static str> {
    if !valid_uuid(thread) || message_id.is_empty() {
        return Err(Failure::InvalidInput("Codex queue identity".into()));
    }
    let list = json!({"threadId": thread, "limit": 2});
    let was_empty = rpc
        .read("thread/queue/list", list.clone())
        .ok()
        .is_some_and(|value| complete_items(&value).is_some_and(|items| items.is_empty()));
    let input = json!([{"type":"text", "text":text, "text_elements":[]}]);
    let added = rpc.add(json!({
        "threadId": thread, "clientUserMessageId": message_id, "input": input
    }))?;
    let submission = &added["queuedSubmission"];
    if !submission.is_object() {
        return Err(Failure::AcceptanceUncertain);
    }
    if !was_empty {
        return Ok("Queued; native wake withheld because the previous queue was not proven empty");
    }
    let Some(id) = submission["id"].as_str().filter(|id| !id.is_empty()) else {
        return Ok(
            "Queued; native wake withheld because the accepted queue identity is unverified",
        );
    };
    if !matches_input(submission, message_id, text) {
        return Ok("Queued; native wake withheld because the accepted queue input is unverified");
    }
    if !can_wake(rpc) {
        return Ok("Queued; native wake withheld because the thread was not verified idle");
    }
    let verified = rpc
        .read("thread/queue/list", list)
        .ok()
        .is_some_and(|value| {
            complete_items(&value).is_some_and(|items| {
                items.len() == 1
                    && items[0]["id"].as_str() == Some(id)
                    && matches_input(&items[0], message_id, text)
            })
        });
    if !verified {
        return Ok(
            "Queued; native wake withheld because the queue changed or could not be verified",
        );
    }
    // A different client can still change the queue after this read: Codex has
    // no atomic wake-if-head-is API. Never claim that opening the URI ran it.
    if opener
        .open(&format!("codex://threads/wake/{thread}"))
        .is_err()
    {
        return Ok("Queued; native wake request failed; start and receipt are not confirmed");
    }
    Ok("Queued; native Codex wake requested; start and receipt are not confirmed")
}

fn complete_items(value: &Value) -> Option<&Vec<Value>> {
    if value
        .get("nextCursor")
        .is_some_and(|cursor| !cursor.is_null())
    {
        return None;
    }
    value.get("data")?.as_array()
}

fn matches_input(item: &Value, message_id: &str, text: &str) -> bool {
    let Some(input) = item["input"].as_array().filter(|input| input.len() == 1) else {
        return false;
    };
    let Some(part) = input[0].as_object() else {
        return false;
    };
    item["clientUserMessageId"].as_str() == Some(message_id)
        && part.get("type").and_then(Value::as_str) == Some("text")
        && part.get("text").and_then(Value::as_str) == Some(text)
        && part
            .get("text_elements")
            .is_none_or(|elements| elements.as_array().is_some_and(|v| v.is_empty()))
        && part
            .keys()
            .all(|key| matches!(key.as_str(), "type" | "text" | "text_elements"))
}

#[cfg(test)]
#[path = "queue_wake_tests.rs"]
mod tests;
