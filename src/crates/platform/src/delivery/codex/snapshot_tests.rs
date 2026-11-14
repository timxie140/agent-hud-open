use super::current_desktop_turn;
use super::snapshot::{decode, SnapshotError};
use serde_json::{json, Value};

const OWNER: &str = "synthetic-owner";
const THREAD: &str = "synthetic-thread";
const VERSIONS: &[u64] = &[11, 13];

fn envelope(version: u64, state: Value) -> Value {
    json!({
        "type": "broadcast",
        "method": "thread-stream-state-changed",
        "sourceClientId": OWNER,
        "version": version,
        "params": {
            "hostId": "local",
            "conversationId": THREAD,
            "change": {"type": "snapshot", "conversationState": state}
        }
    })
}

fn canonical(turn: Option<Value>) -> Value {
    let (entries, entities) = match turn {
        Some(turn) => (
            json!([{"value": "synthetic-key"}]),
            json!({"synthetic-key": turn}),
        ),
        None => (json!([]), json!({})),
    };
    json!({
        "id": THREAD,
        "hostId": "local",
        "turns": [],
        "turnHistory": {"kind": "canonical", "history": {
            "islands": [{"entries": entries, "newerBoundary": {"status": "exhausted"}}],
            "entitiesByKey": entities
        }}
    })
}

#[test]
fn valid_snapshots_preserve_turn_selection_for_legacy_and_canonical_history() {
    let legacy = json!({"turns": [{"turnId": "legacy-turn", "status": "inProgress"}]});
    let active = canonical(Some(
        json!({"turnId": "canonical-turn", "status": "inProgress"}),
    ));
    for (version, state, expected) in [
        (
            11,
            legacy,
            Some(("legacy-turn".to_owned(), "inProgress".to_owned())),
        ),
        (
            13,
            active,
            Some(("canonical-turn".to_owned(), "inProgress".to_owned())),
        ),
        (13, canonical(None), None),
    ] {
        let decoded = decode(&envelope(version, state.clone()), OWNER, THREAD, VERSIONS)
            .unwrap()
            .expect("matching snapshot");
        assert_eq!(decoded, state);
        assert_eq!(current_desktop_turn(&decoded).unwrap(), expected);
    }
}

#[test]
fn unrelated_broadcasts_are_ignored_before_version_or_state_validation() {
    for path in [
        "type",
        "method",
        "sourceClientId",
        "hostId",
        "conversationId",
    ] {
        let mut message = envelope(99, Value::Null);
        match path {
            "type" => message["type"] = json!("request"),
            "method" => message["method"] = json!("another-method"),
            "sourceClientId" => message["sourceClientId"] = json!("another-owner"),
            "hostId" => message["params"]["hostId"] = json!("remote"),
            "conversationId" => message["params"]["conversationId"] = json!("another-thread"),
            _ => unreachable!(),
        }
        assert_eq!(
            decode(&message, OWNER, THREAD, VERSIONS),
            Ok(None),
            "{path}"
        );
    }
    let mut message = envelope(13, canonical(None));
    message["params"]["change"]["type"] = json!("patch");
    assert_eq!(decode(&message, OWNER, THREAD, VERSIONS), Ok(None));
}

#[test]
fn unsupported_or_invalid_versions_are_rejected() {
    let mut message = envelope(12, canonical(None));
    assert_eq!(
        decode(&message, OWNER, THREAD, VERSIONS),
        Err(SnapshotError::Version)
    );
    message["version"] = json!("13");
    assert_eq!(
        decode(&message, OWNER, THREAD, VERSIONS),
        Err(SnapshotError::Version)
    );
    message.as_object_mut().unwrap().remove("version");
    assert_eq!(
        decode(&message, OWNER, THREAD, VERSIONS),
        Err(SnapshotError::Version)
    );
    assert_eq!(
        decode(&envelope(13, canonical(None)), OWNER, THREAD, &[11]),
        Err(SnapshotError::Version)
    );
}

#[test]
fn snapshot_state_must_be_an_object() {
    for version in [11, 13] {
        for state in [Value::Null, json!([]), json!("state"), json!(42)] {
            assert_eq!(
                decode(&envelope(version, state), OWNER, THREAD, VERSIONS),
                Err(SnapshotError::State)
            );
        }
        let mut message = envelope(version, json!({}));
        message["params"]["change"]
            .as_object_mut()
            .unwrap()
            .remove("conversationState");
        assert_eq!(
            decode(&message, OWNER, THREAD, VERSIONS),
            Err(SnapshotError::State)
        );
    }
}

#[test]
fn version_13_requires_the_observed_canonical_container_shape() {
    let valid = canonical(None);
    let mut cases = Vec::new();
    let mut state = valid.clone();
    state.as_object_mut().unwrap().remove("turns");
    cases.push(state);
    let mut state = valid.clone();
    state["turns"] = json!({});
    cases.push(state);
    let mut state = valid.clone();
    state["turnHistory"]["kind"] = json!("future");
    cases.push(state);
    let mut state = valid.clone();
    state.as_object_mut().unwrap().remove("turnHistory");
    cases.push(state);
    let mut state = valid.clone();
    state["turnHistory"]["history"]
        .as_object_mut()
        .unwrap()
        .remove("islands");
    cases.push(state);
    let mut state = valid.clone();
    state["turnHistory"]["history"]["islands"] = json!({});
    cases.push(state);
    let mut state = valid.clone();
    state["turnHistory"]["history"]
        .as_object_mut()
        .unwrap()
        .remove("entitiesByKey");
    cases.push(state);
    let mut state = valid;
    state["turnHistory"]["history"]["entitiesByKey"] = json!([]);
    cases.push(state);
    for state in cases {
        assert_eq!(
            decode(&envelope(13, state), OWNER, THREAD, VERSIONS),
            Err(SnapshotError::State)
        );
    }
}

#[test]
fn version_13_requires_matching_body_identity() {
    for field in ["id", "hostId"] {
        let mut missing = canonical(None);
        missing.as_object_mut().unwrap().remove(field);
        assert_eq!(
            decode(&envelope(13, missing), OWNER, THREAD, VERSIONS),
            Err(SnapshotError::State),
            "missing {field}"
        );

        let mut mismatched = canonical(None);
        mismatched[field] = json!("different-value");
        assert_eq!(
            decode(&envelope(13, mismatched), OWNER, THREAD, VERSIONS),
            Err(SnapshotError::State),
            "mismatched {field}"
        );
    }
}

#[test]
fn malformed_or_unknown_current_turns_are_rejected_before_delivery() {
    for turn in [
        json!({"status": "inProgress"}),
        json!({"turnId": "synthetic-turn", "status": "future"}),
    ] {
        assert_eq!(
            decode(
                &envelope(13, canonical(Some(turn))),
                OWNER,
                THREAD,
                VERSIONS
            ),
            Err(SnapshotError::State)
        );
    }
}

#[test]
fn version_13_still_requires_unique_canonical_receiving_input() {
    use sha2::{Digest, Sha256};
    let text = "isolated v13 input";
    let fingerprint = format!("{:x}", Sha256::digest(text.as_bytes()));
    let state = canonical(Some(json!({"turnId":"received-turn", "status":"completed",
        "items":[{"type":"userMessage", "id":"native-item", "clientId":"native-client",
            "clientUserMessageId":"agent-hud:m-v13", "content":[{"type":"text", "text":text}]}]})));
    let decoded = decode(&envelope(13, state), OWNER, THREAD, VERSIONS)
        .unwrap()
        .unwrap();
    let proof = super::observed::recorded(&decoded, THREAD, "m-v13", &fingerprint).unwrap();
    assert_eq!(proof.thread(), THREAD);
    assert_eq!(proof.turn(), "received-turn");
    assert!(super::observed::recorded(&decoded, THREAD, "m-other", &fingerprint).is_none());
    assert!(super::observed::recorded(&decoded, THREAD, "m-v13", "wrong-body").is_none());
    let mut optimistic = decoded.clone();
    optimistic["turns"] = json!([{"turnId":"received-turn"}]);
    assert!(super::observed::recorded(&optimistic, THREAD, "m-v13", &fingerprint).is_none());
}
