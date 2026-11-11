//! Settings → Agents → Dot. No secret is returned to the webview.
use serde_json::Value;
use std::sync::{Arc, PoisonError};
use tauri::Manager;

/// The shared HUD snapshot contains connection flags only. Settings retain
/// their private form fields; tunnel IDs, proxy and keys never enter it.
pub(crate) fn project(snapshot: &mut Value, cached: Option<&Value>) {
    if snapshot["mode"] == "demo" {
        return;
    }
    let supported = agent_hud_runtime::dot::supported();
    let enabled = agent_hud_runtime::dot::enabled();
    let status = public_status(supported, enabled, cached);
    snapshot["connection"]["dot"] = status.clone();
    if let Some(providers) = snapshot["providers"].as_array_mut() {
        providers.retain(|p| p["id"] != "dot");
        if supported {
            providers.push(serde_json::json!({"id":"dot","name":"Dot","detected":true,
                "enabled":enabled,"notice":null,"sessions":if status["subscribed"] == true {1} else {0},
                "dataStatus":"detection-only"}));
        }
    }
}

fn public_status(supported: bool, enabled: bool, cached: Option<&Value>) -> Value {
    serde_json::json!({"supported":supported,"enabled":enabled,
        "running":enabled && cached.is_some_and(|s| s["running"] == true),
        "ready":enabled && cached.is_some_and(|s| s["ready"] == true),
        "subscribed":enabled && cached.is_some_and(|s| s["subscribed"] == true)})
}

fn publish(app: &tauri::AppHandle, status: &Value) {
    let service = app.state::<crate::service::Service>();
    let mut backend = service
        .backend
        .lock()
        .unwrap_or_else(PoisonError::into_inner);
    let Some(previous) = backend.snapshot.as_ref() else {
        return;
    };
    let mut next = previous.as_ref().clone();
    project(&mut next, Some(status));
    if &next != previous.as_ref() {
        backend.snapshot = Some(Arc::new(next));
        backend.publish_snapshot(app);
    }
}

pub(crate) fn refresh(app: &tauri::AppHandle) {
    if app.state::<super::AppState>().demo {
        return;
    }
    let status = if agent_hud_runtime::dot::supported() && agent_hud_runtime::dot::enabled() {
        agent_hud_runtime::dot::status()
    } else {
        serde_json::json!({})
    };
    publish(app, &status);
}

#[tauri::command]
pub async fn native_dot(
    app: tauri::AppHandle,
    action: String,
    arguments: Option<Value>,
) -> Result<Value, String> {
    if app.state::<super::AppState>().demo {
        return Err("Dot connection settings are not available in demo mode".into());
    }
    if !matches!(action.as_str(), "status" | "configure") {
        return Err("Unknown Dot settings operation".into());
    }
    let configured = action == "configure";
    let result = tauri::async_runtime::spawn_blocking(move || {
        agent_hud_runtime::dot::control(&action, arguments.unwrap_or_else(|| serde_json::json!({})))
    })
    .await
    .map_err(|_| "Dot settings request failed")??;
    if configured {
        agent_hud_runtime::dot::start_with_hud()?;
    }
    publish(&app, &result);
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn shared_snapshot_has_only_public_flags_and_cannot_keep_disabled_connection() {
        let private = serde_json::json!({"running":true,"ready":true,"subscribed":true,
            "runtimeApiKey":"fixture-private-key","tunnelId":"fixture-private-id",
            "proxy":"fixture-private-proxy","notice":"fixture-private-notice"});
        let enabled = public_status(true, true, Some(&private));
        assert_eq!(enabled.as_object().unwrap().len(), 5);
        assert!(!enabled.to_string().contains("fixture-private"));
        assert_eq!(enabled["subscribed"], true);
        let disabled = public_status(true, false, Some(&private));
        for key in ["running", "ready", "subscribed"] {
            assert_eq!(disabled[key], false);
        }
    }
}
