//! Settings → Agents → Dot. No secret is returned to the webview.
use serde_json::Value;

#[tauri::command]
pub async fn native_dot(action: String, arguments: Option<Value>) -> Result<Value, String> {
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
    Ok(result)
}
