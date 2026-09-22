/// Every Tauri command the renderer may invoke. Shared by `build.rs` (ACL
/// manifest) and the library (handler registration + tests), so the three can
/// never drift apart. Adding a name is a security-relevant change: it needs a
/// capability grant, a row in the P2 capability table and a review.
pub const APP_COMMANDS: &[&str] = &[
    // P2: identity and the typed local bridge.
    "desktop_info",
    "bridge_request",
    // P3: Desktop-shell capabilities (not protocol commands, never proxied).
    "get_server_origin",
    "set_server_origin",
    "restart_desktop",
    "choose_folder",
    "choose_file",
    // P10: diagnostics and user-driven updates (typed, closed inputs only).
    "get_diagnostics",
    "export_diagnostics",
    "open_data_folder",
    "check_for_update",
    "install_update",
];
