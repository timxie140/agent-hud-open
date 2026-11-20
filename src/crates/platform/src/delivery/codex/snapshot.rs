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
            || !state["turns"].as_array().is_some_and(Vec::is_empty)
            || change["revision"].as_u64().is_none()
            || state["turnHistory"]["kind"] != "canonical"
            || !history["islands"].is_array()
            || !history["entitiesByKey"].is_object()
        {
            return Err(SnapshotError::State);
        }
        // Only an exhausted newest boundary proves that the latest turn is
        // loaded. Older history may still be paged out; isComplete need not be true.
        let newest = history["islands"]
            .as_array()
            .and_then(|islands| islands.last())
            .filter(|island| island["newerBoundary"]["status"] == "exhausted")
            .ok_or(SnapshotError::State)?;
        let entries = newest["entries"].as_array().ok_or(SnapshotError::State)?;
        for (index, entry) in entries.iter().enumerate() {
            let turn = entry["value"]
                .as_str()
                .and_then(|key| history["entitiesByKey"].get(key))
                .ok_or(SnapshotError::State)?;
            if !turn["turnId"].as_str().is_some_and(|id| !id.is_empty())
                || !turn["items"].is_array()
                || !matches!(
                    turn["status"].as_str(),
                    Some("inProgress" | "completed" | "failed" | "interrupted")
                )
                || (turn["status"] == "inProgress" && index + 1 != entries.len())
            {
                return Err(SnapshotError::State);
            }
        }
        let current = super::current_desktop_turn(state).map_err(|_| SnapshotError::State)?;
        // Do not let the legacy selector fall back across a history gap.
        if entries.is_empty() && current.is_some() {
            return Err(SnapshotError::State);
        }
    }
    Ok(Some(state.clone()))
}
