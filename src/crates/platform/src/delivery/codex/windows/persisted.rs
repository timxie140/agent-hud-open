//! Read a persisted Codex input via App Server without starting or loading its thread.
use super::*;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

pub(in crate::delivery::codex) fn persisted_input(
    route: Option<&QueueRoute>,
    data: &Path,
    target: &SessionTarget,
    request: &str,
    fingerprint: &str,
    timeout: Duration,
) -> Result<Option<ReceivedInput>> {
    let Some((route, thread)) = route.filter(|route| route.discover_executable).zip(
        target
            .thread_id
            .as_deref()
            .filter(|thread| valid_uuid(thread)),
    ) else {
        return Ok(None);
    };
    let mut server = process::StdioServer::open_route(route, data, timeout)?;
    let result = server.request(
        "thread/turns/list",
        json!({"threadId":thread,"limit":16,"sortDirection":"desc","itemsView":"full"}),
    )?;
    Ok(recorded(&result, thread, request, fingerprint))
}

fn recorded(
    result: &Value,
    thread: &str,
    request: &str,
    fingerprint: &str,
) -> Option<ReceivedInput> {
    let expected = format!("agent-hud:{request}");
    let mut found = None;
    for turn in result["data"].as_array()? {
        if !matches!(turn["status"].as_str(), Some("completed" | "inProgress")) {
            continue;
        }
        let turn_id = turn["id"].as_str().filter(|id| !id.is_empty())?;
        for item in turn["items"].as_array()? {
            if item["type"] != "userMessage" {
                continue;
            }
            let Some(parts) = item["content"]
                .as_array()
                .filter(|parts| parts.len() == 1 && parts[0]["type"] == "text")
            else {
                continue;
            };
            let Some(text) = parts[0]["text"].as_str() else {
                continue;
            };
            if format!("{:x}", Sha256::digest(text.trim().as_bytes())) != fingerprint {
                continue;
            }
            let id = item["id"].as_str().filter(|id| !id.is_empty())?;
            if found.is_some()
                || (id.starts_with("agent-hud:") && id != expected)
                || ["clientUserMessageId", "clientId"].iter().any(|field| {
                    item[*field].as_str().is_some_and(|id| {
                        (*field == "clientUserMessageId" || id.starts_with("agent-hud:"))
                            && id != expected
                    })
                })
            {
                return None;
            }
            found = Some(ReceivedInput {
                thread: thread.into(),
                turn: turn_id.into(),
                text: text.into(),
            });
        }
    }
    found
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_a_unique_native_input_may_confirm() {
        let text = "[Agent HUD · Dot; message_id=m-dot-11111111]\nfixture";
        let fingerprint = format!("{:x}", Sha256::digest(text));
        let input = json!({"type":"userMessage","id":"native-input","content":[{"type":"text","text":text}]});
        let response = |items: Vec<Value>| json!({"data":[{"id":"original-turn","status":"completed","items":items}]});
        let check = |items| {
            recorded(
                &response(items),
                "original-thread",
                "m-dot-11111111",
                &fingerprint,
            )
        };
        assert_eq!(check(vec![input.clone()]).unwrap().turn(), "original-turn");
        assert!(check(vec![input.clone(), input.clone()]).is_none());
        let mut conflict = input.clone();
        conflict["clientUserMessageId"] = json!("agent-hud:wrong");
        assert!(check(vec![conflict]).is_none());
        let mut optimistic = input;
        optimistic["type"] = json!("queuedSubmission");
        assert!(check(vec![optimistic]).is_none());
    }
}
