use std::{
    ffi::c_void,
    os::windows::io::{AsRawHandle, FromRawHandle, OwnedHandle},
    path::Path,
};

#[repr(C)]
#[derive(Default)]
struct FileTime {
    low: u32,
    high: u32,
}

#[link(name = "kernel32")]
extern "system" {
    fn OpenProcess(access: u32, inherit: i32, pid: u32) -> *mut c_void;
    fn GetCurrentProcess() -> *mut c_void;
    fn GetProcessTimes(
        process: *mut c_void,
        created: *mut FileTime,
        exit: *mut FileTime,
        kernel: *mut FileTime,
        user: *mut FileTime,
    ) -> i32;
    fn QueryFullProcessImageNameW(
        process: *mut c_void,
        flags: u32,
        name: *mut u16,
        size: *mut u32,
    ) -> i32;
    fn WaitForSingleObject(handle: *mut c_void, timeout: u32) -> u32;
}
#[link(name = "advapi32")]
extern "system" {
    fn OpenProcessToken(process: *mut c_void, access: u32, token: *mut *mut c_void) -> i32;
    fn GetTokenInformation(
        token: *mut c_void,
        kind: u32,
        data: *mut c_void,
        size: u32,
        needed: *mut u32,
    ) -> i32;
    fn EqualSid(first: *const c_void, second: *const c_void) -> i32;
}

pub(super) fn same_path(first: &Path, second: &Path) -> bool {
    match (first.canonicalize(), second.canonicalize()) {
        (Ok(first), Ok(second)) => first
            .to_string_lossy()
            .eq_ignore_ascii_case(&second.to_string_lossy()),
        _ => false,
    }
}

fn token_user(process: *mut c_void) -> Result<Vec<usize>, String> {
    let mut token = std::ptr::null_mut();
    if unsafe { OpenProcessToken(process, 8, &mut token) } == 0 {
        return Err("Recovery peer token unavailable".into());
    }
    let token = unsafe { OwnedHandle::from_raw_handle(token) };
    let mut needed = 0;
    unsafe {
        GetTokenInformation(
            token.as_raw_handle(),
            1,
            std::ptr::null_mut(),
            0,
            &mut needed,
        );
    }
    if !(std::mem::size_of::<usize>() as u32..=65536).contains(&needed) {
        return Err("Invalid recovery peer token".into());
    }
    let mut data = vec![0usize; (needed as usize).div_ceil(std::mem::size_of::<usize>())];
    if unsafe {
        GetTokenInformation(
            token.as_raw_handle(),
            1,
            data.as_mut_ptr().cast(),
            needed,
            &mut needed,
        )
    } == 0
    {
        return Err("Recovery peer token read failed".into());
    }
    Ok(data)
}

pub(super) fn monitor(pid: u32, created: &str, expected: &Path) -> Result<OwnedHandle, String> {
    // Hold the exact process object, not a later process that reuses its PID.
    let process = unsafe { OpenProcess(0x0010_1000, 0, pid) }; // SYNCHRONIZE | QUERY_LIMITED_INFORMATION.
    if process.is_null() {
        return Err("Recovery monitor unavailable".into());
    }
    let process = unsafe { OwnedHandle::from_raw_handle(process) };
    if unsafe { WaitForSingleObject(process.as_raw_handle(), 0) } != 258 {
        return Err("Recovery monitor already exited".into());
    }
    let mut times: [FileTime; 4] = std::array::from_fn(|_| FileTime::default());
    let [a, b, c, d] = &mut times;
    if unsafe { GetProcessTimes(process.as_raw_handle(), a, b, c, d) } == 0 {
        return Err("Recovery monitor lifetime unavailable".into());
    }
    let stamp = ((times[0].high as u64) << 32) | times[0].low as u64;
    if created.parse::<u64>().ok() != Some(stamp) {
        return Err("Recovery monitor lifetime mismatch".into());
    }
    let mut buffer = vec![0u16; 32768];
    let mut length = buffer.len() as u32;
    if unsafe {
        QueryFullProcessImageNameW(process.as_raw_handle(), 0, buffer.as_mut_ptr(), &mut length)
    } == 0
    {
        return Err("Recovery monitor image unavailable".into());
    }
    let path = String::from_utf16(&buffer[..length as usize])
        .map_err(|_| "Invalid recovery image path")?;
    if !same_path(Path::new(&path), expected) {
        return Err("Recovery monitor image mismatch".into());
    }
    let peer = token_user(process.as_raw_handle())?;
    let current = token_user(unsafe { GetCurrentProcess() })?;
    // TOKEN_USER starts with a SID pointer; usize storage preserves its alignment.
    if unsafe {
        EqualSid(
            *(peer.as_ptr().cast::<*const c_void>()),
            *(current.as_ptr().cast::<*const c_void>()),
        )
    } == 0
    {
        return Err("Recovery monitor belongs to another user".into());
    }
    Ok(process)
}
