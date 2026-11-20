use super::*;
use std::collections::BTreeMap;

fn config() -> StartConfig {
    let home = std::env::temp_dir().join("codex-runtime-policy-fixture");
    StartConfig {
        claude_config: home.join("claude"),
        codex_data: home.join("codex-profile"),
        task_root: home.join("tasks"),
        home,
        claude_executable: None,
        codex_executable: None,
        discover_codex_executable: false,
        antigravity_executable: None,
        claude_desktop: false,
        codex_desktop: false,
        environment: BTreeMap::from([("FIXTURE_VARIABLE".into(), "unchanged".into())]),
    }
}

#[test]
fn old_or_custom_configuration_is_pinned_unless_discovery_is_explicit() {
    let mut value = serde_json::to_value(config()).unwrap();
    value
        .as_object_mut()
        .unwrap()
        .remove("discoverCodexExecutable");
    let mut pinned: StartConfig = serde_json::from_value(value).unwrap();
    assert!(!pinned.discover_codex_executable);
    assert!(pinned.codex_queue().is_none());
    pinned.codex_executable = Some(pinned.home.join("custom/codex.exe"));
    let route = pinned.codex_queue().unwrap();
    assert!(!route.discover_executable);
    assert_eq!(Some(route.executable), pinned.codex_executable);
}

#[test]
fn registered_runtime_can_recover_from_a_temporarily_missing_startup_cli() {
    let mut automatic = config();
    automatic.discover_codex_executable = true;
    let route = automatic.codex_queue().unwrap();
    assert!(route.discover_executable);
    assert!(route.executable.as_os_str().is_empty());
    assert_eq!(route.environment["FIXTURE_VARIABLE"], "unchanged");
}

#[test]
fn selected_runtime_is_pinned_for_remaining_phases_without_changing_context() {
    let mut automatic = config();
    automatic.discover_codex_executable = true;
    automatic.codex_executable = Some(automatic.home.join("retired/codex.exe"));
    let original = automatic.codex_queue().unwrap();
    let selected = automatic.home.join("current/codex.exe");
    let pinned = original.pinned(&selected);
    assert_eq!(pinned.executable, selected);
    assert!(!pinned.discover_executable);
    assert_eq!(pinned.environment, original.environment);
    assert_eq!(pinned.applications, original.applications);
    assert!(original.discover_executable);
    assert_ne!(original.executable, pinned.executable);
    assert_eq!(automatic.codex_data, automatic.home.join("codex-profile"));
}
