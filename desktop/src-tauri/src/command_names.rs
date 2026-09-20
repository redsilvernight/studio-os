/// Every Tauri command the renderer may invoke. Shared by `build.rs` (ACL
/// manifest) and the library (handler registration + tests), so the three can
/// never drift apart. Adding a name is a security-relevant change: it needs a
/// capability grant, a row in the P2 capability table and a review.
pub const APP_COMMANDS: &[&str] = &["desktop_info", "bridge_request"];
