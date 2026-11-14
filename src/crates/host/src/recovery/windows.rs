//! Private per-run kernel events shared only with our verified same-user monitor.
use serde::Deserialize;
use std::{
    env,
    ffi::c_void,
    os::windows::{
        io::{AsRawHandle, FromRawHandle, OwnedHandle},
        process::CommandExt,
    },
    path::{Path, PathBuf},
    process::{Command, Stdio},
    sync::{Arc, OnceLock},
};

mod identity;
const CONTEXT: &str = "AGENTHUD_RECOVERY_CONTEXT";
const EVENT_ACCESS: u32 = 0x0010_0002; // SYNCHRONIZE | EVENT_MODIFY_STATE.
static CLIENT: OnceLock<Arc<Client>> = OnceLock::new();

#[link(name = "kernel32")]
extern "system" {
    fn OpenEventW(access: u32, inherit: i32, name: *const u16) -> *mut c_void;
    fn SetEvent(event: *mut c_void) -> i32;
    fn WaitForMultipleObjects(
        count: u32,
        handles: *const *mut c_void,
        all: i32,
        timeout: u32,
    ) -> u32;
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct Context {
    run_id: String,
    monitor_pid: u32,
    monitor_created: String,
    gui_path: PathBuf,
    ready_event: String,
    stop_event: String,
    quit_event: String,
    maintenance_event: String,
}
struct Client {
    _monitor: OwnedHandle,
    ready: OwnedHandle,
    stop: OwnedHandle,
    quit: OwnedHandle,
    _maintenance: OwnedHandle,
}

fn open_event(name: &str) -> Result<OwnedHandle, String> {
    let wide: Vec<u16> = name.encode_utf16().chain(Some(0)).collect();
    let event = unsafe { OpenEventW(EVENT_ACCESS, 0, wide.as_ptr()) };
    if event.is_null() {
        return Err("Recovery event unavailable".into());
    }
    Ok(unsafe { OwnedHandle::from_raw_handle(event) })
}

fn attach(helper: &Path) -> Result<(), String> {
    let raw = env::var(CONTEXT).map_err(|_| "Recovery child context missing")?;
    // Startup is still single-threaded; do not leak the context into other clients.
    env::remove_var(CONTEXT);
    if raw.len() > 8192 {
        return Err("Recovery context too large".into());
    }
    let context: Context = serde_json::from_str(&raw).map_err(|_| "Invalid recovery context")?;
    if context.run_id.len() != 32 || !context.run_id.bytes().all(|b| b.is_ascii_hexdigit()) {
        return Err("Invalid recovery run identity".into());
    }
    let executable = env::current_exe().map_err(|_| "GUI identity unavailable")?;
    if !identity::same_path(&executable, &context.gui_path) {
        return Err("Recovery GUI identity mismatch".into());
    }
    let monitor = identity::monitor(context.monitor_pid, &context.monitor_created, helper)?;
    let prefix = format!("Local\\AgentHUDRecovery-{}-", context.run_id);
    for (name, suffix) in [
        (&context.ready_event, "ready"),
        (&context.stop_event, "stop"),
        (&context.quit_event, "quit"),
        (&context.maintenance_event, "maintenance"),
    ] {
        if *name != format!("{prefix}{suffix}") {
            return Err("Recovery event identity mismatch".into());
        }
    }
    let client = Client {
        _monitor: monitor,
        ready: open_event(&context.ready_event)?,
        stop: open_event(&context.stop_event)?,
        quit: open_event(&context.quit_event)?,
        _maintenance: open_event(&context.maintenance_event)?,
    };
    CLIENT
        .set(Arc::new(client))
        .map_err(|_| "Recovery already attached".into())
}

pub(crate) fn entry(arguments: &[String], demo: bool, options: &crate::HostOptions) -> Option<i32> {
    if demo {
        return None;
    }
    let executable = match env::current_exe() {
        Ok(path) => path,
        Err(_) => return Some(2),
    };
    let helper = executable.parent()?.join("agent-hud-recovery.exe");
    let helper = helper.is_file().then_some(helper);
    if arguments.iter().any(|arg| arg == "--recovery-child") {
        let result = helper
            .as_deref()
            .ok_or_else(|| "Recovery helper missing".into())
            .and_then(attach);
        return result.err().map(|error: String| {
            eprintln!("Agent HUD recovery: {error}");
            2
        });
    }
    let Some(helper) = helper else {
        eprintln!("Agent HUD recovery: helper missing; this development launch is not supervised");
        return None;
    };
    // Unbundled builds keep resources in another directory; do not supervise them.
    if !identity::same_path(helper.parent()?, executable.parent()?) {
        return None;
    }
    // Preserve second-launch focus before asking the monitor's singleton gate.
    // Release a fresh claim before spawning: only the actual GUI owns collection.
    match crate::instance::claim(options.canonical_executable.is_some()) {
        crate::instance::Launch::Run(locks) => drop(locks),
        crate::instance::Launch::HandOver(lock) => {
            if !agent_hud_runtime::instance::hand_over(&lock) {
                crate::instance::refuse(None);
            }
            return Some(0);
        }
        crate::instance::Launch::Refused(holder) => {
            crate::instance::refuse(holder.as_deref());
            return Some(0);
        }
        crate::instance::Launch::Unavailable(error) => {
            crate::instance::unavailable(&error);
            return Some(2);
        }
    }
    let result = Command::new(helper)
        .arg("--run")
        .arg(&executable)
        .arg("--")
        .args(arguments.iter().skip(1))
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .creation_flags(0x0800_0000)
        .spawn();
    Some(match result {
        Ok(_) => 0,
        Err(error) => {
            eprintln!("Agent HUD recovery could not start: {error}");
            2
        }
    })
}

pub(crate) fn ready(app: tauri::AppHandle) {
    let Some(client) = CLIENT.get().cloned() else {
        return;
    };
    let listener = client.clone();
    let result = std::thread::Builder::new()
        .name("agenthud-recovery-stop".into())
        .spawn(move || {
            let handles = [listener.quit.as_raw_handle(), listener.stop.as_raw_handle()];
            if unsafe { WaitForMultipleObjects(2, handles.as_ptr(), 0, u32::MAX) } == 0 {
                unsafe {
                    SetEvent(listener.stop.as_raw_handle());
                }
                app.exit(0);
            }
        });
    if let Err(error) = result {
        eprintln!("Agent HUD recovery listener failed: {error}");
        return;
    }
    if unsafe { SetEvent(client.ready.as_raw_handle()) } == 0 {
        eprintln!("Agent HUD recovery: readiness signal failed");
    }
}

pub(crate) fn user_quit() {
    if let Some(client) = CLIENT.get() {
        if unsafe { SetEvent(client.stop.as_raw_handle()) } == 0 {
            eprintln!("Agent HUD recovery: stop signal failed");
        }
    }
}
pub(crate) fn exited() {
    user_quit();
}
