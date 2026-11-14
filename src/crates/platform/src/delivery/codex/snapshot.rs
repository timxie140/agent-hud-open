//! Qualified Desktop stream envelopes; foreign owners never become input evidence.
use serde_json::Value;

#[derive(Debug, PartialEq)]
pub(super) enum SnapshotError {
    Version,
    State,
}

pub(super) fn decode(
    message: &Value,
    owner: &str,
    thread: &str,
    versions: &[u64],
) -> Result<Option<Value>, SnapshotError> {
    if message["type"] != "broadcast"
        || message["method"] != "thread-stream-state-changed"
        || message["sourceClientId"] != owner
        || message["params"]["hostId"] != "local"
        || message["params"]["conversationId"] != thread
    {
        return Ok(None);
    }
    let version = message["version"]
        .as_u64()
        .filter(|version| versions.contains(version))
        .ok_or(SnapshotError::Version)?;
    let change = &message["params"]["change"];
    if change["type"] != "snapshot" {
        return Ok(None);
    }
    let state = &change["conversationState"];
    if !state.is_object() {
        return Err(SnapshotError::State);
    }
    // Windows v13 was qualified against a same-user native owner's snapshot.
    // Accept its observed canonical containers, not arbitrary future schemas.
    if version == 13 {
        let history = &state["turnHistory"]["history"];
        if state["id"] != thread
            || state["hostId"] != "local"
            || !state["turns"].is_array()
            || state["turnHistory"]["kind"] != "canonical"
            || !history["islands"].is_array()
            || !history["entitiesByKey"].is_object()
        {
            return Err(SnapshotError::State);
        }
        let current = super::current_desktop_turn(state).map_err(|_| SnapshotError::State)?;
        if current.is_some_and(|(_, status)| {
            !matches!(
                status.as_str(),
                "inProgress" | "completed" | "failed" | "interrupted"
            )
        }) {
            return Err(SnapshotError::State);
        }
    }
    Ok(Some(state.clone()))
}
