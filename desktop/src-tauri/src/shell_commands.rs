//! Shell-native app commands (P3): runtime `server_origin`, app restart and the
//! semantic native pickers.
//!
//! These are Desktop-shell capabilities, not `studio.local/v1` protocol
//! extensions: they never travel through `bridge_request` and add nothing to
//! the P1 allowlist. Every command re-checks that the caller is the trusted
//! main window on an allowed origin.

use crate::diagnostics::{self, Diagnostics, Folder};
use crate::picker::{self, NativeChooser, PickError, PickKind, PickOutcome, PickerOptions};
use crate::server_origin::{self, SettingsStore};
use crate::sidecar::Sidecar;
use crate::updater::{self, UpdateState, UpdateStatus};
use crate::{caller_is_trusted, DevOrigin};
use serde::Serialize;
use std::sync::atomic::{AtomicBool, Ordering};
use tauri::{AppHandle, State, WebviewWindow};

/// Managed state of the shell settings and the picker gate.
pub struct ShellState {
    pub store: Option<SettingsStore>,
    /// The origin that was added to the CSP when this process started.
    pub applied_origin: Option<String>,
    picker_open: AtomicBool,
}

impl ShellState {
    pub fn new(store: Option<SettingsStore>, applied_origin: Option<String>) -> Self {
        Self {
            store,
            applied_origin,
            picker_open: AtomicBool::new(false),
        }
    }
}

#[derive(Debug, Serialize)]
pub struct ShellError {
    pub code: String,
    pub message: String,
}

fn shell_error(code: &str, message: &str) -> ShellError {
    ShellError {
        code: code.into(),
        message: message.into(),
    }
}

fn untrusted() -> ShellError {
    shell_error("untrusted_caller", "untrusted caller")
}

#[derive(Debug, Serialize, PartialEq, Eq)]
pub struct ServerOriginState {
    /// The user-configured origin, `None` when the build default applies.
    pub configured: Option<String>,
    /// The user origin this process allowed in its CSP at start (`None` = the
    /// build default). It is the only user origin the renderer may call now.
    pub applied: Option<String>,
    /// True when `configured` differs from what this process allowed in its
    /// CSP: the change only takes effect after a restart.
    pub restart_required: bool,
}

fn origin_state(state: &ShellState) -> ServerOriginState {
    let configured = state.store.as_ref().and_then(SettingsStore::load);
    let restart_required = configured != state.applied_origin;
    ServerOriginState {
        configured,
        applied: state.applied_origin.clone(),
        restart_required,
    }
}

#[tauri::command]
pub fn get_server_origin(
    window: WebviewWindow,
    state: State<'_, ShellState>,
    dev: State<'_, DevOrigin>,
) -> Result<ServerOriginState, ShellError> {
    if !caller_is_trusted(&window, &dev) {
        return Err(untrusted());
    }
    Ok(origin_state(&state))
}

/// `origin: null` clears the user setting (the build default applies again).
#[tauri::command]
pub fn set_server_origin(
    window: WebviewWindow,
    origin: Option<String>,
    state: State<'_, ShellState>,
    dev: State<'_, DevOrigin>,
) -> Result<ServerOriginState, ShellError> {
    if !caller_is_trusted(&window, &dev) {
        return Err(untrusted());
    }
    let Some(store) = state.store.as_ref() else {
        return Err(shell_error(
            "storage_unavailable",
            "No per-user configuration directory is available.",
        ));
    };
    let normalised = match origin {
        None => None,
        Some(raw) => {
            Some(server_origin::validate(&raw).map_err(|e| shell_error(e.code(), e.message()))?)
        }
    };
    store
        .save(normalised.as_deref())
        .map_err(|_| shell_error("storage_failed", "The server address could not be saved."))?;
    Ok(origin_state(&state))
}

/// Relaunch the application (needed to apply a new server origin to the CSP).
/// The sidecar is stopped first: `restart` does not emit the exit event.
#[tauri::command]
pub fn restart_desktop(
    window: WebviewWindow,
    app: AppHandle,
    sidecar: State<'_, Sidecar>,
    dev: State<'_, DevOrigin>,
) -> Result<(), ShellError> {
    if !caller_is_trusted(&window, &dev) {
        return Err(untrusted());
    }
    sidecar.shutdown();
    app.restart()
}

async fn run_picker(
    window: WebviewWindow,
    kind: PickKind,
    options: Option<PickerOptions>,
    state: &ShellState,
    dev: &DevOrigin,
) -> Result<PickOutcome, ShellError> {
    if !caller_is_trusted(&window, dev) {
        return Err(untrusted());
    }
    let options = options.unwrap_or_default();
    picker::validate_options(kind, &options).map_err(|e| shell_error(e.code(), e.message()))?;
    if state.picker_open.swap(true, Ordering::SeqCst) {
        return Err(shell_error(
            "picker_busy",
            "A selection dialog is already open.",
        ));
    }
    let chooser = NativeChooser { parent: window };
    let result =
        tauri::async_runtime::spawn_blocking(move || picker::pick(&chooser, kind, &options)).await;
    state.picker_open.store(false, Ordering::SeqCst);
    match result {
        Ok(Ok(outcome)) => Ok(outcome),
        Ok(Err(PickError::Options(e))) => Err(shell_error(e.code(), e.message())),
        Ok(Err(PickError::UnsupportedPath)) => Err(shell_error(
            "unsupported_path",
            "The chosen path cannot be represented as text.",
        )),
        Err(_) => Err(shell_error("picker_failed", "The selection dialog failed.")),
    }
}

#[tauri::command]
pub async fn choose_folder(
    window: WebviewWindow,
    options: Option<PickerOptions>,
    state: State<'_, ShellState>,
    dev: State<'_, DevOrigin>,
) -> Result<PickOutcome, ShellError> {
    run_picker(window, PickKind::Folder, options, &state, &dev).await
}

#[tauri::command]
pub async fn choose_file(
    window: WebviewWindow,
    options: Option<PickerOptions>,
    state: State<'_, ShellState>,
    dev: State<'_, DevOrigin>,
) -> Result<PickOutcome, ShellError> {
    run_picker(window, PickKind::File, options, &state, &dev).await
}

fn diagnostics_of(state: &ShellState, sidecar: &Sidecar, updates: &UpdateState) -> Diagnostics {
    let origin = origin_state(state);
    diagnostics::collect(
        sidecar.state(),
        origin.applied.or(origin.configured),
        state.store.as_ref().map(SettingsStore::dir),
        updates.configured,
    )
}

/// Versions, sidecar state and data locations. Read-only; no secret is read.
#[tauri::command]
pub fn get_diagnostics(
    window: WebviewWindow,
    state: State<'_, ShellState>,
    sidecar: State<'_, Sidecar>,
    updates: State<'_, UpdateState>,
    dev: State<'_, DevOrigin>,
) -> Result<Diagnostics, ShellError> {
    if !caller_is_trusted(&window, &dev) {
        return Err(untrusted());
    }
    Ok(diagnostics_of(&state, &sidecar, &updates))
}

#[derive(Debug, Serialize)]
pub struct ExportedDiagnostics {
    /// Display form (home directory masked) of the written file.
    pub file: String,
}

/// Write the redacted diagnostics file into the daemon data directory. The
/// destination is fixed; the renderer chooses nothing.
#[tauri::command]
pub async fn export_diagnostics(
    window: WebviewWindow,
    state: State<'_, ShellState>,
    sidecar: State<'_, Sidecar>,
    updates: State<'_, UpdateState>,
    dev: State<'_, DevOrigin>,
) -> Result<ExportedDiagnostics, ShellError> {
    if !caller_is_trusted(&window, &dev) {
        return Err(untrusted());
    }
    let snapshot = diagnostics_of(&state, &sidecar, &updates);
    let Some(data) = diagnostics::daemon_data_dir() else {
        return Err(shell_error(
            "storage_unavailable",
            "No per-user data directory is available.",
        ));
    };
    let failed = || shell_error("export_failed", "The diagnostics could not be exported.");
    let path = tauri::async_runtime::spawn_blocking(move || diagnostics::export(&snapshot, &data))
        .await
        .map_err(|_| failed())?
        .map_err(|_| failed())?;
    Ok(ExportedDiagnostics {
        file: diagnostics::redact(&path.to_string_lossy()),
    })
}

/// Reveal the logs or the exported diagnostics folder in the file explorer.
#[tauri::command]
pub fn open_data_folder(
    window: WebviewWindow,
    folder: Folder,
    dev: State<'_, DevOrigin>,
) -> Result<(), ShellError> {
    if !caller_is_trusted(&window, &dev) {
        return Err(untrusted());
    }
    let Some(data) = diagnostics::daemon_data_dir() else {
        return Err(shell_error(
            "storage_unavailable",
            "No per-user data directory is available.",
        ));
    };
    diagnostics::reveal(&diagnostics::folder_path(folder, &data))
        .map_err(|_| shell_error("open_failed", "The folder could not be opened."))
}

fn update_error(e: updater::UpdateError) -> ShellError {
    shell_error(e.code, e.message)
}

/// User-driven: nothing checks for updates on its own.
#[tauri::command]
pub async fn check_for_update(
    window: WebviewWindow,
    app: AppHandle,
    updates: State<'_, UpdateState>,
    dev: State<'_, DevOrigin>,
) -> Result<UpdateStatus, ShellError> {
    if !caller_is_trusted(&window, &dev) {
        return Err(untrusted());
    }
    updater::check(&app, &updates).await.map_err(update_error)
}

/// Download the release found by `check_for_update`, verify its signature, then
/// stop the daemon and hand over to the installer (which restarts the app).
/// Any failure leaves the installed version untouched.
#[tauri::command]
pub async fn install_update(
    window: WebviewWindow,
    sidecar: State<'_, Sidecar>,
    updates: State<'_, UpdateState>,
    dev: State<'_, DevOrigin>,
) -> Result<(), ShellError> {
    if !caller_is_trusted(&window, &dev) {
        return Err(untrusted());
    }
    let (update, bytes) = updater::download_verified(&updates)
        .await
        .map_err(update_error)?;
    let sidecar = sidecar.inner().clone();
    tauri::async_runtime::spawn_blocking(move || {
        sidecar.shutdown();
        update.install(bytes)
    })
    .await
    .map_err(|_| shell_error("install_failed", "The update could not be installed."))?
    .map_err(|e| update_error(updater::classify(&e)))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn state_with(tag: &str, applied: Option<&str>) -> (ShellState, SettingsStore) {
        let dir =
            std::env::temp_dir().join(format!("studio-desktop-shell-{tag}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        let store = SettingsStore::new(dir);
        (
            ShellState::new(Some(store.clone()), applied.map(str::to_owned)),
            store,
        )
    }

    #[test]
    fn no_saved_origin_and_none_applied_needs_no_restart() {
        let (state, _) = state_with("none", None);
        assert_eq!(
            origin_state(&state),
            ServerOriginState {
                configured: None,
                applied: None,
                restart_required: false
            }
        );
    }

    #[test]
    fn a_saved_origin_that_differs_from_the_applied_one_needs_a_restart() {
        let (state, store) = state_with("differs", None);
        store.save(Some("https://studio.example.com")).unwrap();
        let s = origin_state(&state);
        assert_eq!(s.configured.as_deref(), Some("https://studio.example.com"));
        assert_eq!(s.applied, None);
        assert!(s.restart_required);
    }

    #[test]
    fn a_saved_origin_equal_to_the_applied_one_needs_no_restart() {
        let (state, store) = state_with("same", Some("https://studio.example.com"));
        store.save(Some("https://studio.example.com")).unwrap();
        let s = origin_state(&state);
        assert_eq!(s.applied.as_deref(), Some("https://studio.example.com"));
        assert!(!s.restart_required);
    }

    #[test]
    fn clearing_an_applied_origin_needs_a_restart() {
        let (state, store) = state_with("clear", Some("https://studio.example.com"));
        store.save(None).unwrap();
        let s = origin_state(&state);
        assert_eq!(s.configured, None);
        assert!(s.restart_required);
    }
}
