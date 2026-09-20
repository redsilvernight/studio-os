//! Studi'OS Desktop shell (P2 foundation).
//!
//! A thin Tauri 2 host for the shared Dashboard build. The only privileged
//! surface is two app commands (see `command_names`): `desktop_info` and
//! `bridge_request`. There is no shell, filesystem, process or HTTP-proxy
//! primitive, and no plugin that provides one.

mod allowlist;
mod bridge;
#[cfg_attr(not(test), allow(dead_code))] // consumed by build.rs and the tests
mod command_names;
mod info;
mod navigation;
mod sidecar;

use navigation::Decision;
use serde_json::{Map, Value};
use sidecar::{ExchangeError, Sidecar};
use tauri::webview::NewWindowResponse;
use tauri::{Manager, RunEvent, State, WebviewUrl, WebviewWindow, WebviewWindowBuilder};
use url::Url;

/// The Vite dev server origin; `None` in a release build.
struct DevOrigin(Option<Url>);

fn caller_is_trusted(window: &WebviewWindow, dev: &DevOrigin) -> bool {
    window.label() == "main"
        && window
            .url()
            .map(|u| navigation::decide(&u, dev.0.as_ref()) == Decision::Allow)
            .unwrap_or(false)
}

fn open_externally(url: &Url) {
    if let Some(target) = navigation::external_target(url) {
        let _ = webbrowser::open(target);
    }
}

#[tauri::command]
fn desktop_info(
    window: WebviewWindow,
    sidecar: State<'_, Sidecar>,
    dev: State<'_, DevOrigin>,
) -> Result<info::DesktopInfo, String> {
    if !caller_is_trusted(&window, &dev) {
        return Err("untrusted caller".into());
    }
    Ok(info::desktop_info(sidecar.state()))
}

#[tauri::command]
async fn bridge_request(
    window: WebviewWindow,
    request: Value,
    sidecar: State<'_, Sidecar>,
    dev: State<'_, DevOrigin>,
) -> Result<Value, String> {
    if !caller_is_trusted(&window, &dev) {
        return Err("untrusted caller".into());
    }
    let sidecar = sidecar.inner().clone();
    tauri::async_runtime::spawn_blocking(move || handle_request(&sidecar, request))
        .await
        .map_err(|_| "bridge task failed".to_string())
}

fn handle_request(sidecar: &Sidecar, request: Value) -> Value {
    let valid = match bridge::validate_request(&request) {
        Ok(v) => v,
        Err(rejection) => return bridge::reject(&request, &rejection),
    };
    let err = |code: &str, message: &str, retryable: bool, details: Map<String, Value>| {
        bridge::error_message(
            Some(&valid.message_id),
            Some(&valid.correlation_id),
            code,
            message,
            retryable,
            details,
        )
    };
    if !allowlist::is_served_in_p2(&valid.command) {
        let mut details = Map::new();
        details.insert("command".into(), Value::String(valid.command.clone()));
        return err(
            "not_supported",
            "This command is part of the protocol but not served by the P2 spike.",
            false,
            details,
        );
    }
    let line = match serde_json::to_string(&request) {
        Ok(l) if !l.contains('\n') => l,
        _ => return err("invalid_request", "The request could not be serialised.", false, Map::new()),
    };
    match sidecar.exchange(&line) {
        Ok(answer) => match serde_json::from_str::<Value>(&answer) {
            Ok(parsed) => match bridge::check_peer_answer(&valid, &parsed) {
                Ok(()) => parsed,
                Err(why) => err("internal_error", why, false, Map::new()),
            },
            Err(_) => err("internal_error", "The local peer answered with invalid JSON.", false, Map::new()),
        },
        Err(ExchangeError::Unavailable) => err(
            "daemon_unavailable",
            "The local daemon is not available.",
            true,
            Map::new(),
        ),
        Err(ExchangeError::Crashed { code }) => {
            let mut details = Map::new();
            if let Some(code) = code {
                details.insert("exit_code".into(), Value::from(code));
            }
            err("daemon_crashed", "The local daemon stopped unexpectedly.", true, details)
        }
        Err(ExchangeError::Timeout) => {
            err("timeout", "The local daemon did not answer in time.", true, Map::new())
        }
        Err(ExchangeError::Io) => {
            err("internal_error", "The local daemon channel failed.", true, Map::new())
        }
    }
}

pub fn run() {
    let sidecar = Sidecar::default();
    let exit_sidecar = sidecar.clone();

    let app = tauri::Builder::default()
        .manage(sidecar)
        .invoke_handler(tauri::generate_handler![desktop_info, bridge_request])
        .setup(|app| {
            let dev_origin = if tauri::is_dev() {
                app.config().build.dev_url.clone()
            } else {
                None
            };
            app.manage(DevOrigin(dev_origin.clone()));

            let nav_dev = dev_origin.clone();
            let popup_dev = dev_origin.clone();
            WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
                .title(info::PRODUCT)
                .inner_size(1280.0, 800.0)
                .min_inner_size(900.0, 600.0)
                .on_navigation(move |url| match navigation::decide(url, nav_dev.as_ref()) {
                    Decision::Allow => true,
                    Decision::OpenExternally => {
                        open_externally(url);
                        false
                    }
                    Decision::Deny => false,
                })
                .on_new_window(move |url, _features| {
                    // Popups never get a WebView of their own: same policy,
                    // and an internal target is still refused as a new window.
                    if navigation::decide(&url, popup_dev.as_ref()) == Decision::OpenExternally {
                        open_externally(&url);
                    }
                    NewWindowResponse::Deny
                })
                .build()?;
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building Studi'OS Desktop");

    app.run(move |_handle, event| {
        if let RunEvent::Exit = event {
            exit_sidecar.shutdown();
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    fn read(rel: &str) -> String {
        fs::read_to_string(format!("{}/{rel}", env!("CARGO_MANIFEST_DIR"))).unwrap()
    }

    #[test]
    fn registered_commands_are_exactly_the_two_typed_ones() {
        assert_eq!(command_names::APP_COMMANDS, &["desktop_info", "bridge_request"]);
    }

    #[test]
    fn no_command_name_is_a_generic_dangerous_primitive() {
        let banned = [
            "execute_shell", "spawn_process", "read_file", "write_file", "proxy_http", "execute",
            "run_command", "shell", "spawn", "exec", "fs", "http", "proxy", "eval",
        ];
        for name in command_names::APP_COMMANDS {
            let lower = name.to_lowercase();
            assert!(
                !banned.iter().any(|b| lower.split('_').any(|part| part == *b) || lower == *b),
                "{name} looks like a generic primitive"
            );
        }
    }

    #[test]
    fn capability_grants_exactly_the_app_commands_and_no_plugin() {
        let cap: Value = serde_json::from_str(&read("capabilities/main-window.json")).unwrap();
        let mut granted: Vec<String> = cap["permissions"]
            .as_array()
            .unwrap()
            .iter()
            .map(|p| p.as_str().expect("plain permission strings only").to_owned())
            .collect();
        granted.sort();
        let mut expected: Vec<String> = command_names::APP_COMMANDS
            .iter()
            .map(|c| format!("allow-{}", c.replace('_', "-")))
            .collect();
        expected.sort();
        assert_eq!(granted, expected);
        assert_eq!(cap["windows"], serde_json::json!(["main"]));
        assert!(cap.get("remote").is_none(), "no remote URL may hold a capability");
    }

    #[test]
    fn only_one_capability_file_exists() {
        let files: Vec<_> = fs::read_dir(format!("{}/capabilities", env!("CARGO_MANIFEST_DIR")))
            .unwrap()
            .flatten()
            .collect();
        assert_eq!(files.len(), 1);
    }

    #[test]
    fn config_has_no_dangerous_surface() {
        let conf: Value = serde_json::from_str(&read("tauri.conf.json")).unwrap();
        // No preconfigured window: the only window is built in code with the
        // navigation policy attached.
        assert_eq!(conf["app"]["windows"], serde_json::json!([]));
        assert!(conf["plugins"].is_null() || conf["plugins"].as_object().unwrap().is_empty());
        assert!(conf["app"]["security"]["dangerousDisableAssetCspModification"].is_null());
        assert!(conf["app"]["security"]["dangerousRemoteDomainIpcAccess"].is_null());
        let csp = conf["app"]["security"]["csp"].as_str().unwrap();
        assert!(csp.contains("default-src 'self'"));
        assert!(!csp.contains("unsafe-eval"));
        assert!(!csp.contains(" *"));
        let cargo = read("Cargo.toml");
        for banned in ["tauri-plugin-shell", "tauri-plugin-fs", "tauri-plugin-http", "tauri-plugin-opener"] {
            assert!(!cargo.contains(banned), "{banned} must not be a dependency");
        }
    }

    #[test]
    fn valid_but_unserved_commands_answer_not_supported() {
        let sc = Sidecar::default();
        let mut req: Value = serde_json::from_str(
            &fs::read_to_string(concat!(
                env!("CARGO_MANIFEST_DIR"),
                "/../../contracts/local/fixtures/valid/bridge.request.handshake.json"
            ))
            .unwrap(),
        )
        .unwrap();
        let mut req = req["data"].take();
        req["command"] = Value::String("daemon.start".into());
        let out = handle_request(&sc, req);
        assert_eq!(out["kind"], "error");
        assert_eq!(out["error"]["code"], "not_supported");
        // It never reached the sidecar.
        assert_eq!(sc.state(), sidecar::SidecarState::NotStarted);
    }

    #[test]
    fn non_allowlisted_command_is_refused_before_any_side_effect() {
        let sc = Sidecar::default();
        let out = handle_request(
            &sc,
            serde_json::json!({"kind":"request","protocol":"studio.local/v1","message_id":"m1",
                "correlation_id":"c1","sent_at":"2026-01-15T12:00:00Z","command":"execute_shell",
                "payload":{"cmd":"calc"}}),
        );
        assert_eq!(out["error"]["code"], "unknown_command");
        assert_eq!(sc.state(), sidecar::SidecarState::NotStarted);
    }
}
