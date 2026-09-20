//! P2 daemon-gate spike: launch, talk to and observe ONE fixed local sidecar.
//!
//! This is deliberately not the P4 supervisor. It proves that Tauri can find a
//! packaged executable, exchange `studio.local/v1` messages over stdio, see
//! the process end, and do so without any generic shell. It has no restart,
//! no ownership/lock handling, no attach and no lifecycle commands.
//!
//! Hard limits: the executable is a fixed basename resolved next to the app
//! binary (never a path or argument coming from the renderer), it is started
//! without arguments, and the only thing written to it is a bridge request that
//! already passed the allowlist.

use serde::Serialize;
use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::mpsc::{self, Receiver, RecvTimeoutError};
use std::sync::{Arc, Mutex};
use std::time::Duration;

pub const SIDECAR_BASENAME: &str = "studio-daemon-spike";
const EXCHANGE_TIMEOUT: Duration = Duration::from_secs(20);
const MAX_LINE_BYTES: usize = 2 * 1024 * 1024;

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
#[serde(tag = "state", rename_all = "snake_case")]
pub enum SidecarState {
    /// Never started (started lazily by the first served bridge request).
    NotStarted,
    Running { pid: u32 },
    Exited { code: Option<i32> },
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
}

#[derive(Clone, Default)]
pub struct Sidecar(Arc<Mutex<Inner>>);

fn sidecar_path() -> Option<PathBuf> {
    let exe = std::env::current_exe().ok()?;
    let name = if cfg!(windows) {
        format!("{SIDECAR_BASENAME}.exe")
    } else {
        SIDECAR_BASENAME.to_owned()
    };
    Some(exe.parent()?.join(name))
}

impl Inner {
    fn spawn(&mut self) -> Result<(), ExchangeError> {
        self.started = true;
        let Some(path) = sidecar_path().filter(|p| p.is_file()) else {
            self.unavailable = true;
            return Err(ExchangeError::Unavailable);
        };
        let mut cmd = Command::new(path);
        cmd.stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::null());
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
            for line in BufReader::new(stdout).lines() {
                match line {
                    Ok(l) if l.len() <= MAX_LINE_BYTES => {
                        if tx.send(l).is_err() {
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
        if let Some(code) = self.exit {
            return SidecarState::Exited { code };
        }
        if self.unavailable {
            return SidecarState::Unavailable;
        }
        SidecarState::NotStarted
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
    pub fn state(&self) -> SidecarState {
        self.0.lock().map(|mut g| g.state()).unwrap_or(SidecarState::Unavailable)
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
            // Ended earlier: report it, do not silently respawn (P4 concern).
            return Err(ExchangeError::Crashed { code: g.exit.flatten() });
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
                Err(ExchangeError::Crashed { code: g.exit.flatten() })
            }
        }
    }

    /// Ask the sidecar to end (EOF on stdin), then force it if it lingers.
    pub fn shutdown(&self) {
        if let Ok(mut g) = self.0.lock() {
            g.io = None; // closes stdin: a well-behaved sidecar exits on EOF
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
    fn the_sidecar_name_is_fixed_and_path_free() {
        assert!(!SIDECAR_BASENAME.contains(['/', '\\', ' ', '.']));
    }
}
