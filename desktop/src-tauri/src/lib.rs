//! Studi'OS Desktop shell.
//!
//! A thin Tauri 2 host for the shared Dashboard build. The only privileged
//! surface is the closed list of typed app commands in `command_names`: the
//! P2 identity/bridge pair and the P3 shell commands (runtime server origin,
//! restart, semantic native pickers). There is no shell, filesystem, process
//! or HTTP-proxy primitive, and no plugin that provides one.

mod allowlist;
mod bridge;
#[cfg_attr(not(test), allow(dead_code))] // consumed by build.rs and the tests
mod command_names;
mod diagnostics;
mod info;
mod navigation;
mod picker;
mod server_origin;
mod shell_commands;
mod sidecar;
mod updater;
mod webview_args;

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
    if !allowlist::is_served_by_daemon(&valid.command) {
        let mut details = Map::new();
        details.insert("command".into(), Value::String(valid.command.clone()));
        return err(
            "not_supported",
            "This command is part of the protocol but not served by the daemon.",
            false,
            details,
        );
    }
    let line = match serde_json::to_string(&request) {
        Ok(l) if !l.contains('\n') => l,
        _ => {
            return err(
                "invalid_request",
                "The request could not be serialised.",
                false,
                Map::new(),
            )
        }
    };
    match sidecar.exchange(&line) {
        Ok(answer) => match serde_json::from_str::<Value>(&answer) {
            Ok(parsed) => match bridge::check_peer_answer(&valid, &parsed) {
                Ok(()) => parsed,
                Err(why) => err("internal_error", why, false, Map::new()),
            },
            Err(_) => err(
                "internal_error",
                "The local peer answered with invalid JSON.",
                false,
                Map::new(),
            ),
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
            err(
                "daemon_crashed",
                "The local daemon stopped unexpectedly.",
                true,
                details,
            )
        }
        Err(ExchangeError::Timeout) => err(
            "timeout",
            "The local daemon did not answer in time.",
            true,
            Map::new(),
        ),
        Err(ExchangeError::Io) => err(
            "internal_error",
            "The local daemon channel failed.",
            true,
            Map::new(),
        ),
    }
}

fn apply_server_origin_to_csp(config: &mut tauri::Config, origin: &str) {
    let security = &mut config.app.security;
    if let Some(tauri::utils::config::Csp::Policy(policy)) = &security.csp {
        security.csp = Some(tauri::utils::config::Csp::Policy(
            server_origin::csp_with_connect_origin(policy, origin),
        ));
    }
}

pub fn run() {
    let mut context = tauri::generate_context!();
    // The CSP is static per build: a user-configured server origin is allowed
    // in `connect-src` (and nowhere else) before the webview is created.
    let store = server_origin::SettingsStore::for_identifier(&context.config().identifier);
    let applied_origin = store.as_ref().and_then(server_origin::SettingsStore::load);
    if let Some(origin) = &applied_origin {
        apply_server_origin_to_csp(context.config_mut(), origin);
    }
    let effective_origin = server_origin::effective_origin(
        applied_origin.as_deref(),
        option_env!("STUDIO_DESKTOP_API_URL"),
        option_env!("STUDIO_DESKTOP_ALLOW_INSECURE_ORIGIN"),
    );
    let sidecar = Sidecar::with_origin(effective_origin);
    let exit_sidecar = sidecar.clone();
    let shell_state = shell_commands::ShellState::new(store, applied_origin);

    // The updater is compiled in but only active when this build carries an
    // updater configuration (public key + endpoint); otherwise it is absent.
    let updates_configured = context.config().plugins.0.contains_key("updater");
    let mut builder = tauri::Builder::default();
    if updates_configured {
        builder = builder.plugin(tauri_plugin_updater::Builder::new().build());
    }

    let app = builder
        .manage(sidecar)
        .manage(shell_state)
        .manage(updater::UpdateState::new(updates_configured))
        .invoke_handler(tauri::generate_handler![
            desktop_info,
            bridge_request,
            shell_commands::get_server_origin,
            shell_commands::set_server_origin,
            shell_commands::restart_desktop,
            shell_commands::choose_folder,
            shell_commands::choose_file,
            shell_commands::get_diagnostics,
            shell_commands::export_diagnostics,
            shell_commands::open_data_folder,
            shell_commands::check_for_update,
            shell_commands::install_update
        ])
        .setup(|app| {
            let dev_origin = if tauri::is_dev() {
                app.config().build.dev_url.clone()
            } else {
                None
            };
            app.manage(DevOrigin(dev_origin.clone()));

            let nav_dev = dev_origin.clone();
            let popup_dev = dev_origin.clone();
            let mut window =
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
                        if navigation::decide(&url, popup_dev.as_ref()) == Decision::OpenExternally
                        {
                            open_externally(&url);
                        }
                        NewWindowResponse::Deny
                    });
            let requested = std::env::var(webview_args::ENV).ok();
            let persisted = webview_args::persisted_value();
            if let Some(args) =
                webview_args::browser_args(requested.as_deref(), persisted.as_deref())
            {
                window = window.additional_browser_args(&args);
            }
            window.build()?;
            Ok(())
        })
        .build(context)
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
    fn registered_commands_are_exactly_the_typed_ones() {
        assert_eq!(
            command_names::APP_COMMANDS,
            &[
                "desktop_info",
                "bridge_request",
                "get_server_origin",
                "set_server_origin",
                "restart_desktop",
                "choose_folder",
                "choose_file",
                "get_diagnostics",
                "export_diagnostics",
                "open_data_folder",
                "check_for_update",
                "install_update",
            ]
        );
    }

    #[test]
    fn no_command_name_is_a_generic_dangerous_primitive() {
        let banned = [
            "execute_shell",
            "spawn_process",
            "read_file",
            "write_file",
            "proxy_http",
            "execute",
            "run_command",
            "shell",
            "spawn",
            "exec",
            "fs",
            "http",
            "proxy",
            "eval",
        ];
        for name in command_names::APP_COMMANDS {
            let lower = name.to_lowercase();
            assert!(
                !banned
                    .iter()
                    .any(|b| lower.split('_').any(|part| part == *b) || lower == *b),
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
            .map(|p| {
                p.as_str()
                    .expect("plain permission strings only")
                    .to_owned()
            })
            .collect();
        granted.sort();
        let mut expected: Vec<String> = command_names::APP_COMMANDS
            .iter()
            .map(|c| format!("allow-{}", c.replace('_', "-")))
            .collect();
        expected.sort();
        assert_eq!(granted, expected);
        assert!(
            granted
                .iter()
                .all(|p| p.starts_with("allow-") && !p.contains(':')),
            "no plugin permission (updater:*, dialog:*, fs:*) may be granted to the renderer"
        );
        assert_eq!(cap["windows"], serde_json::json!(["main"]));
        assert!(
            cap.get("remote").is_none(),
            "no remote URL may hold a capability"
        );
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
        for banned in [
            "tauri-plugin-shell",
            "tauri-plugin-fs",
            "tauri-plugin-http",
            "tauri-plugin-opener",
        ] {
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
        // Publication stays owned by its later lane: allowlisted, never served.
        req["command"] = Value::String("publication.preview".into());
        let out = handle_request(&sc, req);
        assert_eq!(out["kind"], "error");
        assert_eq!(out["error"]["code"], "not_supported");
        // It never reached the sidecar.
        assert_eq!(sc.state(), sidecar::SidecarState::NotStarted);
    }

    #[test]
    fn workspace_commands_are_routed_to_the_daemon() {
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
        // Served since P11: the shell forwards to the sidecar instead of
        // answering not_supported. With no sidecar binary next to the test
        // runner the supervisor reports daemon_unavailable, never a refusal.
        for command in [
            "workspace.validate",
            "workspace.get_config",
            "workspace.confirm_roots",
            "workspace.git_status",
            "workspace.save_config",
        ] {
            req["command"] = Value::String(command.into());
            let out = handle_request(&sc, req.clone());
            assert_eq!(out["kind"], "error", "{command}");
            assert_eq!(out["error"]["code"], "daemon_unavailable", "{command}");
        }
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
