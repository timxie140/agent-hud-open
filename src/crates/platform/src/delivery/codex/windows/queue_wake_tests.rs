use super::*;
use std::{
    collections::VecDeque,
    sync::{Arc, Mutex},
};

const THREAD: &str = "12345678-1234-4234-8234-123456789abc";
const MESSAGE: &str = "client-message-1";
const TEXT: &str = "original message\n第二行";
const QUEUED: &str = "submission-1";

type Calls = Arc<Mutex<Vec<(String, Value)>>>;

struct FakeRpc {
    calls: Calls,
    reads: VecDeque<Result<Value>>,
    added: Option<Result<Value>>,
}
impl QueueRpc for FakeRpc {
    fn read(&mut self, method: &str, params: Value) -> Result<Value> {
        self.calls.lock().unwrap().push((method.to_owned(), params));
        self.reads.pop_front().expect("unexpected read")
    }
    fn add(&mut self, params: Value) -> Result<Value> {
        self.calls
            .lock()
            .unwrap()
            .push(("thread/queue/add".into(), params));
        self.added.take().expect("unexpected add")
    }
}
struct FakeOpener {
    calls: Calls,
    fail: bool,
}
impl process::ProcessRunner for FakeOpener {
    fn run(&self, _: &process::CommandPlan) -> Result<process::ProcessOutput> {
        panic!("no process may be spawned in queue wake tests")
    }
    fn open(&self, uri: &str) -> Result<()> {
        self.calls.lock().unwrap().push(("open".into(), json!(uri)));
        if self.fail {
            Err(Failure::Unavailable("fixture".into()))
        } else {
            Ok(())
        }
    }
}
fn item() -> Value {
    json!({"id": QUEUED, "clientUserMessageId": MESSAGE,
        "input": [{"type":"text", "text":TEXT, "text_elements":[]}]})
}
fn list(items: Vec<Value>) -> Value {
    json!({"data":items,"nextCursor":null})
}
fn added() -> Value {
    json!({"queuedSubmission":item()})
}
fn fixture(
    reads: Vec<Result<Value>>,
    add: Result<Value>,
    fail_open: bool,
) -> (FakeRpc, FakeOpener, Calls) {
    let calls = Arc::new(Mutex::new(Vec::new()));
    (
        FakeRpc {
            calls: calls.clone(),
            reads: reads.into(),
            added: Some(add),
        },
        FakeOpener {
            calls: calls.clone(),
            fail: fail_open,
        },
        calls,
    )
}
fn invoke(rpc: &mut FakeRpc, opener: &FakeOpener) -> Result<&'static str> {
    enqueue_with(rpc, opener, THREAD, TEXT, MESSAGE)
}
fn methods(calls: &Calls) -> Vec<String> {
    calls
        .lock()
        .unwrap()
        .iter()
        .map(|(method, _)| method.clone())
        .collect()
}
fn assert_no_wake(calls: &Calls) {
    assert!(!methods(calls).iter().any(|method| method == "open"));
    assert!(methods(calls)
        .iter()
        .all(|method| matches!(method.as_str(), "thread/queue/list" | "thread/queue/add")));
}

#[test]
fn empty_queue_adds_exact_input_once_then_checks_and_requests_wake() {
    let (mut rpc, opener, calls) = fixture(
        vec![Ok(list(vec![])), Ok(list(vec![item()]))],
        Ok(added()),
        false,
    );
    let reason = invoke(&mut rpc, &opener).unwrap();
    assert!(reason.contains("wake requested") && reason.contains("not confirmed"));
    let calls = calls.lock().unwrap();
    assert_eq!(calls.len(), 4);
    assert_eq!(
        calls[0],
        (
            "thread/queue/list".into(),
            json!({"threadId":THREAD,"limit":2})
        )
    );
    assert_eq!(
        calls[1],
        (
            "thread/queue/add".into(),
            json!({"threadId":THREAD,"clientUserMessageId":MESSAGE,"input":[{"type":"text","text":TEXT,"text_elements":[]}]})
        )
    );
    assert_eq!(calls[2], calls[0]);
    assert_eq!(
        calls[3],
        (
            "open".into(),
            json!(format!("codex://threads/wake/{THREAD}"))
        )
    );
}

#[test]
fn existing_queue_and_unverifiable_initial_lists_never_wake() {
    let cases = vec![
        Ok(list(vec![item()])),
        Err(Failure::Unavailable("fixture".into())),
        Ok(json!({"data":[],"nextCursor":"next"})),
        Ok(json!({"data":[],"nextCursor":42})),
        Ok(json!({"data":{},"nextCursor":null})),
        Ok(json!({"nextCursor":null})),
    ];
    for before in cases {
        let (mut rpc, opener, calls) = fixture(vec![before], Ok(added()), false);
        let reason = invoke(&mut rpc, &opener).unwrap();
        assert!(reason.contains("previous queue"));
        assert_eq!(methods(&calls), ["thread/queue/list", "thread/queue/add"]);
        assert_no_wake(&calls);
    }
}

#[test]
fn changed_or_unverifiable_post_add_lists_never_wake() {
    let mut other_id = item();
    other_id["id"] = json!("other");
    let mut other_client = item();
    other_client["clientUserMessageId"] = json!("other");
    let mut other_text = item();
    other_text["input"][0]["text"] = json!("changed");
    let mut extra_part = item();
    extra_part["input"]
        .as_array_mut()
        .unwrap()
        .push(json!({"type":"text","text":"extra"}));
    let cases = vec![
        Err(Failure::Unavailable("fixture".into())),
        Ok(list(vec![])),
        Ok(list(vec![item(), item()])),
        Ok(list(vec![other_id])),
        Ok(list(vec![other_client])),
        Ok(list(vec![other_text])),
        Ok(list(vec![extra_part])),
        Ok(json!({"data":[item()],"nextCursor":"next"})),
        Ok(json!({"data":"wrong","nextCursor":null})),
        Ok(json!({"nextCursor":null})),
    ];
    for after in cases {
        let (mut rpc, opener, calls) = fixture(vec![Ok(list(vec![])), after], Ok(added()), false);
        let reason = invoke(&mut rpc, &opener).unwrap();
        assert!(reason.contains("changed or could not be verified"));
        assert_eq!(
            methods(&calls),
            ["thread/queue/list", "thread/queue/add", "thread/queue/list"]
        );
        assert_no_wake(&calls);
    }
}

#[test]
fn rejected_uncertain_or_malformed_add_never_wakes() {
    let cases = vec![
        Err(Failure::Rejected("fixture".into())),
        Err(Failure::AcceptanceUncertain),
        Ok(json!({})),
        Ok(json!({"queuedSubmission":null})),
        Ok(json!({"queuedSubmission":[]})),
    ];
    for add in cases {
        let (mut rpc, opener, calls) = fixture(vec![Ok(list(vec![]))], add, false);
        assert!(invoke(&mut rpc, &opener).is_err());
        assert_eq!(methods(&calls), ["thread/queue/list", "thread/queue/add"]);
        assert_no_wake(&calls);
    }
}

#[test]
fn unverified_returned_identity_or_input_remains_queued_without_wake() {
    let mut missing_id = item();
    missing_id.as_object_mut().unwrap().remove("id");
    let mut empty_id = item();
    empty_id["id"] = json!("");
    let mut other_client = item();
    other_client["clientUserMessageId"] = json!("other");
    let mut other_text = item();
    other_text["input"][0]["text"] = json!("other");
    let mut extra_key = item();
    extra_key["input"][0]["unknown"] = json!(true);
    for submission in [missing_id, empty_id, other_client, other_text, extra_key] {
        let (mut rpc, opener, calls) = fixture(
            vec![Ok(list(vec![]))],
            Ok(json!({"queuedSubmission":submission})),
            false,
        );
        let reason = invoke(&mut rpc, &opener).unwrap();
        assert!(reason.contains("Queued") && reason.contains("unverified"));
        assert_eq!(methods(&calls), ["thread/queue/list", "thread/queue/add"]);
        assert_no_wake(&calls);
    }
}

#[test]
fn opener_failure_is_still_queued_and_does_not_retry() {
    let (mut rpc, opener, calls) = fixture(
        vec![Ok(list(vec![])), Ok(list(vec![item()]))],
        Ok(added()),
        true,
    );
    let reason = invoke(&mut rpc, &opener).unwrap();
    assert!(
        reason.contains("Queued")
            && reason.contains("wake request failed")
            && reason.contains("not confirmed")
    );
    assert_eq!(
        methods(&calls),
        [
            "thread/queue/list",
            "thread/queue/add",
            "thread/queue/list",
            "open"
        ]
    );
}

#[test]
fn invalid_thread_or_empty_message_id_never_calls_rpc_or_open() {
    for (thread, message_id) in [("not-a-uuid", MESSAGE), (THREAD, "")] {
        let (mut rpc, opener, calls) = fixture(vec![], Ok(added()), false);
        assert!(matches!(
            enqueue_with(&mut rpc, &opener, thread, TEXT, message_id),
            Err(Failure::InvalidInput(_))
        ));
        assert!(calls.lock().unwrap().is_empty());
    }
}

#[test]
fn omitted_optional_next_cursor_is_accepted_as_complete() {
    let (mut rpc, opener, calls) = fixture(
        vec![Ok(json!({"data":[]})), Ok(json!({"data":[item()]}))],
        Ok(added()),
        false,
    );
    assert!(invoke(&mut rpc, &opener)
        .unwrap()
        .contains("wake requested"));
    assert_eq!(
        methods(&calls),
        [
            "thread/queue/list",
            "thread/queue/add",
            "thread/queue/list",
            "open"
        ]
    );
}

#[test]
fn journal_retries_and_restart_never_repeat_queue_write_or_wake() {
    struct Transport {
        rpc: Mutex<FakeRpc>,
        opener: FakeOpener,
    }
    impl CodexTransport for Transport {
        fn deliver(
            &self,
            _: &Path,
            target: &SessionTarget,
            request: &SendRequest,
            _: Duration,
        ) -> Result<Receipt> {
            let message_id = format!("agent-hud:{}", request.request_id);
            let reason = enqueue_with(
                &mut *self.rpc.lock().unwrap(),
                &self.opener,
                THREAD,
                &request.text,
                &message_id,
            )?;
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
    }
    for fail_open in [false, true] {
        let temp = tempfile::tempdir().unwrap();
        let root = temp.path().join("private");
        let paths = || LocalClientPaths {
            claude_channel: root.join("claude"),
            codex_data: root.join("codex"),
            receipts: root.join("receipts"),
        };
        let target = SessionTarget {
            provider: Provider::Codex,
            session_id: THREAD.into(),
            thread_id: Some(THREAD.into()),
            parent_id: None,
        };
        let request = SendRequest {
            provider: Provider::Codex,
            session_id: THREAD.into(),
            request_id: "wake-fixture".into(),
            text: TEXT.into(),
            form: PromptForm::Own,
            operation: Operation::SteerOrEnqueue,
            expected_turn_id: None,
        };
        let mut submission = item();
        submission["clientUserMessageId"] = json!("agent-hud:wake-fixture");
        let (rpc, opener, calls) = fixture(
            vec![Ok(list(vec![])), Ok(list(vec![submission.clone()]))],
            Ok(json!({"queuedSubmission":submission})),
            fail_open,
        );
        let transport = Arc::new(Transport {
            rpc: Mutex::new(rpc),
            opener,
        });
        let service = || {
            LocalClients::with_transport(
                paths(),
                vec![target.clone()],
                transport.clone(),
                Duration::from_secs(1),
            )
            .unwrap()
        };
        {
            let service = service();
            let first = service.send(request.clone()).unwrap();
            assert_eq!(first.state, DeliveryState::Queued);
            assert_eq!(
                serde_json::to_value(service.send(request.clone()).unwrap()).unwrap(),
                serde_json::to_value(first).unwrap()
            );
            let mut edited = request.clone();
            edited.text.push_str(" changed");
            assert_eq!(service.send(edited).unwrap_err(), Failure::IdentityConflict);
        }
        assert_eq!(
            service().send(request).unwrap().state,
            DeliveryState::Queued
        );
        assert_eq!(
            methods(&calls),
            [
                "thread/queue/list",
                "thread/queue/add",
                "thread/queue/list",
                "open"
            ]
        );
    }
}
