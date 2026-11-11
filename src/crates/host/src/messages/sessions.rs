//! Messaging can still reach a loaded Harness chat older than the HUD's
//! recent display window. Read cached session facts, never scan or open chats.
use serde_json::{json, Value};
use std::{collections::HashSet, sync::Arc};

pub(super) fn for_messages(
    snapshot: Arc<Value>,
    query: impl Fn(&str, Value) -> Result<Value, String>,
) -> Arc<Value> {
    if snapshot["sessionScope"] != "recent" {
        return snapshot;
    }
    let mut rows = snapshot["sessions"].as_array().cloned().unwrap_or_default();
    let mut known: HashSet<String> = rows
        .iter()
        .filter_map(|row| row["id"].as_str().map(str::to_owned))
        .collect();
    let mut offset = 0;
    for _ in 0..10 {
        let Ok(page) = query(
            "sessions",
            json!({"source":"deepseek","scope":"all","rootsOnly":true,"limit":200,"offset":offset}),
        ) else {
            return snapshot;
        };
        let Some(items) = page["items"].as_array() else {
            return snapshot;
        };
        for row in items {
            if row["source"] != "deepseek" || !row["parentId"].is_null() {
                continue;
            }
            if let Some(id) = row["id"].as_str() {
                if known.insert(id.to_owned()) {
                    rows.push(row.clone());
                }
            }
        }
        let Some(next) = page["nextOffset"].as_u64() else {
            let mut expanded = snapshot.as_ref().clone();
            expanded["sessions"] = json!(rows);
            return Arc::new(expanded);
        };
        if next <= offset {
            return snapshot;
        }
        offset = next;
    }
    // A malformed or unbounded page sequence cannot expand the target set.
    snapshot
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::Cell;

    #[test]
    fn old_harness_roots_remain_message_targets_without_changing_the_display() {
        let snapshot = Arc::new(json!({"sessionScope":"recent","sessions":[
            {"id":"codex-current","source":"codex","state":"running"},
            {"id":"deepseek:current","source":"deepseek","state":"running"}]}));
        let calls = Cell::new(0);
        let expanded = for_messages(snapshot.clone(), |method, params| {
            assert_eq!(method, "sessions");
            assert_eq!(params["source"], "deepseek");
            assert_eq!(params["scope"], "all");
            assert_eq!(params["rootsOnly"], true);
            let page = calls.get();
            calls.set(page + 1);
            Ok(if page == 0 {
                json!({"items":[{"id":"deepseek:current","source":"deepseek","state":"idle"},
                    {"id":"deepseek:old","source":"deepseek","state":"idle","parentId":null}],"nextOffset":200})
            } else {
                assert_eq!(params["offset"], 200);
                json!({"items":[{"id":"deepseek:child","source":"deepseek","parentId":"parent"},
                    {"id":"codex-other","source":"codex"}],"nextOffset":null})
            })
        });
        assert_eq!(calls.get(), 2);
        assert_eq!(snapshot["sessions"].as_array().unwrap().len(), 2);
        assert_eq!(expanded["sessions"].as_array().unwrap().len(), 3);
        assert_eq!(expanded["sessions"][1]["state"], "running");
        assert_eq!(expanded["sessions"][2]["id"], "deepseek:old");
    }

    #[test]
    fn query_failure_keeps_only_the_original_targets() {
        let snapshot = Arc::new(json!({"sessionScope":"recent","sessions":[]}));
        let expanded = for_messages(snapshot.clone(), |_, _| Err("unavailable".into()));
        assert!(Arc::ptr_eq(&snapshot, &expanded));
    }
}
