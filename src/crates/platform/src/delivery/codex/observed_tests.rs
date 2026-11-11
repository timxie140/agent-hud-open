use super::*;
use serde_json::json;
const THREAD: &str = "00000000-0000-4000-8000-000000000001";
const TEXT: &str = "isolated input";
fn hash() -> String {
    format!("{:x}", Sha256::digest(TEXT.as_bytes()))
}
fn state() -> Value {
    json!({"turnHistory":{"kind":"canonical","history":{"islands":[{"entries":[{"value":"k"}]}],
        "entitiesByKey":{"k":{"turnId":"received-turn","status":"completed","items":[
            {"type":"userMessage","id":"native-item","clientUserMessageId":"agent-hud:m-fixture",
             "content":[{"type":"text","text":TEXT}]}]}}}},"turns":[]})
}
#[test]
fn canonical_input_is_bound_to_both_native_request_and_content() {
    let state = state();
    let proof = recorded(&state, THREAD, "m-fixture", &hash()).unwrap();
    assert_eq!(proof.thread(), THREAD);
    assert_eq!(proof.turn(), "received-turn");
    assert_eq!(proof.text(), TEXT);
    assert!(recorded(&state, THREAD, "m-other", &hash()).is_none());
    assert!(recorded(&state, THREAD, "m-fixture", "wrong-fingerprint").is_none());
}
#[test]
fn canonical_native_ids_may_replace_client_ids_but_conflicting_ids_are_refused() {
    let mut value = state();
    value["turnHistory"]["history"]["entitiesByKey"]["k"]["items"][0]
        .as_object_mut()
        .unwrap()
        .remove("clientUserMessageId");
    assert!(recorded(&value, THREAD, "m-fixture", &hash()).is_some());
    assert!(recorded(&value, THREAD, "m-fixture", "wrong-fingerprint").is_none());
    value["turnHistory"]["history"]["entitiesByKey"]["k"]["items"][0]["id"] =
        json!("agent-hud:m-other");
    assert!(recorded(&value, THREAD, "m-fixture", &hash()).is_none());
}
#[test]
fn queued_optimistic_unknown_and_ambiguous_states_are_not_receipt_proof() {
    let original = state();
    let turn = original["turnHistory"]["history"]["entitiesByKey"]["k"].clone();
    for value in [
        json!({"queuedSubmissions":[turn.clone()]}),
        json!({"turns":[turn.clone()]}),
        json!({"turnHistory":{"kind":"future"},"turns":[turn.clone()]}),
    ] {
        assert!(recorded(&value, THREAD, "m-fixture", &hash()).is_none());
    }
    let mut duplicate = original.clone();
    duplicate["turns"] = json!([turn]);
    assert!(recorded(&duplicate, THREAD, "m-fixture", &hash()).is_none());
    for status in ["queued", "pending", "failed", "interrupted"] {
        let mut value = original.clone();
        value["turnHistory"]["history"]["entitiesByKey"]["k"]["status"] = json!(status);
        assert!(recorded(&value, THREAD, "m-fixture", &hash()).is_none());
    }
}
#[test]
fn only_canonical_accepted_steering_is_proof() {
    let mut value = state();
    let item = &mut value["turnHistory"]["history"]["entitiesByKey"]["k"]["items"][0];
    item["type"] = json!("steeringUserMessage");
    item["input"] = item["content"].clone();
    item["status"] = json!("pending");
    assert!(recorded(&value, THREAD, "m-fixture", &hash()).is_none());
    value["turnHistory"]["history"]["entitiesByKey"]["k"]["items"][0]["status"] = json!("accepted");
    assert!(recorded(&value, THREAD, "m-fixture", &hash()).is_some());
}

#[cfg(unix)]
#[path = "observed_unix_tests.rs"]
mod unix;
