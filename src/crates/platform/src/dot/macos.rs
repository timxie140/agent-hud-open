use std::path::{Path, PathBuf};
use std::process::Command;
pub(super) const SUPPORTED: bool = true;
pub(super) fn data_directory() -> PathBuf {
    std::env::var_os("HOME")
        .map(PathBuf::from)
        .unwrap_or_default()
        .join("Library/Application Support/AgentHUDPrivate/dot-client")
}
pub(super) fn helper(executable: &Path) -> Result<PathBuf, String> {
    let folder = executable.parent().ok_or("Cannot locate HUD directory")?;
    Ok(if folder.file_name().is_some_and(|name| name == "MacOS") {
        folder.join("../Resources/dot/agent-hud-dot")
    } else {
        folder.join("dot/agent-hud-dot")
    })
}
pub(super) fn hidden(_: &mut Command) {}
