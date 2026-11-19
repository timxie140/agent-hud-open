use super::*;

fn fixture() -> (tempfile::TempDir, PathBuf) {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path().join("package");
    fs::create_dir_all(&root).unwrap();
    (temp, root)
}
fn make_app(root: &Path, directory: &str, name: &str) -> PathBuf {
    let folder = root.join(directory);
    fs::create_dir_all(folder.join("resources")).unwrap();
    fs::write(folder.join(name), b"fixture only").unwrap();
    let cli = folder.join("resources/codex.exe");
    fs::write(&cli, b"fixture only; never executed").unwrap();
    cli
}
fn application(entry: &str) -> String {
    format!(r#"<Application Id="test" Executable="{entry}"/>"#)
}
fn manifest(body: &str) -> String {
    format!("<Package><Applications>{body}</Applications></Package>")
}

#[test]
fn accepts_registered_relative_application_and_bom_whitespace() {
    let (_temp, root) = fixture();
    let cli = make_app(&root, "app", "Codex.exe");
    let xml = format!("\u{feff}  \n{}", manifest(&application(r"app\Codex.exe")));
    assert_eq!(manifest_engine(&root, &xml).unwrap(), cli);
}

#[test]
fn rejects_external_entity_and_doctype() {
    let (_temp, root) = fixture();
    make_app(&root, "app", "Codex.exe");
    let xml = format!(
        r#"<!DOCTYPE Package [<!ENTITY injected SYSTEM "file:///sensitive">]>{}"#,
        manifest(&application(r"app\Codex.exe"))
    );
    assert!(manifest_engine(&root, &xml).is_err());
}

#[test]
fn rejects_absolute_drive_relative_and_parent_traversal_entries() {
    let (_temp, root) = fixture();
    make_app(&root, "app", "Codex.exe");
    for entry in [
        r"C:\outside\app.exe",
        r"C:app\Codex.exe",
        r"\outside\app.exe",
        r"app\..\app\Codex.exe",
        r"..\package\app\Codex.exe",
    ] {
        assert!(
            manifest_engine(&root, &manifest(&application(entry))).is_err(),
            "accepted {entry}"
        );
    }
}

#[test]
fn rejects_missing_application_cli_or_malformed_manifest() {
    let (_temp, root) = fixture();
    assert!(manifest_engine(&root, &manifest("")).is_err());
    let xml = manifest(&application(r"app\Codex.exe"));
    assert!(manifest_engine(&root, &xml).is_err());
    fs::create_dir_all(root.join("app/resources")).unwrap();
    fs::write(root.join("app/Codex.exe"), b"fixture").unwrap();
    assert!(manifest_engine(&root, &xml).is_err());
    assert!(manifest_engine(&root, "<Package><Application").is_err());
}

#[test]
fn duplicate_same_directory_deduplicates_but_distinct_directories_fail_closed() {
    let (_temp, root) = fixture();
    let cli = make_app(&root, "app", "Codex.exe");
    fs::write(root.join("app/Another.exe"), b"fixture").unwrap();
    let repeated = format!(
        "{}{}",
        application(r"app\Codex.exe"),
        application(r"app\Another.exe")
    );
    assert_eq!(manifest_engine(&root, &manifest(&repeated)).unwrap(), cli);
    make_app(&root, "other", "Codex.exe");
    let multiple = format!(
        "{}{}",
        application(r"app\Codex.exe"),
        application(r"other\Codex.exe")
    );
    assert!(manifest_engine(&root, &manifest(&multiple)).is_err());
}

#[test]
fn owned_name_requires_in_bounds_aligned_nonempty_nul_terminated_utf16() {
    let buffer = [65u16, 66, 0, 88, 0];
    assert_eq!(
        owned_name(buffer.as_ptr(), &buffer).unwrap(),
        vec![65, 66, 0]
    );
    assert_eq!(
        owned_name(buffer.as_ptr().wrapping_add(3), &buffer).unwrap(),
        vec![88, 0]
    );
    assert!(owned_name(std::ptr::null(), &buffer).is_err());
    assert!(owned_name(buffer.as_ptr().wrapping_add(2), &buffer).is_err());
    assert!(owned_name(buffer.as_ptr().wrapping_add(buffer.len()), &buffer).is_err());
    assert!(owned_name(buffer.as_ptr().wrapping_add(buffer.len() + 1), &buffer).is_err());
    let odd = buffer.as_ptr().cast::<u8>().wrapping_add(1).cast::<u16>();
    assert!(owned_name(odd, &buffer).is_err());
    let unterminated = [65u16, 66];
    assert!(owned_name(unterminated.as_ptr(), &unterminated).is_err());
    assert!(owned_name([0u16].as_ptr(), &[]).is_err());
}
