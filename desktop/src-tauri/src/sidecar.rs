//! P4 supervisor for the fixed Studio OS daemon sidecar.
//!
//! Hard limits: the executable is a fixed basename resolved next to the app
//! binary (never a path or argument coming from the renderer), it is started
//! without arguments, and the only thing written to it is a bridge request that
//! already passed the allowlist. The one thing the Desktop tells it is the
//! validated server origin, through a fixed environment variable.

use serde::Serialize;
use std::collections::VecDeque;
use std::io::{BufRead, BufReader, Read, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::mpsc::{self, Receiver, RecvTimeoutError};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

pub const SIDECAR_BASENAME: &str = "studio-daemon";
const SIDECAR_DIR: &str = "sidecar";
const MANIFEST_FILE: &str = "sidecar-manifest.json";
pub const SERVER_ORIGIN_ENV: &str = "STUDIO_DESKTOP_SERVER_ORIGIN";
const EXCHANGE_TIMEOUT: Duration = Duration::from_secs(20);
const MAX_LINE_BYTES: usize = 2 * 1024 * 1024;
const RESTART_WINDOW: Duration = Duration::from_secs(60);
const MAX_RESTARTS: usize = 3;

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
#[serde(tag = "state", rename_all = "snake_case")]
pub enum SidecarState {
    /// Never started (started lazily by the first served bridge request).
    NotStarted,
    Running {
        pid: u32,
    },
    Exited {
        code: Option<i32>,
    },
    Recovering {
        attempts: usize,
    },
    Abandoned {
        attempts: usize,
    },
    /// Binary absent or not launchable. Never a silent success.
    Unavailable,
}

#[derive(Debug)]
pub enum ExchangeError {
    Unavailable,
    Crashed { code: Option<i32> },
    Timeout,
    Io,
}

struct Io {
    stdin: ChildStdin,
    lines: Receiver<String>,
}

#[derive(Default)]
struct Inner {
    child: Option<Child>,
    io: Option<Io>,
    started: bool,
    exit: Option<Option<i32>>,
    unavailable: bool,
    restarts: VecDeque<Instant>,
    abandoned: bool,
    origin: Option<String>,
}

#[derive(Clone, Default)]
pub struct Sidecar(Arc<Mutex<Inner>>);

/// Directory holding the frozen daemon (a PyInstaller one-folder build shipped
/// as an app resource): `<install dir>/sidecar`. Nothing is ever extracted to a
/// temp directory at run time.
pub fn sidecar_dir() -> Option<PathBuf> {
    let exe = std::env::current_exe().ok()?;
    Some(exe.parent()?.join(SIDECAR_DIR))
}

fn sidecar_path() -> Option<PathBuf> {
    let name = if cfg!(windows) {
        format!("{SIDECAR_BASENAME}.exe")
    } else {
        SIDECAR_BASENAME.to_owned()
    };
    Some(sidecar_dir()?.join(name))
}

/// Build-time description of the frozen daemon (`sidecar-manifest.json`).
#[derive(Debug, Clone, Serialize, serde::Deserialize, PartialEq, Eq)]
pub struct SidecarManifest {
    pub daemon_version: String,
    pub desktop_version: String,
    pub protocol: String,
}

pub fn read_manifest(dir: &Path) -> Option<SidecarManifest> {
    let text = std::fs::read_to_string(dir.join(MANIFEST_FILE)).ok()?;
    serde_json::from_str(&text).ok()
}

/// How the bundled daemon relates to this shell. A different bridge protocol is
/// refused at spawn (fail closed); a different build version only warns, since
/// capability negotiation already handles additive drift.
#[derive(Debug, Clone, Copy, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum SidecarCompat {
    Compatible,
    VersionDrift,
    ProtocolMismatch,
    /// No manifest (development build): nothing to compare.
    Unknown,
}

pub fn compat(manifest: Option<&SidecarManifest>) -> SidecarCompat {
    match manifest {
        None => SidecarCompat::Unknown,
        Some(m) if m.protocol != crate::allowlist::PROTOCOL => SidecarCompat::ProtocolMismatch,
        Some(m) if m.desktop_version != crate::info::DESKTOP_VERSION => SidecarCompat::VersionDrift,
        Some(_) => SidecarCompat::Compatible,
    }
}

fn persist_after_desktop_close() -> bool {
    std::env::var("STUDIO_DESKTOP_KEEP_DAEMON")
        .map(|value| value == "1" || value.eq_ignore_ascii_case("true"))
        .unwrap_or(false)
}

impl Inner {
    fn spawn(&mut self) -> Result<(), ExchangeError> {
        self.started = true;
        let Some(path) = sidecar_path().filter(|p| p.is_file()) else {
            self.unavailable = true;
            return Err(ExchangeError::Unavailable);
        };
        let manifest = path.parent().and_then(read_manifest);
        if compat(manifest.as_ref()) == SidecarCompat::ProtocolMismatch {
            self.unavailable = true;
            return Err(ExchangeError::Unavailable);
        }
        let mut cmd = Command::new(path);
        cmd.stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null());
        if persist_after_desktop_close() {
            cmd.env("STUDIO_DAEMON_PERSIST", "1");
        }
        match &self.origin {
            Some(origin) => cmd.env(SERVER_ORIGIN_ENV, origin),
            None => cmd.env_remove(SERVER_ORIGIN_ENV),
        };
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
        }
        let mut child = match cmd.spawn() {
            Ok(c) => c,
            Err(_) => {
                self.unavailable = true;
                return Err(ExchangeError::Unavailable);
            }
        };
        let stdin = child.stdin.take().ok_or(ExchangeError::Io)?;
        let stdout = child.stdout.take().ok_or(ExchangeError::Io)?;
        let (tx, rx) = mpsc::channel::<String>();
        std::thread::spawn(move || {
            let mut reader = BufReader::new(stdout);
            loop {
                let mut bytes = Vec::with_capacity(4096);
                let read = reader
                    .by_ref()
                    .take((MAX_LINE_BYTES + 1) as u64)
                    .read_until(b'\n', &mut bytes);
                match read {
                    Ok(0) => break,
                    Ok(_) if bytes.len() <= MAX_LINE_BYTES && bytes.ends_with(b"\n") => {
                        bytes.pop();
                        if bytes.ends_with(b"\r") {
                            bytes.pop();
                        }
                        let Ok(line) = String::from_utf8(bytes) else {
                            break;
                        };
                        if tx.send(line).is_err() {
                            break;
                        }
                    }
                    _ => break,
                }
            }
        });
        self.child = Some(child);
        self.io = Some(Io { stdin, lines: rx });
        Ok(())
    }

    /// Reap the child if it ended. Returns the recorded exit, if any.
    fn observe(&mut self) {
        if let Some(child) = self.child.as_mut() {
            if let Ok(Some(status)) = child.try_wait() {
                self.exit = Some(status.code());
                self.child = None;
                self.io = None;
            }
        }
    }

    fn state(&mut self) -> SidecarState {
        self.observe();
        if let Some(child) = self.child.as_ref() {
            return SidecarState::Running { pid: child.id() };
        }
        if self.unavailable {
            return SidecarState::Unavailable;
        }
        if self.abandoned {
            return SidecarState::Abandoned {
                attempts: self.restarts.len(),
            };
        }
        if let Some(code) = self.exit {
            if !self.restarts.is_empty() {
                return SidecarState::Recovering {
                    attempts: self.restarts.len(),
                };
            }
            return SidecarState::Exited { code };
        }
        SidecarState::NotStarted
    }

    fn restart(&mut self) -> Result<(), ExchangeError> {
        let now = Instant::now();
        while self
            .restarts
            .front()
            .is_some_and(|attempt| now.duration_since(*attempt) > RESTART_WINDOW)
        {
            self.restarts.pop_front();
        }
        if self.restarts.len() >= MAX_RESTARTS {
            self.abandoned = true;
            return Err(ExchangeError::Crashed {
                code: self.exit.flatten(),
            });
        }
        self.restarts.push_back(now);
        self.exit = None;
        self.spawn()
    }

    fn kill(&mut self) {
        self.io = None;
        if let Some(mut child) = self.child.take() {
            let _ = child.kill();
            self.exit = Some(child.wait().ok().and_then(|s| s.code()));
        }
    }
}

impl Sidecar {
    pub(crate) fn with_origin(origin: Option<crate::server_origin::ApprovedOrigin>) -> Self {
        let origin = origin.map(crate::server_origin::ApprovedOrigin::into_string);
        Self(Arc::new(Mutex::new(Inner {
            origin,
            ..Inner::default()
        })))
    }

    #[cfg(test)]
    pub fn origin(&self) -> Option<String> {
        self.0.lock().ok().and_then(|g| g.origin.clone())
    }

    pub fn state(&self) -> SidecarState {
        self.0
            .lock()
            .map(|mut g| g.state())
            .unwrap_or(SidecarState::Unavailable)
    }

    /// One request line in, one response line out. Blocking: call from a
    /// blocking task, never from the async runtime or the UI thread.
    pub fn exchange(&self, line: &str) -> Result<String, ExchangeError> {
        let mut g = self.0.lock().map_err(|_| ExchangeError::Io)?;
        g.observe();
        if !g.started {
            g.spawn()?;
        } else if g.unavailable {
            return Err(ExchangeError::Unavailable);
        } else if g.child.is_none() {
            g.restart()?;
        }
        let io = g.io.as_mut().ok_or(ExchangeError::Io)?;
        let written = io
            .stdin
            .write_all(line.as_bytes())
            .and_then(|_| io.stdin.write_all(b"\n"))
            .and_then(|_| io.stdin.flush());
        let received = match written {
            Ok(()) => io.lines.recv_timeout(EXCHANGE_TIMEOUT),
            Err(_) => Err(RecvTimeoutError::Disconnected),
        };
        match received {
            Ok(answer) => Ok(answer),
            Err(RecvTimeoutError::Timeout) => {
                // A late answer would desynchronise the next exchange.
                g.kill();
                Err(ExchangeError::Timeout)
            }
            Err(RecvTimeoutError::Disconnected) => {
                // Give the OS a moment to publish the exit status.
                for _ in 0..20 {
                    g.observe();
                    if g.child.is_none() {
                        break;
                    }
                    std::thread::sleep(Duration::from_millis(25));
                }
                if g.child.is_some() {
                    g.kill();
                }
                Err(ExchangeError::Crashed {
                    code: g.exit.flatten(),
                })
            }
        }
    }

    /// Ask the sidecar to end (EOF on stdin), then force it if it lingers.
    pub fn shutdown(&self) {
        if let Ok(mut g) = self.0.lock() {
            g.io = None; // closes stdin: a well-behaved sidecar exits on EOF
            if persist_after_desktop_close() {
                g.child = None;
                return;
            }
            for _ in 0..20 {
                g.observe();
                if g.child.is_none() {
                    return;
                }
                std::thread::sleep(Duration::from_millis(50));
            }
            g.kill();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_missing_binary_is_reported_unavailable_not_success() {
        // Test binaries live in target/<profile>/deps: no sidecar next to them.
        let sc = Sidecar::default();
        assert_eq!(sc.state(), SidecarState::NotStarted);
        assert!(matches!(sc.exchange("{}"), Err(ExchangeError::Unavailable)));
        assert_eq!(sc.state(), SidecarState::Unavailable);
        // Stays unavailable: no silent retry loop.
        assert!(matches!(sc.exchange("{}"), Err(ExchangeError::Unavailable)));
    }

    #[test]
    fn restarts_are_bounded_then_the_sidecar_is_abandoned() {
        let mut inner = Inner {
            started: true,
            exit: Some(Some(1)),
            ..Inner::default()
        };
        for _ in 0..MAX_RESTARTS {
            inner.restarts.push_back(Instant::now());
        }
        assert_eq!(
            inner.state(),
            SidecarState::Recovering {
                attempts: MAX_RESTARTS
            }
        );
        assert!(matches!(
            inner.restart(),
            Err(ExchangeError::Crashed { code: Some(1) })
        ));
        assert_eq!(
            inner.state(),
            SidecarState::Abandoned {
                attempts: MAX_RESTARTS
            }
        );
        assert!(matches!(
            inner.restart(),
            Err(ExchangeError::Crashed { .. })
        ));
        assert_eq!(inner.restarts.len(), MAX_RESTARTS);
    }

    #[test]
    fn restarts_older_than_the_window_do_not_count() {
        let mut inner = Inner {
            started: true,
            ..Inner::default()
        };
        let stale = Instant::now()
            .checked_sub(RESTART_WINDOW + Duration::from_secs(1))
            .expect("monotonic clock far enough from its origin");
        for _ in 0..MAX_RESTARTS {
            inner.restarts.push_back(stale);
        }
        let _ = inner.restart();
        assert!(!inner.abandoned);
        assert_eq!(inner.restarts.len(), 1);
    }

    #[test]
    fn only_a_validated_origin_is_kept_for_the_child_environment() {
        assert_eq!(Sidecar::with_origin(None).origin(), None);
        assert_eq!(
            Sidecar::with_origin(crate::server_origin::effective_origin(
                Some("https://Studio.Example.com:443"),
                None,
                None,
            ))
            .origin()
            .as_deref(),
            Some("https://studio.example.com")
        );
        for bad in [
            "http://tauri.localhost",
            "https://user:pw@studio.example.com",
            "https://studio.example.com/api",
            "http://studio.example.com",
            "javascript:alert(1)",
            "https://a.example --flag",
            "",
        ] {
            assert_eq!(
                Sidecar::with_origin(crate::server_origin::effective_origin(
                    Some(bad),
                    None,
                    None,
                ))
                .origin(),
                None,
                "{bad}"
            );
        }
    }

    #[test]
    fn an_explicit_remote_http_build_origin_reaches_the_sidecar_without_weakening_runtime_validation(
    ) {
        let origin = crate::server_origin::effective_origin(
            None,
            Some("http://deploy.example:8080"),
            Some("1"),
        );
        assert_eq!(
            Sidecar::with_origin(origin).origin().as_deref(),
            Some("http://deploy.example:8080")
        );
        assert!(crate::server_origin::validate("http://deploy.example:8080").is_err());
        assert!(crate::server_origin::validate("http://other.example:8080").is_err());
    }

    fn manifest(protocol: &str, version: &str) -> SidecarManifest {
        SidecarManifest {
            daemon_version: "0.1.0".into(),
            desktop_version: version.into(),
            protocol: protocol.into(),
        }
    }

    #[test]
    fn a_sidecar_speaking_another_protocol_is_refused_and_a_version_drift_only_warns() {
        let ok = manifest(crate::allowlist::PROTOCOL, crate::info::DESKTOP_VERSION);
        assert_eq!(compat(Some(&ok)), SidecarCompat::Compatible);
        assert_eq!(compat(None), SidecarCompat::Unknown);
        assert_eq!(
            compat(Some(&manifest(crate::allowlist::PROTOCOL, "0.0.1"))),
            SidecarCompat::VersionDrift
        );
        assert_eq!(
            compat(Some(&manifest(
                "studio.local/v2",
                crate::info::DESKTOP_VERSION
            ))),
            SidecarCompat::ProtocolMismatch
        );
    }

    #[test]
    fn the_manifest_is_read_from_disk_and_a_corrupt_one_is_unknown() {
        let dir =
            std::env::temp_dir().join(format!("studio-sidecar-manifest-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        assert!(read_manifest(&dir).is_none());
        std::fs::write(dir.join(MANIFEST_FILE), "{ not json").unwrap();
        assert!(read_manifest(&dir).is_none());
        let good = manifest("studio.local/v1", "0.1.0");
        std::fs::write(
            dir.join(MANIFEST_FILE),
            serde_json::to_string(&good).unwrap(),
        )
        .unwrap();
        assert_eq!(read_manifest(&dir), Some(good));
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn the_sidecar_name_is_fixed_and_path_free() {
        assert!(!SIDECAR_BASENAME.contains(['/', '\\', ' ', '.']));
    }
}
