//! Explicit unsupported secure-store/lifecycle capability on Linux.
use std::path::{Path, PathBuf};
use std::process::Command;
pub(super) const SUPPORTED: bool = false;
pub(super) fn data_directory() -> PathBuf {
    PathBuf::new()
}
pub(super) fn helper(_: &Path) -> Result<PathBuf, String> {
    Err("Dot's packaged runtime is available on macOS and Windows".into())
}
pub(super) fn hidden(_: &mut Command) {}
