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

/// Common Controls v6 for the unit-test executable. The app carries tauri-build's
/// embedded manifest; a test binary has none, and the Windows loader refuses it
/// (STATUS_ENTRYPOINT_NOT_FOUND, `TaskDialogIndirect`) since the Wry runtime is
/// linked. The linker-generated external manifest sits next to the test exe and
/// is ignored wherever an embedded manifest exists (the app).
fn common_controls_for_tests() {
    if std::env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("windows")
        && std::env::var("CARGO_CFG_TARGET_ENV").as_deref() == Ok("msvc")
    {
        println!("cargo:rustc-link-arg=/MANIFEST");
        println!(
            "cargo:rustc-link-arg=/MANIFESTDEPENDENCY:type='win32' name='Microsoft.Windows.Common-Controls'              version='6.0.0.0' processorArchitecture='*' publicKeyToken='6595b64144ccf1df' language='*'"
        );
    }
}

fn main() {
    common_controls_for_tests();
    println!("cargo:rerun-if-env-changed=STUDIO_DESKTOP_API_URL");
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
