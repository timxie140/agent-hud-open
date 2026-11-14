//! GUI lifetime supervision. CLI transports and demo runs keep their own lifecycle.
#[cfg(not(windows))]
mod unsupported;
#[cfg(windows)]
mod windows;
#[cfg(not(windows))]
use unsupported as platform;
#[cfg(windows)]
use windows as platform;

pub(super) use platform::{entry, exited, ready, user_quit};
