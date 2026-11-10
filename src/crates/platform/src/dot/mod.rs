//! The packaged Dot sidecar; credentials cross stdin, never process arguments.
use serde_json::{Value, json};
use std::io::{Read, Write};
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

#[cfg(target_os = "macos")]
#[path = "macos.rs"]
mod host;
#[cfg(target_os = "windows")]
#[path = "windows.rs"]
mod host;
#[cfg(target_os = "linux")]
#[path = "linux.rs"]
mod host;

pub const SESSION: &str = "dot:luo";

pub fn enabled() -> bool {
    let folder = if let Some(path) = std::env::var_os("AGENTHUD_DOT_DATA") {
        PathBuf::from(path)
    } else {
        host::data_directory()
    };
    enabled_at(&folder)
}

fn enabled_at(folder: &std::path::Path) -> bool {
    std::fs::read_to_string(folder.join("enabled")).is_ok_and(|value| value == "true")
}

fn helper() -> Result<PathBuf, String> {
    let executable = std::env::current_exe().map_err(|_| "Cannot locate HUD executable")?;
    let path = host::helper(&executable)?;
    if path.is_file() {
        Ok(path)
    } else {
        Err(
            "The packaged Dot runtime is missing; install the complete macOS or Windows build"
                .into(),
        )
    }
}

pub fn control(action: &str, arguments: Value) -> Result<Value, String> {
    if !host::SUPPORTED {
        return Err("Dot's packaged runtime is available on macOS and Windows".into());
    }
    let mut command = Command::new(helper()?);
    command
        .arg("--control-stdin")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
    host::hidden(&mut command);
    let mut child = command
        .spawn()
        .map_err(|_| "Cannot start Dot control runtime")?;
    let bytes = serde_json::to_vec(&json!({"action":action,"arguments":arguments}))
        .map_err(|_| "Invalid Dot control request")?;
    if let Some(mut input) = child.stdin.take() {
        input
            .write_all(&bytes)
            .map_err(|_| "Dot control input failed")?;
    }
    let output = child
        .stdout
        .take()
        .ok_or("Dot control output unavailable")?;
    let reader = std::thread::spawn(move || {
        let mut bytes = Vec::new();
        output
            .take(1_048_577)
            .read_to_end(&mut bytes)
            .map(|_| bytes)
    });
    let deadline = Instant::now() + Duration::from_secs(25);
    loop {
        if child
            .try_wait()
            .map_err(|_| "Dot control process failed")?
            .is_some()
        {
            break;
        }
        if Instant::now() >= deadline {
            let _ = child.kill();
            let _ = child.wait();
            return Err("Dot result is uncertain; do not resend automatically".into());
        }
        std::thread::sleep(Duration::from_millis(20));
    }
    let bytes = reader
        .join()
        .map_err(|_| "Dot output unavailable")?
        .map_err(|_| "Dot output unavailable")?;
    if bytes.len() > 1_048_576 {
        return Err("Dot control response too large".into());
    }
    let result: Value =
        serde_json::from_slice(&bytes).map_err(|_| "Invalid Dot control response")?;
    if let Some(error) = result["error"].as_str() {
        return Err(error.to_owned());
    }
    result
        .get("result")
        .cloned()
        .ok_or_else(|| "Dot result missing".into())
}

pub fn status() -> Value {
    control("status", json!({})).unwrap_or_else(|notice| {
        json!({
            "enabled":false,"running":false,"ready":false,"subscribed":false,
            "hasRuntimeApiKey":false,"notice":notice
        })
    })
}

/// The GUI alone starts this. MCP relay processes never start another tunnel.
pub fn start_with_hud() -> Result<(), String> {
    if !host::SUPPORTED || !enabled() {
        return Ok(());
    }
    let mut command = Command::new(helper()?);
    command
        .args(["--supervise", &std::process::id().to_string()])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    host::hidden(&mut command);
    let mut child = command
        .spawn()
        .map_err(|_| "Cannot start HUD-owned Dot runtime")?;
    std::thread::spawn(move || {
        let _ = child.wait();
    });
    Ok(())
}

#[cfg(test)]
mod tests {
    #[test]
    fn disabled_or_malformed_hint_never_enables_a_runtime() {
        let folder = tempfile::tempdir().unwrap();
        assert!(!super::enabled_at(folder.path()));
        for value in ["false", "", "TRUE", "true\n", "{\"enabled\":true}"] {
            std::fs::write(folder.path().join("enabled"), value).unwrap();
            assert!(!super::enabled_at(folder.path()));
        }
        std::fs::write(folder.path().join("enabled"), "true").unwrap();
        assert!(super::enabled_at(folder.path()));
    }
}
