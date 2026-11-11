//! The one packaged Dot runtime; fixtures replace only this I/O boundary.
use serde_json::Value;
use std::sync::Arc;

pub(crate) type Control = Arc<dyn Fn(&str, Value) -> Result<Value, String> + Send + Sync>;

pub(crate) struct DotPort {
    pub control: Control,
    pub enabled: Arc<dyn Fn() -> bool + Send + Sync>,
}
impl Default for DotPort {
    fn default() -> Self {
        Self {
            control: Arc::new(agent_hud_platform::dot::control),
            enabled: Arc::new(agent_hud_platform::dot::enabled),
        }
    }
}
impl DotPort {
    pub fn call(&self, action: &str, value: Value) -> Result<Value, String> {
        (self.control)(action, value)
    }
    pub fn enabled(&self) -> bool {
        (self.enabled)()
    }
}
