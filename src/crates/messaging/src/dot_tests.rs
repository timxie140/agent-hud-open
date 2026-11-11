//! Isolated Dot/owner fixtures. No tunnel, production data or real challenge.
use super::*;

#[derive(Default)]
struct Dot {
    parent: String,
    claimed: bool,
    calls: Vec<String>,
    native: Value,
    fail_confirm: bool,
    proactive: bool,
    target: Option<String>,
    registry: Value,
}
fn connect(world: &mut World) -> Arc<Mutex<Dot>> {
    let state = Arc::new(Mutex::new(Dot::default()));
    let control = state.clone();
    world.messaging.dot = dot_port::DotPort {
        enabled: Arc::new(|| true),
        control: Arc::new(move |action, value| {
            let mut state = control.lock().unwrap();
            state.calls.push(action.into());
            Ok(match action {
                "status" => json!({"enabled":true,"ready":true,"subscribed":true}),
                "sessions" => {
                    state.registry = value;
                    json!({})
                }
                "send" => {
                    state.parent = value["id"].as_str().unwrap().into();
                    json!({"state":"webhook_accepted"})
                }
                "pending" => {
                    json!({"messages":if state.claimed || state.parent.is_empty() {json!([])} else {
                    json!([{"id":state.parent,"source":format!("codex:{}",state.target.as_deref().unwrap_or(CODEX)),
                        "origin":if state.proactive {"dot"} else {"codex"}}])}})
                }
                "claim" => {
                    state.claimed = true;
                    json!({"claimed":true,"replyId":if state.proactive {&state.parent} else {"m-reply-fixture"},
                    "source":format!("codex:{}",state.target.as_deref().unwrap_or(CODEX)),"origin":if state.proactive {"dot"} else {"codex"},
                    "text":"ACK isolated fixture","deliveryChallenge":"isolated-fixture-challenge-1234"})
                }
                "complete" => {
                    state.native = value["native"].clone();
                    json!({})
                }
                "confirm" => {
                    assert_eq!(
                        value["id"],
                        if state.proactive {
                            &state.parent
                        } else {
                            "m-reply-fixture"
                        }
                    );
                    assert_eq!(value["source"], format!("codex:{CODEX}"));
                    assert_eq!(
                        value["deliveryChallenge"],
                        "isolated-fixture-challenge-1234"
                    );
                    if state.fail_confirm {
                        return Err("Notification outcome uncertain".into());
                    }
                    json!({"recipientConfirmed":true})
                }
                _ => panic!("Unexpected fixture operation"),
            })
        }),
    };
    state
}

#[test]
fn dot_flies_both_ways_reports_native_queue_and_waits_for_real_input() {
    let mut world = World::on();
    let dot = connect(&mut world);
    let sent = world.send(("codex", CODEX), "dot:luo", "isolated marker");
    assert_eq!(sent["state"], "queued");
    world.maintain(1_792_600_005_000);
    assert_eq!(world.codex.0.lock().unwrap().len(), 1);
    assert_eq!(
        dot.lock().unwrap().native,
        json!({"state":"accepted","deliveryMode":"queued"})
    );
    world.maintain(1_792_600_010_000);
    assert!(!dot.lock().unwrap().calls.iter().any(|c| c == "confirm"));
    let flights = flown(&world);
    assert_eq!(flights.len(), 2);
    assert_eq!(flights[0]["from"], "codex");
    assert_eq!(flights[0]["to"], "dot");
    assert_eq!(flights[1]["from"], "dot");
    assert_eq!(flights[1]["to"], "codex");
    // Only the fixture native owner now attests the exact submitted input.
    world.codex.1.store(true, AtomicOrdering::SeqCst);
    world.maintain(1_792_600_015_000);
    world.maintain(1_792_600_020_000);
    assert_eq!(
        dot.lock()
            .unwrap()
            .calls
            .iter()
            .filter(|c| *c == "confirm")
            .count(),
        1
    );
    assert_eq!(
        flown(&world).len(),
        2,
        "a receipt never creates an ACK plane loop"
    );
    let bytes = std::fs::read(world.fixture.root.join("data/messaging/messages.json")).unwrap();
    let saved = String::from_utf8(bytes).unwrap();
    assert!(!saved.contains("isolated-fixture-challenge"));
    assert!(!saved.contains("ACK isolated fixture"));
}

#[test]
fn uncertain_confirmation_is_reserved_across_reload_without_resend() {
    let mut world = World::on();
    let dot = connect(&mut world);
    dot.lock().unwrap().fail_confirm = true;
    world.send(("codex", CODEX), "dot:luo", "isolated marker");
    world.maintain(1_792_600_005_000);
    world.codex.1.store(true, AtomicOrdering::SeqCst);
    world.maintain(1_792_600_010_000);
    world.messaging.journal =
        Journal::load(world.fixture.root.join("data/messaging/messages.json"));
    world.maintain(1_792_600_015_000);
    let state = dot.lock().unwrap();
    assert_eq!(state.calls.iter().filter(|c| *c == "confirm").count(), 1);
    assert_eq!(world.codex.0.lock().unwrap().len(), 1);
}

#[test]
fn disabled_permissions_never_autoconfirm_or_submit_dot_replies() {
    let mut world = World::on();
    let dot = connect(&mut world);
    world.send(("codex", CODEX), "dot:luo", "isolated marker");
    world.snapshot["settings"]["agentMessages"] = json!(false);
    world.maintain(1_792_600_005_000);
    assert_eq!(dot.lock().unwrap().calls, vec!["send", "sessions"]);
    assert_eq!(dot.lock().unwrap().registry["enabled"], false);
    assert!(world.codex.0.lock().unwrap().is_empty());
}

#[test]
fn proactive_dot_selects_existing_codex_without_a_fake_mcp_caller_and_confirms_actual_input() {
    let mut world = World::on();
    let dot = connect(&mut world);
    {
        let mut state = dot.lock().unwrap();
        state.proactive = true;
        state.parent = "m-proactive-fixture".into();
    }
    world.maintain(1_792_600_005_000);
    let sends = world.codex.0.lock().unwrap();
    assert_eq!(sends.len(), 1);
    assert_eq!(sends[0].operation, Operation::SteerOrEnqueue);
    assert!(sends[0]
        .text
        .starts_with("[Agent HUD · Dot Luo; message_id=m-proactive-fixture]"));
    drop(sends);
    let state = dot.lock().unwrap();
    assert_eq!(state.registry["sessions"].as_array().unwrap().len(), 1);
    assert_eq!(state.registry["sessions"][0]["id"], CODEX);
    drop(state);
    let message = world.messaging.journal.find("m-proactive-fixture").unwrap();
    assert_eq!(message.from.client, "dot");
    assert_eq!(message.to.session_id, CODEX);
    assert!(message.reply_to.is_none());
    world.codex.1.store(true, AtomicOrdering::SeqCst);
    world.maintain(1_792_600_010_000);
    world.maintain(1_792_600_015_000);
    assert_eq!(
        dot.lock()
            .unwrap()
            .calls
            .iter()
            .filter(|c| *c == "confirm")
            .count(),
        1
    );
    assert_eq!(
        flown(&world).len(),
        1,
        "confirmation does not emit another plane"
    );
}

#[test]
fn removed_or_child_proactive_targets_are_refused_before_native_delivery() {
    for child in [false, true] {
        let mut world = World::on();
        let dot = connect(&mut world);
        let id = "bbbbbbbb-0000-4000-8000-000000000001";
        if child {
            world.snapshot["sessions"].as_array_mut().unwrap().push(
                json!({"id":id,"source":"codex","title":"child","parentId":CODEX,"state":"idle"}),
            );
        }
        {
            let mut state = dot.lock().unwrap();
            state.proactive = true;
            state.parent = "m-proactive-fixture".into();
            state.target = Some(id.into());
        }
        world.maintain(1_792_600_005_000);
        assert!(world.codex.0.lock().unwrap().is_empty());
        assert_eq!(
            dot.lock().unwrap().native,
            json!({"state":"refused","reasonCode":"recipient_unavailable"})
        );
    }
}

#[test]
fn reservation_write_failure_never_confirms() {
    let mut world = World::on();
    let dot = connect(&mut world);
    world.send(("codex", CODEX), "dot:luo", "isolated marker");
    world.maintain(1_792_600_005_000);
    world.codex.1.store(true, AtomicOrdering::SeqCst);
    let path = world.fixture.root.join("data/messaging/messages.json");
    std::fs::remove_file(&path).unwrap();
    std::fs::create_dir(&path).unwrap();
    world.maintain(1_792_600_010_000);
    assert!(!dot.lock().unwrap().calls.iter().any(|c| c == "confirm"));
}
