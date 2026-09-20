// The renderer can only reach the commands declared here. Each name becomes an
// `allow-<name>` permission that the capability file grants explicitly.
include!("src/command_names.rs");

use std::path::PathBuf;

/// The Windows resource compiler (RC.EXE) cannot read an icon path containing
/// an apostrophe, and this repository is commonly checked out under
/// `...\Studi'os\...`. When the icon path is affected, build from a copy kept
/// in the system temp directory; every other case uses the default path.
fn windows_icon_override() -> Option<PathBuf> {
    let manifest_dir = PathBuf::from(std::env::var_os("CARGO_MANIFEST_DIR")?);
    let icon = manifest_dir.join("icons").join("icon.ico");
    if !cfg!(windows) || !icon.to_string_lossy().contains('\'') {
        return None;
    }
    let dir = std::env::temp_dir().join("studio-os-desktop-build");
    std::fs::create_dir_all(&dir).ok()?;
    let copy = dir.join("icon.ico");
    std::fs::copy(&icon, &copy).ok()?;
    println!("cargo:rerun-if-changed={}", icon.display());
    Some(copy)
}

fn main() {
    let mut windows = tauri_build::WindowsAttributes::new();
    if let Some(icon) = windows_icon_override() {
        windows = windows.window_icon_path(icon);
    }
    tauri_build::try_build(
        tauri_build::Attributes::new()
            .windows_attributes(windows)
            .app_manifest(tauri_build::AppManifest::new().commands(APP_COMMANDS)),
    )
    .expect("failed to run tauri-build");
}
