use super::*;
#[test]
fn observation_uses_existing_owner_read_only_and_ignores_wrong_sender() {
    use std::{
        io::{Read, Write},
        os::unix::net::{UnixListener, UnixStream},
    };
    fn read(socket: &mut UnixStream) -> Value {
        let mut size = [0; 4];
        socket.read_exact(&mut size).unwrap();
        let mut data = vec![0; u32::from_le_bytes(size) as usize];
        socket.read_exact(&mut data).unwrap();
        serde_json::from_slice(&data).unwrap()
    }
    fn write(socket: &mut UnixStream, value: Value) {
        let bytes = serde_json::to_vec(&value).unwrap();
        socket
            .write_all(&(bytes.len() as u32).to_le_bytes())
            .unwrap();
        socket.write_all(&bytes).unwrap();
    }
    let dir = tempfile::tempdir().unwrap();
    std::fs::create_dir_all(dir.path().join("ipc")).unwrap();
    let listener = UnixListener::bind(dir.path().join("ipc/ipc.sock")).unwrap();
    let worker = std::thread::spawn(move || {
        let (mut socket, _) = listener.accept().unwrap();
        socket
            .set_read_timeout(Some(Duration::from_secs(2)))
            .unwrap();
        let init = read(&mut socket);
        assert_eq!(init["method"], "initialize");
        write(
            &mut socket,
            json!({"type":"response","requestId":init["requestId"],"resultType":"success","result":{"clientId":"fixture-client"}}),
        );
        let discover = read(&mut socket);
        assert_eq!(discover["params"]["conversationId"], THREAD);
        write(
            &mut socket,
            json!({"type":"response","requestId":discover["requestId"],"resultType":"success","handledByClientId":"actual-owner","result":{}}),
        );
        let follow = read(&mut socket);
        assert_eq!(follow["params"]["following"], true);
        for (owner, conversation) in [
            ("wrong-owner", THREAD),
            ("actual-owner", "wrong-thread"),
            ("actual-owner", THREAD),
        ] {
            write(
                &mut socket,
                json!({"type":"broadcast","method":"thread-stream-state-changed","version":11,
                "sourceClientId":owner,"params":{"hostId":"local","conversationId":conversation,
                "change":{"type":"snapshot","conversationState":state()}}}),
            );
        }
        assert_eq!(read(&mut socket)["params"]["following"], false);
    });
    let target = SessionTarget {
        provider: Provider::Codex,
        session_id: THREAD.into(),
        thread_id: Some(THREAD.into()),
        parent_id: None,
    };
    assert!(observe(
        dir.path(),
        &target,
        "m-fixture",
        &hash(),
        Duration::from_secs(2)
    )
    .unwrap()
    .is_some());
    worker.join().unwrap();
}
