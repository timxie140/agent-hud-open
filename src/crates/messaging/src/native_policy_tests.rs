//! Native DSH sends and replies use the verified Codex delivery policy.
use super::*;

#[test]
fn dsh_to_codex_uses_fresh_client_state_for_steer_or_queue() {
    for state in ["running", "idle", "waitingForApproval"] {
        let mut world = World::on();
        world.harness();
        world.snapshot["sessions"][1]["state"] = json!(state);
        let result = world.send(("deepseek", HARNESS_OWN), CODEX, "Review this");
        assert_ne!(result["state"], "refused");
        let sent = world.codex.0.lock().unwrap();
        assert_eq!(sent.len(), 1);
        assert_eq!(sent[0].operation, Operation::SteerOrEnqueue);
        assert_eq!(sent[0].request_id, result["id"]);
        assert!(sent[0].text.contains("from DeepSeek Harness"));
    }
}

#[test]
fn dsh_reply_to_codex_keeps_recipient_identity_and_uses_steer_or_queue() {
    let mut world = World::on();
    world.harness();
    world.harness_session(HARNESS_TWO, HARNESS_TWO_OWN, "Another DSH");
    let parent = world.send(("codex", CODEX), HARNESS, "Please review");
    assert_eq!(parent["state"], "queued");
    let forged = world.call(
        Some(("deepseek", HARNESS_TWO_OWN)),
        "send_message",
        json!({"reply_to":parent["id"],"text":"Not my message"}),
    );
    assert_eq!(forged["state"], "refused");
    assert!(world.codex.0.lock().unwrap().is_empty());
    let reply = world.call(
        Some(("deepseek", HARNESS_OWN)),
        "send_message",
        json!({"reply_to":parent["id"],"text":"Reviewed"}),
    );
    assert_ne!(reply["state"], "refused");
    let sent = world.codex.0.lock().unwrap();
    assert_eq!(sent.len(), 1);
    assert_eq!(sent[0].operation, Operation::SteerOrEnqueue);
    assert_eq!(sent[0].request_id, reply["id"]);
    assert!(sent[0].text.contains(parent["id"].as_str().unwrap()));
    drop(sent);
    assert_eq!(world.get(&parent["id"])["reply"], reply["id"]);
}
