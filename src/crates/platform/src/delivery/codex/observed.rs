//! A read-only observation from the real Desktop thread owner, never a queue ACK.
use super::*;
use serde_json::Value;
use sha2::{Digest, Sha256};

/// Not serializable/debuggable: its text may contain a private receipt challenge.
/// Only the native adapter (or isolated fixture feature) can construct this proof.
pub struct ReceivedInput {
    pub(super) thread: String,
    pub(super) request: String,
    pub(super) turn: String,
    pub(super) text: String,
}
impl ReceivedInput {
    pub fn thread(&self) -> &str {
        &self.thread
    }
    pub fn request(&self) -> &str {
        &self.request
    }
    pub fn turn(&self) -> &str {
        &self.turn
    }
    pub fn text(&self) -> &str {
        &self.text
    }
}

pub(super) fn recorded(
    state: &Value,
    thread: &str,
    request: &str,
    fingerprint: &str,
) -> Option<ReceivedInput> {
    // Only native canonical input, not an optimistic UI overlay, is proof.
    // Unknown/older Desktop schemas remain unconfirmed for manual fallback.
    let storage = state.get("turnHistory")?;
    if storage["kind"] != "canonical" {
        return None;
    }
    let history = &storage["history"];
    let mut turns = Vec::new();
    let mut ids = std::collections::HashSet::new();
    for island in history["islands"].as_array()? {
        for entry in island["entries"].as_array()? {
            let turn = history["entitiesByKey"].get(entry["value"].as_str()?)?;
            let id = turn["turnId"].as_str().filter(|id| !id.is_empty())?;
            if !ids.insert(id) {
                return None;
            }
            turns.push(turn);
        }
    }
    if state.get("turns").is_some_and(|overlay| {
        overlay.as_array().is_none_or(|turns| {
            turns
                .iter()
                .any(|turn| turn["turnId"].as_str().is_some_and(|id| ids.contains(id)))
        })
    }) {
        return None;
    }
    let expected = format!("agent-hud:{request}");
    let mut found = None;
    for turn in turns.into_iter().rev() {
        if !matches!(turn["status"].as_str(), Some("inProgress" | "completed")) {
            continue;
        }
        let Some(turn_id) = turn
            .get("turnId")
            .filter(|v| !v.is_null())
            .or_else(|| turn.get("id"))
            .and_then(Value::as_str)
            .filter(|id| !id.is_empty())
        else {
            continue;
        };
        let Some(items) = turn["items"].as_array() else {
            continue;
        };
        for item in items {
            // Pending queue/restore objects and optimistic steering overlays
            // are not native receipt evidence. Accepted steering must be canonical.
            let content = match item["type"].as_str() {
                Some("userMessage") => &item["content"],
                Some("steeringUserMessage") if item["status"] == "accepted" => &item["input"],
                _ => continue,
            };
            if item["id"] != expected && item["clientUserMessageId"] != expected {
                continue;
            }
            let Some(parts) = content
                .as_array()
                .filter(|v| v.len() == 1 && v[0]["type"] == "text")
            else {
                continue;
            };
            let Some(text) = parts[0]["text"].as_str() else {
                continue;
            };
            if format!("{:x}", Sha256::digest(text.trim().as_bytes())) != fingerprint {
                continue;
            }
            if found.is_some() {
                return None;
            }
            found = Some(ReceivedInput {
                thread: thread.into(),
                request: request.into(),
                turn: turn_id.into(),
                text: text.into(),
            });
        }
    }
    found
}

pub(super) fn observe(
    data: &Path,
    target: &SessionTarget,
    request: &str,
    fingerprint: &str,
    timeout: Duration,
) -> Result<Option<ReceivedInput>> {
    let thread = target
        .thread_id
        .as_deref()
        .filter(|id| valid_uuid(id))
        .ok_or_else(|| Failure::InvalidInput("Receiving Codex thread".into()))?;
    let Some(state) = super::desktop::owned_snapshot(data, thread, timeout)? else {
        return Ok(None);
    };
    Ok(recorded(&state, thread, request, fingerprint))
}

#[cfg(any(test, feature = "fixtures"))]
pub fn fixture(thread: &str, request: &str, turn: &str, text: &str) -> ReceivedInput {
    ReceivedInput {
        thread: thread.into(),
        request: request.into(),
        turn: turn.into(),
        text: text.into(),
    }
}

#[cfg(test)]
#[path = "observed_tests.rs"]
mod tests;
