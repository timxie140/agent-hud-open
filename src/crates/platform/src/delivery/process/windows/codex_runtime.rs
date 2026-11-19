//! Resolve auto-discovered runtimes per operation, before any protocol input.
//! A custom executable is never replaced. Retry is confined to CreateProcess.
use super::*;
use std::path::Path;

pub(in crate::delivery::process) fn spawn_codex(
    executable: &Path,
    discover: bool,
    environment: &BTreeMap<String, String>,
    spawn: impl FnMut(&Path) -> std::io::Result<Child>,
) -> Result<(Child, PathBuf)> {
    spawn_with(
        executable,
        discover,
        || crate::os::discover_live_codex(environment).map_err(Failure::Unavailable),
        spawn,
    )
}

fn spawn_with<T>(
    executable: &Path,
    discover: bool,
    mut resolve: impl FnMut() -> Result<PathBuf>,
    mut spawn: impl FnMut(&Path) -> std::io::Result<T>,
) -> Result<(T, PathBuf)> {
    let selected = if discover {
        resolve()?
    } else {
        executable.to_path_buf()
    };
    match spawn(&selected) {
        Ok(child) => Ok((child, selected)),
        Err(error) if discover && matches!(error.raw_os_error(), Some(2 | 3)) => {
            // No child/initialize/thread/start/queue/add exists at this boundary.
            // An update between discovery and CreateProcess permits one refresh.
            let refreshed = resolve()?;
            if refreshed == selected {
                return Err(error.into());
            }
            Ok((spawn(&refreshed)?, refreshed))
        }
        Err(error) => Err(error.into()),
    }
}

#[cfg(test)]
#[path = "codex_runtime_tests.rs"]
mod tests;
