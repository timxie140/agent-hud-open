//! Isolated same-user pipes exercise real framing/peer checks, never codex-ipc.
use super::*;
use crate::clients::codex::desktop_io::DesktopIpc;
use serde_json::{json, Value};
use std::{future::Future, path::PathBuf, sync::mpsc, thread};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::windows::named_pipe::{NamedPipeServer, ServerOptions},
};

const THREAD: &str = "00000000-0000-4000-8000-000000000013";
const OWNER: &str = "fixture-owner";
const TEXT: &str = "isolated v13 receiving input";
const TIMEOUT: Duration = Duration::from_secs(10);

fn pipe<F, Fut>(handler: F) -> (DesktopIpc, thread::JoinHandle<()>)
where
    F: FnOnce(NamedPipeServer) -> Fut + Send + 'static,
    Fut: Future<Output = ()>,
{
    let path = PathBuf::from(format!(
        r"\\.\pipe\agenthud-v13-fixture-{}",
        uuid::Uuid::new_v4()
    ));
    let server_path = path.clone();
    let (ready, waiting) = mpsc::channel();
    let worker = thread::spawn(move || {
        tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .unwrap()
            .block_on(async {
                let server = ServerOptions::new()
                    .first_pipe_instance(true)
                    .reject_remote_clients(true)
                    .create(server_path)
                    .unwrap();
                ready.send(()).unwrap();
                tokio::time::timeout(TIMEOUT, async {
                    server.connect().await.unwrap();
                    handler(server).await;
                })
                .await
                .unwrap();
            });
    });
    waiting.recv_timeout(TIMEOUT).unwrap();
    (DesktopIpc::connect(&path, TIMEOUT).unwrap(), worker)
}

async fn read(server: &mut NamedPipeServer) -> Value {
    let mut header = [0; 4];
    server.read_exact(&mut header).await.unwrap();
    let length = u32::from_le_bytes(header) as usize;
    assert!(length > 0 && length < 64 * 1024);
    let mut bytes = vec![0; length];
    server.read_exact(&mut bytes).await.unwrap();
    serde_json::from_slice(&bytes).unwrap()
}

async fn write(server: &mut NamedPipeServer, value: Value) {
    let bytes = serde_json::to_vec(&value).unwrap();
    // Split the frame header, exercising the actual pipe framing reader.
    let header = (bytes.len() as u32).to_le_bytes();
    server.write_all(&header[..2]).await.unwrap();
    server.write_all(&header[2..]).await.unwrap();
    server.write_all(&bytes).await.unwrap();
}

fn state(status: &str) -> Value {
    json!({"id":THREAD, "hostId":"local", "turns":[], "turnHistory":{"kind":"canonical",
        "history":{"generation":1, "isComplete":false, "islands":[{"entries":[{"key":"k","value":"k"}],
            "olderBoundary":{"status":"available"}, "newerBoundary":{"status":"exhausted"}}],
            "entitiesByKey":{"k":{"turnId":"fixture-turn", "status":status, "items":[
                {"type":"userMessage", "id":"native-item", "clientId":"native-client",
                 "content":[{"type":"text", "text":TEXT}]}]}}}}})
}

#[derive(Clone, Copy)]
enum Action {
    Steer,
    Start,
    WrongTurn,
    Rejected,
    Timeout,
}

fn server(
    version: u64,
    state: Value,
    action: Option<Action>,
) -> (DesktopIpc, thread::JoinHandle<()>) {
    pipe(move |mut server| async move {
        let init = read(&mut server).await;
        assert_eq!(init["method"], "initialize");
        assert_eq!(init["version"], 0);
        write(
            &mut server,
            json!({"type":"response", "requestId":init["requestId"],
            "resultType":"success", "result":{"clientId":"fixture-client"}}),
        )
        .await;
        let discovery = read(&mut server).await;
        assert_eq!(discovery["method"], "thread-owner-discovery");
        assert_eq!(discovery["params"]["conversationId"], THREAD);
        write(
            &mut server,
            json!({"type":"response", "requestId":discovery["requestId"],
            "resultType":"success", "handledByClientId":OWNER}),
        )
        .await;
        let follow = read(&mut server).await;
        assert_eq!(follow["method"], "thread-stream-following-changed");
        assert_eq!(follow["targetClientIds"], json!([OWNER]));
        assert_eq!(follow["params"]["following"], true);
        // A foreign owner/host/thread's unsupported event cannot authorize or
        // prevent delivery to the discovered owner of this thread.
        let event = json!({"type":"broadcast", "method":"thread-stream-state-changed",
            "sourceClientId":OWNER, "version":version, "params":{"hostId":"local",
            "conversationId":THREAD, "change":{"type":"snapshot", "revision":1, "conversationState":state}}});
        for field in ["sourceClientId", "hostId", "conversationId"] {
            let mut foreign = event.clone();
            foreign["version"] = json!(99);
            if field == "sourceClientId" {
                foreign[field] = json!("foreign");
            } else {
                foreign["params"][field] = json!("foreign");
            }
            write(&mut server, foreign).await;
        }
        write(&mut server, event).await;
        let unfollow = read(&mut server).await;
        assert_eq!(unfollow["method"], "thread-stream-following-changed");
        assert_eq!(unfollow["params"]["following"], false);
        if let Some(action) = action {
            let request = read(&mut server).await;
            let start = matches!(action, Action::Start);
            assert_eq!(
                request["method"],
                if start {
                    "thread-follower-start-turn"
                } else {
                    "thread-follower-steer-turn"
                }
            );
            assert_eq!(request["version"], if start { 2 } else { 1 });
            assert_eq!(request["targetClientId"], OWNER);
            assert_eq!(request["params"]["conversationId"], THREAD);
            let response = if matches!(action, Action::Rejected) {
                json!({"type":"response", "requestId":request["requestId"],
                    "resultType":"error", "error":"fixture-refusal"})
            } else {
                let result = match action {
                    Action::Start => json!({"turn":{"id":"started-turn"}}),
                    Action::WrongTurn => json!({"turnId":"different-turn"}),
                    _ => json!({"turnId":"fixture-turn"}),
                };
                json!({"type":"response", "requestId":request["requestId"],
                    "resultType":"success", "handledByClientId":OWNER, "result":{"result":result}})
            };
            if !matches!(action, Action::Timeout) {
                write(&mut server, response).await;
            }
        }
        // Refusals, idle decisions and uncertain ACKs must not emit another
        // mutation or a queue submission. The fixture sees EOF, never a retry.
        assert_eq!(server.read(&mut [0]).await.unwrap(), 0);
    })
}

fn deliver(
    version: u64,
    state: Value,
    op: Operation,
    expected: Option<&str>,
    action: Option<Action>,
) -> Result<Option<Receipt>> {
    let (mut connection, worker) = server(version, state, action);
    let target = SessionTarget {
        provider: Provider::Codex,
        session_id: THREAD.into(),
        thread_id: Some(THREAD.into()),
        parent_id: None,
    };
    let request = SendRequest {
        provider: Provider::Codex,
        session_id: THREAD.into(),
        request_id: "fixture-v13".into(),
        text: TEXT.into(),
        form: PromptForm::Labelled,
        operation: op,
        expected_turn_id: expected.map(str::to_owned),
    };
    let timeout = if matches!(action, Some(Action::Timeout)) {
        Duration::from_millis(200)
    } else {
        TIMEOUT
    };
    let result = desktop::deliver_on(&mut connection, &target, &request, THREAD, timeout);
    drop(connection);
    worker.join().unwrap();
    result
}

#[test]
fn windows_pipe_v11_and_v13_steer_active_and_leave_idle_for_queue() {
    assert_eq!(transport::STREAM_VERSIONS, &[11, 13]);
    for version in [11, 13] {
        let receipt = deliver(
            version,
            state("inProgress"),
            Operation::SteerOrEnqueue,
            None,
            Some(Action::Steer),
        )
        .unwrap()
        .unwrap();
        assert_eq!(receipt.state, DeliveryState::Steered);
        assert_eq!(receipt.turn_id.as_deref(), Some("fixture-turn"));
        for status in ["completed", "interrupted"] {
            assert!(deliver(
                version,
                state(status),
                Operation::SteerOrEnqueue,
                None,
                None
            )
            .unwrap()
            .is_none());
        }
    }
    assert_eq!(
        deliver(
            13,
            state("completed"),
            Operation::Automatic,
            None,
            Some(Action::Start)
        )
        .unwrap()
        .unwrap()
        .state,
        DeliveryState::Started
    );
}

#[test]
fn windows_pipe_unknown_overlay_and_incomplete_history_never_start_a_turn() {
    let mut overlay = state("completed");
    overlay["turns"] = json!([{"turnId":"overlay", "status":"inProgress"}]);
    let mut incomplete = state("completed");
    incomplete["turnHistory"]["history"]["islands"][0]["newerBoundary"]["status"] =
        json!("loading");
    for state in [overlay, incomplete] {
        assert_eq!(
            deliver(13, state, Operation::Automatic, None, None).unwrap_err(),
            Failure::Protocol("Desktop state".into())
        );
    }
    assert_eq!(
        deliver(
            14,
            state("inProgress"),
            Operation::SteerOrEnqueue,
            None,
            None
        )
        .unwrap_err(),
        Failure::Protocol("Desktop stream version".into())
    );
}

#[test]
fn windows_pipe_expected_turn_refusal_and_uncertainty_never_retry() {
    assert!(matches!(
        deliver(
            13,
            state("inProgress"),
            Operation::Steer,
            Some("stale-turn"),
            None
        ),
        Err(Failure::Rejected(_))
    ));
    assert_eq!(
        deliver(
            13,
            state("inProgress"),
            Operation::SteerOrEnqueue,
            None,
            Some(Action::WrongTurn)
        )
        .unwrap_err(),
        Failure::AcceptanceUncertain
    );
    assert!(matches!(
        deliver(
            13,
            state("inProgress"),
            Operation::SteerOrEnqueue,
            None,
            Some(Action::Rejected)
        ),
        Err(Failure::Rejected(_))
    ));
    assert_eq!(
        deliver(
            13,
            state("inProgress"),
            Operation::SteerOrEnqueue,
            None,
            Some(Action::Timeout)
        )
        .unwrap_err(),
        Failure::AcceptanceUncertain
    );
}

#[test]
fn windows_pipe_v13_observation_proves_exact_native_input_without_sending() {
    use sha2::{Digest, Sha256};
    let (mut connection, worker) = server(13, state("completed"), None);
    connection
        .request(
            "initialize",
            0,
            "initializing-client",
            None,
            json!({"clientType":"agent-hud"}),
            None,
        )
        .unwrap();
    connection
        .request(
            "thread-owner-discovery",
            1,
            "fixture-client",
            None,
            json!({"hostId":"local","conversationId":THREAD}),
            None,
        )
        .unwrap();
    let state =
        desktop::desktop_snapshot(&mut connection, "fixture-client", OWNER, THREAD).unwrap();
    let hash = format!("{:x}", Sha256::digest(TEXT.as_bytes()));
    let proof = observed::recorded(&state, THREAD, "fixture-v13", &hash).unwrap();
    assert_eq!(proof.thread(), THREAD);
    assert_eq!(proof.turn(), "fixture-turn");
    assert_eq!(proof.text(), TEXT);
    assert!(observed::recorded(&state, THREAD, "fixture-v13", "incorrect").is_none());
    drop(connection);
    worker.join().unwrap();
}
