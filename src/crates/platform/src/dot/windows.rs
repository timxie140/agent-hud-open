use std::os::windows::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::Command;
pub(super) const SUPPORTED: bool = true;
pub(super) fn data_directory() -> PathBuf {
    let home = std::env::var_os("USERPROFILE")
        .map(PathBuf::from)
        .unwrap_or_default();
    std::env::var_os("LOCALAPPDATA")
        .map(PathBuf::from)
        .unwrap_or_else(|| home.join("AppData/Local"))
        .join("AgentHUDPrivate/dot-client")
}
pub(super) fn helper(executable: &Path) -> Result<PathBuf, String> {
    Ok(executable
        .parent()
        .ok_or("Cannot locate HUD directory")?
        .join("dot/agent-hud-dot.exe"))
}
pub(super) fn hidden(command: &mut Command) {
    command.creation_flags(0x0800_0000);
}
