//! P10 updates: a user-driven check and install on top of `tauri-plugin-updater`.
//!
//! The plugin is used programmatically only: it is registered when (and only
//! when) the build carries an updater configuration (`plugins.updater`: public
//! key + HTTPS endpoint), and its own IPC commands are NOT granted to the
//! renderer (see the capability tests). Nothing is checked automatically at
//! start, so an offline or unconfigured Desktop behaves exactly as before.
//!
//! Authenticity: the artifact is verified against the baked-in minisign public
//! key before anything runs (`require-signed-version` also binds the signature
//! to the announced version, which blocks a downgrade to an older genuine
//! release). Any failure leaves the installed version untouched.

use serde::Serialize;
use std::sync::Mutex;
use std::time::Duration;
use tauri::{AppHandle, Runtime};
use tauri_plugin_updater::{Error as PluginError, Update, UpdaterExt};

const CHECK_TIMEOUT: Duration = Duration::from_secs(20);
const MAX_NOTES_CHARS: usize = 2000;

/// Managed state: whether this build can update, and the release found by the
/// last check (installed only through an explicit `install_update`).
pub struct UpdateState {
    pub configured: bool,
    pending: Mutex<Option<Update>>,
}

impl UpdateState {
    pub fn new(configured: bool) -> Self {
        Self {
            configured,
            pending: Mutex::new(None),
        }
    }

    fn set_pending(&self, update: Option<Update>) {
        if let Ok(mut slot) = self.pending.lock() {
            *slot = update;
        }
    }

    fn take_pending(&self) -> Option<Update> {
        self.pending.lock().ok().and_then(|mut slot| slot.take())
    }
}

#[derive(Debug, Serialize, PartialEq, Eq)]
#[serde(tag = "state", rename_all = "snake_case")]
pub enum UpdateStatus {
    /// No public key / endpoint in this build (development or unsigned installer).
    NotConfigured,
    UpToDate {
        current: String,
    },
    Available {
        current: String,
        version: String,
        notes: Option<String>,
    },
}

#[derive(Debug, Serialize, PartialEq, Eq)]
pub struct UpdateError {
    pub code: &'static str,
    pub message: &'static str,
}

/// Map a plugin error to a stable, non-leaking `{code, message}`: transport
/// details and server text never reach the renderer.
pub fn classify(error: &PluginError) -> UpdateError {
    let (code, message) = match error {
        // A body that is not the expected JSON is bad metadata, not a network fault.
        PluginError::Reqwest(e) if e.is_decode() => (
            "invalid_metadata",
            "The update information is invalid or incomplete.",
        ),
        PluginError::Reqwest(_) | PluginError::Network(_) => (
            "network",
            "The update server could not be reached. Try again when you are online.",
        ),
        PluginError::Minisign(_)
        | PluginError::Base64(_)
        | PluginError::SignatureUtf8(_)
        | PluginError::SignedVersionMismatch { .. }
        | PluginError::MissingSignedVersion => (
            "invalid_signature",
            "The update failed its authenticity check and was not installed.",
        ),
        PluginError::ReleaseNotFound
        | PluginError::Serialization(_)
        | PluginError::Semver(_)
        | PluginError::UrlParse(_)
        | PluginError::TargetNotFound(_)
        | PluginError::TargetsNotFound(_) => (
            "invalid_metadata",
            "The update information is invalid or incomplete.",
        ),
        PluginError::InsecureTransportProtocol | PluginError::EmptyEndpoints => (
            "not_configured",
            "Updates are not configured correctly in this build.",
        ),
        _ => ("install_failed", "The update could not be installed."),
    };
    UpdateError { code, message }
}

fn bounded_notes(notes: Option<String>) -> Option<String> {
    notes.map(|n| n.chars().take(MAX_NOTES_CHARS).collect())
}

/// Look for a newer release. A found release is remembered for `install`.
pub async fn check<R: Runtime>(
    app: &AppHandle<R>,
    state: &UpdateState,
) -> Result<UpdateStatus, UpdateError> {
    if !state.configured {
        return Ok(UpdateStatus::NotConfigured);
    }
    let updater = app
        .updater_builder()
        .timeout(CHECK_TIMEOUT)
        .build()
        .map_err(|e| classify(&e))?;
    match updater.check().await.map_err(|e| classify(&e))? {
        Some(update) => {
            let status = UpdateStatus::Available {
                current: update.current_version.clone(),
                version: update.version.clone(),
                notes: bounded_notes(update.body.clone()),
            };
            state.set_pending(Some(update));
            Ok(status)
        }
        None => {
            state.set_pending(None);
            Ok(UpdateStatus::UpToDate {
                current: crate::info::DESKTOP_VERSION.to_owned(),
            })
        }
    }
}

/// Download and verify the pending release, returning the verified bytes. The
/// release is put back when the download fails so the user can retry.
pub async fn download_verified(state: &UpdateState) -> Result<(Update, Vec<u8>), UpdateError> {
    let update = state.take_pending().ok_or(UpdateError {
        code: "no_pending_update",
        message: "Check for an update first.",
    })?;
    match update.download(|_, _| {}, || {}).await {
        Ok(bytes) => Ok((update, bytes)),
        Err(error) => {
            // Any transport-level failure while downloading (including a body cut
            // short) is a retryable network fault, never "bad metadata".
            let classified = match &error {
                PluginError::Reqwest(_) => classify(&PluginError::Network(String::new())),
                other => classify(other),
            };
            state.set_pending(Some(update));
            Err(classified)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{Read, Write};
    use std::net::TcpListener;
    use std::path::PathBuf;
    use std::process::Command;
    use std::sync::Arc;

    #[test]
    fn errors_never_leak_transport_detail() {
        let cases = [
            (
                PluginError::Network("connect to 10.0.0.1 failed".into()),
                "network",
            ),
            (PluginError::ReleaseNotFound, "invalid_metadata"),
            (PluginError::MissingSignedVersion, "invalid_signature"),
            (PluginError::InsecureTransportProtocol, "not_configured"),
            (PluginError::UnsupportedArch, "install_failed"),
        ];
        for (error, code) in cases {
            let out = classify(&error);
            assert_eq!(out.code, code);
            assert!(!out.message.contains("10.0.0.1"));
        }
    }

    #[test]
    fn notes_are_bounded() {
        let long = "x".repeat(MAX_NOTES_CHARS + 500);
        assert_eq!(
            bounded_notes(Some(long)).unwrap().chars().count(),
            MAX_NOTES_CHARS
        );
        assert_eq!(bounded_notes(None), None);
    }

    // ---- end-to-end against a loopback update server with a throwaway key ----

    struct Server {
        addr: String,
        _stop: Arc<Mutex<bool>>,
    }

    /// Serve fixed bodies by path; `truncate` announces a longer body than it sends.
    fn serve(routes: Vec<(&'static str, Vec<u8>, bool)>) -> Server {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let addr = listener.local_addr().unwrap().to_string();
        let stop = Arc::new(Mutex::new(false));
        let routes = Arc::new(routes);
        std::thread::spawn(move || {
            for stream in listener.incoming() {
                let Ok(mut stream) = stream else { break };
                let routes = routes.clone();
                std::thread::spawn(move || {
                    let mut buf = [0u8; 4096];
                    let n = stream.read(&mut buf).unwrap_or(0);
                    let head = String::from_utf8_lossy(&buf[..n]).to_string();
                    let path = head.split_whitespace().nth(1).unwrap_or("/").to_owned();
                    match routes.iter().find(|(p, _, _)| path.starts_with(p)) {
                        Some((_, body, truncate)) => {
                            let announced = if *truncate {
                                body.len() + 4096
                            } else {
                                body.len()
                            };
                            let _ = write!(
                                stream,
                                "HTTP/1.1 200 OK\r\nContent-Length: {announced}\r\nConnection: close\r\n\r\n"
                            );
                            let _ = stream.write_all(body);
                        }
                        None => {
                            let _ = write!(stream, "HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n");
                        }
                    }
                });
            }
        });
        Server { addr, _stop: stop }
    }

    struct Keys {
        dir: PathBuf,
        pubkey: String,
    }

    fn cli() -> Option<PathBuf> {
        let cli = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../node_modules/@tauri-apps/cli/tauri.js");
        cli.is_file().then_some(cli)
    }

    fn node(args: &[&str]) -> Option<String> {
        let out = Command::new("node").args(args).output().ok()?;
        out.status
            .success()
            .then(|| String::from_utf8_lossy(&out.stdout).to_string())
    }

    /// A throwaway minisign key pair, created per test run and never committed.
    fn keys(tag: &str) -> Option<Keys> {
        let cli = cli()?;
        let dir = std::env::temp_dir().join(format!("studio-updater-{tag}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).ok()?;
        let key = dir.join("k.key");
        node(&[
            cli.to_str()?,
            "signer",
            "generate",
            "--ci",
            "-w",
            key.to_str()?,
            "-p",
            "pw",
        ])?;
        let pubkey = std::fs::read_to_string(dir.join("k.key.pub")).ok()?;
        Some(Keys { dir, pubkey })
    }

    fn sign(keys: &Keys, file: &std::path::Path, version: &str) -> Option<String> {
        let cli = cli()?;
        node(&[
            cli.to_str()?,
            "signer",
            "sign",
            "-f",
            keys.dir.join("k.key").to_str()?,
            "-p",
            "pw",
            "--app-version",
            version,
            file.to_str()?,
        ])?;
        std::fs::read_to_string(format!("{}.sig", file.display())).ok()
    }

    fn app_with(keys_pub: &str, endpoint: &str) -> tauri::App<tauri::test::MockRuntime> {
        let mut context = tauri::test::mock_context(tauri::test::noop_assets());
        context.config_mut().plugins.0.insert(
            "updater".into(),
            serde_json::json!({
                "pubkey": keys_pub,
                "endpoints": [endpoint],
                "dangerousInsecureTransportProtocol": true,
                "requireSignedVersion": true
            }),
        );
        tauri::test::mock_builder()
            .plugin(tauri_plugin_updater::Builder::new().build())
            .build(context)
            .expect("mock app")
    }

    /// The manifest platform key the plugin looks up on this host.
    fn platform_key() -> String {
        tauri_plugin_updater::target().expect("supported target")
    }

    fn manifest_for_host(version: &str, url: &str, signature: &str) -> Vec<u8> {
        let key = platform_key();
        serde_json::to_vec(&serde_json::json!({
            "version": version,
            "notes": "test release",
            "platforms": { key: { "url": url, "signature": signature } }
        }))
        .unwrap()
    }

    #[test]
    fn the_update_flow_accepts_a_signed_release_and_refuses_every_bad_one() {
        tauri::async_runtime::block_on(update_flow());
    }

    async fn update_flow() {
        let Some(keys) = keys("flow") else {
            eprintln!("skipped: run `npm ci` in desktop/ to enable the signed-update tests");
            return;
        };
        let artifact = b"NSIS-INSTALLER-BYTES".to_vec();
        let file = keys.dir.join("setup.exe");
        std::fs::write(&file, &artifact).unwrap();
        let signature = sign(&keys, &file, "99.0.0").expect("signed");
        let newer = "99.0.0";

        // A second, unrelated key: signatures made with it must be refused.
        let other = self::keys("other").expect("second key");
        let other_sig = sign(&other, &file, "99.0.0").expect("signed by the wrong key");

        let base = |server: &Server| format!("http://{}", server.addr);
        let server = serve(vec![
            ("/good/latest.json", vec![], false),
            ("/artifact", artifact.clone(), false),
            ("/corrupt", b"NSIS-INSTALLER-BYTEZ".to_vec(), false),
            ("/cut", artifact.clone(), true),
        ]);
        // Routes need the (dynamic) server address inside the manifests, so a
        // second server instance serves the manifests.
        let art = format!("{}/artifact", base(&server));
        let corrupt = format!("{}/corrupt", base(&server));
        let cut = format!("{}/cut", base(&server));
        let manifests = serve(vec![
            ("/ok", manifest_for_host(newer, &art, &signature), false),
            (
                "/same",
                manifest_for_host(env!("CARGO_PKG_VERSION"), &art, &signature),
                false,
            ),
            ("/bad-json", b"{ not json".to_vec(), false),
            (
                "/no-platform",
                serde_json::to_vec(&serde_json::json!({"version": newer, "platforms": {}}))
                    .unwrap(),
                false,
            ),
            (
                "/wrong-key",
                manifest_for_host(newer, &art, &other_sig),
                false,
            ),
            (
                "/corrupt",
                manifest_for_host(newer, &corrupt, &signature),
                false,
            ),
            ("/cut", manifest_for_host(newer, &cut, &signature), false),
            (
                "/inflated",
                manifest_for_host("100.0.0", &art, &signature),
                false,
            ),
        ]);

        let run = |route: &'static str| {
            let endpoint = format!("http://{}{route}", manifests.addr);
            let pubkey = keys.pubkey.clone();
            async move {
                let app = app_with(&pubkey, &endpoint);
                let state = UpdateState::new(true);
                let checked = check(app.handle(), &state).await;
                (checked, state)
            }
        };

        // No update available.
        let (status, _) = run("/same").await;
        assert!(
            matches!(status, Ok(UpdateStatus::UpToDate { .. })),
            "{status:?}"
        );
        // Invalid metadata.
        for route in ["/bad-json", "/no-platform", "/missing"] {
            let (status, _) = run(route).await;
            assert!(status.is_err(), "{route}: {status:?}");
            assert_eq!(status.unwrap_err().code, "invalid_metadata", "{route}");
        }
        // Update available, downloaded and verified.
        let (status, state) = run("/ok").await;
        match status {
            Ok(UpdateStatus::Available { version, .. }) => assert_eq!(version, newer),
            other => panic!("expected an available update, got {other:?}"),
        }
        let (_, bytes) = download_verified(&state)
            .await
            .expect("signed artifact verifies");
        assert_eq!(bytes, artifact);
        // Consumed: a second install without a new check is refused.
        assert_eq!(
            download_verified(&state).await.err().expect("refused").code,
            "no_pending_update"
        );

        // Signature made by another key, corrupted artifact, inflated version:
        // refused, and the release stays pending for a retry.
        for route in ["/wrong-key", "/corrupt", "/inflated"] {
            let (status, state) = run(route).await;
            assert!(
                matches!(status, Ok(UpdateStatus::Available { .. })),
                "{route}: {status:?}"
            );
            let refused = download_verified(&state).await.err().expect("refused");
            assert_eq!(refused.code, "invalid_signature", "{route}");
            assert!(
                state.pending.lock().unwrap().is_some(),
                "{route}: retry must stay possible"
            );
        }
        // Interrupted download: a network error, retryable.
        let (status, state) = run("/cut").await;
        assert!(matches!(status, Ok(UpdateStatus::Available { .. })));
        let cut_off = download_verified(&state).await.err().expect("refused");
        assert_eq!(cut_off.code, "network");
        assert!(state.pending.lock().unwrap().is_some());

        // Server unreachable: a network error, never a panic.
        let app = app_with(&keys.pubkey, "http://127.0.0.1:9/none");
        let state = UpdateState::new(true);
        assert_eq!(
            check(app.handle(), &state).await.unwrap_err().code,
            "network"
        );
        // Unconfigured build.
        let state = UpdateState::new(false);
        assert_eq!(
            check(app.handle(), &state).await,
            Ok(UpdateStatus::NotConfigured)
        );
        let _ = std::fs::remove_dir_all(&keys.dir);
        let _ = std::fs::remove_dir_all(&other.dir);
    }
}
