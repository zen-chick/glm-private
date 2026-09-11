#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::net::TcpStream;
use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::Mutex;
use tauri::{Manager, RunEvent};

struct CoreProcess(Mutex<Option<Child>>);

fn core_is_ready() -> bool {
    TcpStream::connect_timeout(
        &"127.0.0.1:8765".parse().expect("valid loopback address"),
        std::time::Duration::from_millis(250),
    )
    .is_ok()
}

fn core_script() -> Option<PathBuf> {
    if let Ok(path) = std::env::var("GLM_CORE_SCRIPT") {
        let candidate = PathBuf::from(path);
        if candidate.exists() { return Some(candidate); }
    }
    let exe = std::env::current_exe().ok()?;
    let mut base = exe.parent()?.to_path_buf();
    for _ in 0..6 {
        let candidate = base.join("glm_ide_core.py");
        if candidate.exists() { return Some(candidate); }
        base = base.parent()?.to_path_buf();
    }
    None
}

fn bundled_core() -> Option<PathBuf> {
    let exe = std::env::current_exe().ok()?;
    let candidates = [
        exe.parent()?.join("resources").join("GLM Core.exe"),
        exe.parent()?.join("GLM Core.exe"),
    ];
    candidates.into_iter().find(|candidate| candidate.exists())
}

fn start_core_if_needed() -> Option<Child> {
    if core_is_ready() { return None; }
    let workspace = std::env::var("GLM_WORKSPACE")
        .map(PathBuf::from)
        .unwrap_or_else(|_| dirs_fallback());
    std::fs::create_dir_all(&workspace).ok()?;
    if let Some(core) = bundled_core() {
        return Command::new(core)
            .args(["--workspace", workspace.to_string_lossy().as_ref(), "--port", "8765"])
            .spawn().ok();
    }
    let script = core_script()?;
    let python = if cfg!(windows) { "py.exe" } else { "python3" };
    Command::new(python)
        .args([script.to_string_lossy().as_ref(), "--workspace", workspace.to_string_lossy().as_ref(), "--port", "8765"])
        .current_dir(script.parent()?)
        .spawn().ok()
}

fn dirs_fallback() -> PathBuf {
    std::env::var("USERPROFILE")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("."))
        .join("Desktop")
        .join("新しいフォルダー")
}

fn main() {
    let core = start_core_if_needed();
    let builder = tauri::Builder::default()
        .manage(CoreProcess(Mutex::new(core)))
        .setup(|app| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.set_title("GLM Standalone IDE");
            }
            Ok(())
        });
    builder.run(tauri::generate_context!(), |app, event| {
        if let RunEvent::Exit = event {
            if let Some(state) = app.try_state::<CoreProcess>() {
                if let Ok(mut child) = state.0.lock() {
                    if let Some(process) = child.as_mut() { let _ = process.kill(); }
                }
            }
        }
    }).expect("error while running GLM Standalone IDE");
}
