use super::*;
use std::{cell::RefCell, collections::VecDeque};

fn test_spawn(
    original: &Path,
    discover: bool,
    resolutions: Vec<Result<PathBuf>>,
    launches: Vec<std::io::Result<u8>>,
) -> (Result<(u8, PathBuf)>, Vec<String>) {
    let events = RefCell::new(Vec::new());
    let mut resolutions: VecDeque<_> = resolutions.into();
    let mut launches: VecDeque<_> = launches.into();
    let result = spawn_with(
        original,
        discover,
        || {
            events.borrow_mut().push("resolve".into());
            resolutions.pop_front().expect("unexpected resolve")
        },
        |path| {
            events
                .borrow_mut()
                .push(format!("spawn:{}", path.display()));
            launches.pop_front().expect("unexpected spawn")
        },
    );
    assert!(resolutions.is_empty(), "unused resolution fixture");
    assert!(launches.is_empty(), "unused launch fixture");
    (result, events.into_inner())
}
fn path(name: &str) -> PathBuf {
    PathBuf::from(name)
}
fn err(code: i32) -> std::io::Error {
    std::io::Error::from_raw_os_error(code)
}

#[test]
fn automatic_discovery_uses_current_runtime_on_each_operation() {
    let old = path("old.exe");
    let new = path("new.exe");
    let newer = path("newer.exe");
    for current in [&old, &new, &newer] {
        let (result, events) = test_spawn(&old, true, vec![Ok(current.clone())], vec![Ok(7)]);
        assert_eq!(result.unwrap(), (7, current.clone()));
        assert_eq!(events, ["resolve", &format!("spawn:{}", current.display())]);
    }
}

#[test]
fn fixed_custom_path_never_resolves_even_on_not_found() {
    let custom = path("custom.exe");
    for launch in [Ok(1), Err(err(2)), Err(err(3)), Err(err(5))] {
        let (result, events) = test_spawn(&custom, false, vec![], vec![launch]);
        assert_eq!(events, ["spawn:custom.exe"]);
        if let Ok(actual) = result {
            assert_eq!(actual, (1, custom.clone()));
        }
    }
}

#[test]
fn only_not_found_allows_one_refresh_and_retry() {
    for code in [2, 3] {
        let (result, events) = test_spawn(
            Path::new("stale.exe"),
            true,
            vec![Ok(path("old.exe")), Ok(path("new.exe"))],
            vec![Err(err(code)), Ok(9)],
        );
        assert_eq!(result.unwrap(), (9, path("new.exe")));
        assert_eq!(
            events,
            ["resolve", "spawn:old.exe", "resolve", "spawn:new.exe"]
        );
    }
    for code in [5, 32, 87] {
        let (result, events) = test_spawn(
            Path::new("stale.exe"),
            true,
            vec![Ok(path("old.exe"))],
            vec![Err(err(code))],
        );
        assert!(result.is_err());
        assert_eq!(events, ["resolve", "spawn:old.exe"]);
    }
}

#[test]
fn unchanged_resolution_and_second_spawn_failure_stop_without_further_retry() {
    let (result, events) = test_spawn(
        Path::new("ignored.exe"),
        true,
        vec![Ok(path("old.exe")), Ok(path("old.exe"))],
        vec![Err(err(2))],
    );
    assert!(result.is_err());
    assert_eq!(events, ["resolve", "spawn:old.exe", "resolve"]);

    let (result, events) = test_spawn(
        Path::new("ignored.exe"),
        true,
        vec![Ok(path("old.exe")), Ok(path("new.exe"))],
        vec![Err(err(3)), Err(err(2))],
    );
    assert!(result.is_err());
    assert_eq!(
        events,
        ["resolve", "spawn:old.exe", "resolve", "spawn:new.exe"]
    );
}

#[test]
fn resolution_failure_never_spawns_an_unresolved_path() {
    let unavailable = || Failure::Unavailable("fixture".into());
    let (result, events) = test_spawn(Path::new("old.exe"), true, vec![Err(unavailable())], vec![]);
    assert!(result.is_err());
    assert_eq!(events, ["resolve"]);
    let (result, events) = test_spawn(
        Path::new("old.exe"),
        true,
        vec![Ok(path("old.exe")), Err(unavailable())],
        vec![Err(err(2))],
    );
    assert!(result.is_err());
    assert_eq!(events, ["resolve", "spawn:old.exe", "resolve"]);
}

#[test]
fn empty_placeholder_auto_route_uses_discovered_path() {
    let (result, events) = test_spawn(
        Path::new(""),
        true,
        vec![Ok(path("installed.exe"))],
        vec![Ok(1)],
    );
    assert_eq!(result.unwrap(), (1, path("installed.exe")));
    assert_eq!(events, ["resolve", "spawn:installed.exe"]);
}
