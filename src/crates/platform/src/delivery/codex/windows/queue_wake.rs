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
    let mut server =
        process::StdioServer::open(&route.executable, data, &route.environment, timeout)?;
    let reason = enqueue_with(
        &mut server,
        &process::NativeProcessRunner,
        thread,
        text,
        message_id,
    );
    server.end();
    reason
}

/// `open` only requests native activation. Queue/start/receipt remain the
/// desktop client's responsibility. A failure after add must not invite resend.
fn enqueue_with(
    rpc: &mut impl QueueRpc,
    opener: &impl process::ProcessRunner,
    thread: &str,
    text: &str,
    message_id: &str,
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
