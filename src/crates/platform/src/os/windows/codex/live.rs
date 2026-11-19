//! Current-user MSIX discovery through native APIs, without a shell or TTL.
//! No unmatched old runtime cache or alternative PATH CLI is used in this mode.
use super::*;
use std::{collections::BTreeMap, ffi::OsString, os::windows::ffi::OsStringExt};
use windows_sys::Win32::Storage::Packaging::Appx::{
    FindPackagesByPackageFamily, GetPackagePathByFullName,
};

const UNAVAILABLE: &str = "Current registered Codex runtime unavailable; no input submitted";

pub(crate) fn tracks_registered_codex() -> bool {
    // An indeterminate registration must not pin a possibly stale path forever.
    // A genuine standalone CLI installation retains its original fixed routing.
    registered_root().map(|root| root.is_some()).unwrap_or(true)
}

pub(crate) fn discover_live_codex(
    _overrides: &BTreeMap<String, String>,
) -> Result<PathBuf, String> {
    let root = registered_root()?.ok_or(UNAVAILABLE)?;
    let path = root.join("AppxManifest.xml");
    if fs::metadata(&path).map_err(|_| UNAVAILABLE)?.len() > 1024 * 1024 {
        return Err(UNAVAILABLE.into());
    }
    let xml = fs::read_to_string(path).map_err(|_| UNAVAILABLE)?;
    manifest_engine(&root, &xml)
}

fn registered_root() -> Result<Option<PathBuf>, String> {
    let family: Vec<u16> = "OpenAI.Codex_2p2nqsd0c76g0\0".encode_utf16().collect();
    let (mut count, mut size) = (0, 0);
    let code = unsafe {
        FindPackagesByPackageFamily(
            family.as_ptr(),
            0x10,
            &mut count,
            std::ptr::null_mut(),
            &mut size,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
        )
    };
    if code == 0 && count == 0 {
        return Ok(None);
    }
    if code != 122 || count != 1 || size == 0 || size > 65536 {
        return Err(UNAVAILABLE.into());
    }
    let mut buffer = vec![0u16; size as usize];
    let mut names = [std::ptr::null_mut()];
    let mut properties = [0u32];
    let code = unsafe {
        FindPackagesByPackageFamily(
            family.as_ptr(),
            0x10,
            &mut count,
            names.as_mut_ptr(),
            &mut size,
            buffer.as_mut_ptr(),
            properties.as_mut_ptr(),
        )
    };
    if code != 0
        || count != 1
        || properties[0] & 3 != 0
        || size == 0
        || size as usize > buffer.len()
    {
        return Err(UNAVAILABLE.into());
    }
    let name = owned_name(names[0], &buffer[..size as usize])?;
    let mut length = 0;
    let code =
        unsafe { GetPackagePathByFullName(name.as_ptr(), &mut length, std::ptr::null_mut()) };
    if code != 122 || length == 0 || length > 32768 {
        return Err(UNAVAILABLE.into());
    }
    let mut path = vec![0u16; length as usize];
    let code = unsafe { GetPackagePathByFullName(name.as_ptr(), &mut length, path.as_mut_ptr()) };
    if code != 0 || length == 0 || length as usize > path.len() {
        return Err(UNAVAILABLE.into());
    }
    let end = path[..length as usize]
        .iter()
        .position(|c| *c == 0)
        .ok_or(UNAVAILABLE)?;
    let root = PathBuf::from(OsString::from_wide(&path[..end]));
    if !root.is_absolute() {
        return Err(UNAVAILABLE.into());
    }
    Ok(Some(root))
}

fn owned_name(pointer: *const u16, buffer: &[u16]) -> Result<Vec<u16>, String> {
    let bytes = (pointer as usize)
        .checked_sub(buffer.as_ptr() as usize)
        .ok_or(UNAVAILABLE)?;
    if bytes & 1 != 0 {
        return Err(UNAVAILABLE.into());
    }
    let slice = buffer.get(bytes / 2..).ok_or(UNAVAILABLE)?;
    let end = slice
        .iter()
        .position(|c| *c == 0)
        .filter(|end| *end > 0)
        .ok_or(UNAVAILABLE)?;
    Ok(slice[..=end].to_vec())
}

fn manifest_engine(root: &Path, xml: &str) -> Result<PathBuf, String> {
    use quick_xml::{events::Event, Reader, XmlVersion};
    let mut reader = Reader::from_str(xml.trim_start_matches('\u{feff}'));
    let mut candidates = Vec::new();
    let mut elements: Vec<String> = Vec::new();
    let mut seen_root = false;
    let mut version = XmlVersion::Implicit1_0;
    loop {
        let event = reader.read_event().map_err(|_| UNAVAILABLE)?;
        match &event {
            Event::Start(element) | Event::Empty(element)
                if element.local_name().as_ref() == "Application"
                    && elements
                        .iter()
                        .map(String::as_str)
                        .eq(["Package", "Applications"]) =>
            {
                for attr in element.attributes() {
                    let attr = attr.map_err(|_| UNAVAILABLE)?;
                    if attr.key.as_ref() == "Executable" {
                        let entry = attr.normalized_value(version).map_err(|_| UNAVAILABLE)?;
                        let relative = Path::new(&*entry);
                        if relative.is_absolute()
                            || relative
                                .components()
                                .any(|v| !matches!(v, std::path::Component::Normal(_)))
                        {
                            return Err(UNAVAILABLE.into());
                        }
                        let app = root.join(relative);
                        let engine = app.parent().ok_or(UNAVAILABLE)?.join("resources/codex.exe");
                        if app.is_file() && engine.is_file() {
                            let real_root = root.canonicalize().map_err(|_| UNAVAILABLE)?;
                            let real_engine = engine.canonicalize().map_err(|_| UNAVAILABLE)?;
                            if !real_engine.starts_with(&real_root) {
                                return Err(UNAVAILABLE.into());
                            }
                            if !candidates.contains(&engine) {
                                candidates.push(engine);
                            }
                        }
                    }
                }
            }
            _ => {}
        }
        match event {
            Event::Start(element) => {
                if elements.is_empty() {
                    if seen_root || element.local_name().as_ref() != "Package" {
                        return Err(UNAVAILABLE.into());
                    }
                    seen_root = true;
                }
                elements.push(element.local_name().as_ref().to_owned());
            }
            Event::Empty(element) => {
                if elements.is_empty() {
                    if seen_root || element.local_name().as_ref() != "Package" {
                        return Err(UNAVAILABLE.into());
                    }
                    seen_root = true;
                }
            }
            Event::End(element)
                if elements.pop().as_deref() != Some(element.local_name().as_ref()) =>
            {
                return Err(UNAVAILABLE.into())
            }
            Event::Text(text)
                if elements.is_empty()
                    && !text.as_ref().bytes().all(|b| b.is_ascii_whitespace()) =>
            {
                return Err(UNAVAILABLE.into())
            }
            Event::DocType(_) => return Err(UNAVAILABLE.into()),
            Event::Decl(declaration) => {
                if seen_root {
                    return Err(UNAVAILABLE.into());
                }
                version = declaration.xml_version().map_err(|_| UNAVAILABLE)?;
            }
            Event::Eof => {
                if !seen_root || !elements.is_empty() {
                    return Err(UNAVAILABLE.into());
                }
                break;
            }
            _ => {}
        }
    }
    if candidates.len() != 1 {
        return Err(UNAVAILABLE.into());
    }
    Ok(candidates.remove(0))
}

#[cfg(test)]
mod tests;
