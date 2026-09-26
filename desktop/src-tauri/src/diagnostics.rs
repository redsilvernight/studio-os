//! P10 diagnostics: where the data lives, what runs, and a redacted export.
//!
//! Read-only apart from the export file, which is written inside the daemon
//! data directory (never a path chosen by the renderer). Secrets are never
//! read: the credential vault is not touched, the settings file only holds a
//! validated origin, and log lines pass through `redact` before they leave.

use crate::sidecar::{self, SidecarCompat, SidecarManifest, SidecarState};
use regex::Regex;
use serde::Serialize;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::OnceLock;
use std::time::{SystemTime, UNIX_EPOCH};

/// Highest on-disk data format this build understands (`format.json`).
/// Kept in step with `studio_client.data_format.DATA_FORMAT_VERSION`.
pub const SUPPORTED_DATA_FORMAT: u32 = 1;
const FORMAT_FILE: &str = "format.json";
const MAX_LOG_TAIL: u64 = 256 * 1024;
const MAX_EXPORTS_KEPT: usize = 5;

/// The daemon data root, resolved exactly as the Python client does:
/// `%APPDATA%\StudioOS` on Windows, `$XDG_CONFIG_HOME/studio-os` elsewhere,
/// with a `-Dev` / `-dev` suffix for the development channel.
pub fn daemon_data_dir() -> Option<PathBuf> {
    let dev = crate::info::dev_channel();
    if cfg!(windows) {
        let base = std::env::var_os("APPDATA")
            .filter(|v| !v.is_empty())
            .map(PathBuf::from)
            .or_else(dirs::config_dir)?;
        Some(base.join(if dev { "StudioOS-Dev" } else { "StudioOS" }))
    } else {
        let base = std::env::var_os("XDG_CONFIG_HOME")
            .filter(|v| !v.is_empty())
            .map(PathBuf::from)
            .or_else(|| dirs::home_dir().map(|h| h.join(".config")))?;
        Some(base.join(if dev { "studio-os-dev" } else { "studio-os" }))
    }
}

pub fn logs_dir(data: &Path) -> PathBuf {
    data.join("logs")
}

pub fn diagnostics_dir(data: &Path) -> PathBuf {
    data.join("diagnostics")
}

fn patterns() -> &'static [(Regex, &'static str)] {
    static P: OnceLock<Vec<(Regex, &'static str)>> = OnceLock::new();
    P.get_or_init(|| {
        let build = |re: &str, rep: &'static str| (Regex::new(re).expect("static pattern"), rep);
        vec![
            build(
                r#"(?i)("[A-Za-z0-9_.-]*?(?:token|secret(?:[_-]?(?:access[_-]?)?key)?|password|passwd|api[_-]?key|private[_-]?key|credentials?|signature|authorization)"\s*:\s*")(?:[^"\\]|\\.)*(")"#,
                "${1}[REDACTED]${2}",
            ),
            build(
                r#"(?i)('[A-Za-z0-9_.-]*?(?:token|secret(?:[_-]?(?:access[_-]?)?key)?|password|passwd|api[_-]?key|private[_-]?key|credentials?|signature|authorization)'\s*:\s*b?')(?:[^'\\]|\\.)*(')"#,
                "${1}[REDACTED]${2}",
            ),
            build(r"(?i)(authorization\s*[:=]\s*(?:bearer\s+)?)[^\s,;]+", "${1}[REDACTED]"),
            build(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]{8,}", "${1}[REDACTED]"),
            build(
                r#"(?i)(token|secret(?:[_-]?(?:access[_-]?)?key)?|password|passwd|api[_-]?key|private[_-]?key|credentials?|signature|x-amz-signature)(["']?\s*[:=]\s*["']?)[^\s,;&"'{}\[\]]+"#,
                "${1}${2}[REDACTED]",
            ),
            build(r"(?i)([?&](?:x-amz-[^=&?\s]+|signature|token|key)=)[^&\s]+", "${1}[REDACTED]"),
            build(r"(?i)([a-z][a-z0-9+.-]*://)[^/\s:@]+:[^/\s@]+@", "${1}[REDACTED]@"),
        ]
    })
}

/// Redact secrets and the user's profile path from free text.
///
/// Same secret policy as `studio_client.daemon.logging.redact_text`, which
/// masks them before they reach daemon.log; both are checked against
/// `tests/fixtures/log_redaction_vectors.json`.
pub fn redact(input: &str) -> String {
    let mut out = input.to_owned();
    for (re, rep) in patterns() {
        out = re.replace_all(&out, *rep).into_owned();
    }
    redact_home(&out)
}

fn redact_home(input: &str) -> String {
    let Some(home) = dirs::home_dir() else {
        return input.to_owned();
    };
    let home = home.to_string_lossy().into_owned();
    if home.len() < 4 {
        return input.to_owned();
    }
    let forward = home.replace('\\', "/");
    let escaped = home.replace('\\', "\\\\");
    input
        .replace(&escaped, "%USERPROFILE%")
        .replace(&home, "%USERPROFILE%")
        .replace(&forward, "%USERPROFILE%")
}

fn display(path: &Path) -> String {
    redact_home(&path.to_string_lossy())
}

#[derive(Debug, Serialize, PartialEq, Eq)]
#[serde(tag = "state", rename_all = "snake_case")]
pub enum DataFormat {
    /// No marker yet (fresh install or pre-P10 data): the daemon stamps it.
    Unstamped,
    Supported {
        format: u32,
    },
    /// Written by a newer build: this one must not touch the data.
    TooNew {
        format: u32,
        supported: u32,
    },
    Unreadable,
}

pub fn read_data_format(data: &Path) -> DataFormat {
    let Ok(text) = fs::read_to_string(data.join(FORMAT_FILE)) else {
        return DataFormat::Unstamped;
    };
    let format = serde_json::from_str::<serde_json::Value>(&text)
        .ok()
        .and_then(|v| v.get("format").and_then(serde_json::Value::as_u64))
        .and_then(|n| u32::try_from(n).ok());
    match format {
        Some(f) if f > SUPPORTED_DATA_FORMAT => DataFormat::TooNew {
            format: f,
            supported: SUPPORTED_DATA_FORMAT,
        },
        Some(f) => DataFormat::Supported { format: f },
        None => DataFormat::Unreadable,
    }
}

#[derive(Debug, Serialize)]
pub struct LogFile {
    pub name: String,
    pub bytes: u64,
}

#[derive(Debug, Serialize)]
pub struct DataLocations {
    /// Daemon data root (config, outbox, cache, logs): survives upgrade and uninstall.
    pub daemon_data_dir: Option<String>,
    pub logs_dir: Option<String>,
    pub shell_settings_dir: Option<String>,
    /// Where the application binaries live (replaced on upgrade, removed on uninstall).
    pub install_dir: Option<String>,
    pub data_format: DataFormat,
    pub logs: Vec<LogFile>,
}

#[derive(Debug, Serialize)]
pub struct SidecarReport {
    pub state: SidecarState,
    pub present: bool,
    pub manifest: Option<SidecarManifest>,
    pub compat: SidecarCompat,
}

#[derive(Debug, Serialize)]
pub struct Diagnostics {
    pub desktop_version: &'static str,
    pub protocol: &'static str,
    pub os: &'static str,
    pub arch: &'static str,
    pub sidecar: SidecarReport,
    pub server_origin: Option<String>,
    pub updates_configured: bool,
    pub locations: DataLocations,
}

fn list_logs(dir: &Path) -> Vec<LogFile> {
    let Ok(read) = fs::read_dir(dir) else {
        return Vec::new();
    };
    let mut files: Vec<LogFile> = read
        .flatten()
        .filter_map(|entry| {
            let meta = entry.metadata().ok().filter(|m| m.is_file())?;
            Some(LogFile {
                name: entry.file_name().to_string_lossy().into_owned(),
                bytes: meta.len(),
            })
        })
        .collect();
    files.sort_by(|a, b| a.name.cmp(&b.name));
    files
}

pub fn collect(
    sidecar_state: SidecarState,
    server_origin: Option<String>,
    shell_settings_dir: Option<&Path>,
    updates_configured: bool,
) -> Diagnostics {
    let data = daemon_data_dir();
    let sidecar_dir = sidecar::sidecar_dir();
    let manifest = sidecar_dir.as_deref().and_then(sidecar::read_manifest);
    let present = sidecar_dir.as_deref().is_some_and(|d| {
        d.join(if cfg!(windows) {
            "studio-daemon.exe"
        } else {
            "studio-daemon"
        })
        .is_file()
    });
    let install_dir = std::env::current_exe()
        .ok()
        .and_then(|e| e.parent().map(Path::to_path_buf));
    Diagnostics {
        desktop_version: crate::info::DESKTOP_VERSION,
        protocol: crate::allowlist::PROTOCOL,
        os: std::env::consts::OS,
        arch: std::env::consts::ARCH,
        sidecar: SidecarReport {
            state: sidecar_state,
            present,
            compat: sidecar::compat(manifest.as_ref()),
            manifest,
        },
        server_origin,
        updates_configured,
        locations: DataLocations {
            daemon_data_dir: data.as_deref().map(display),
            logs_dir: data.as_deref().map(|d| display(&logs_dir(d))),
            shell_settings_dir: shell_settings_dir.map(display),
            install_dir: install_dir.as_deref().map(display),
            data_format: data
                .as_deref()
                .map_or(DataFormat::Unstamped, read_data_format),
            logs: data
                .as_deref()
                .map(|d| list_logs(&logs_dir(d)))
                .unwrap_or_default(),
        },
    }
}

fn tail_of(path: &Path, max: u64) -> String {
    use std::io::{Read, Seek, SeekFrom};
    let Ok(mut file) = fs::File::open(path) else {
        return String::new();
    };
    let len = file.metadata().map(|m| m.len()).unwrap_or(0);
    if file.seek(SeekFrom::Start(len.saturating_sub(max))).is_err() {
        return String::new();
    }
    let mut bytes = Vec::new();
    let _ = file.take(max).read_to_end(&mut bytes);
    String::from_utf8_lossy(&bytes).into_owned()
}

/// Write `diagnostics-<unix seconds>.json` into `<data>/diagnostics/`: the
/// snapshot plus the redacted tail of the daemon log. Old exports are pruned.
pub fn export(diagnostics: &Diagnostics, data: &Path) -> std::io::Result<PathBuf> {
    let dir = diagnostics_dir(data);
    fs::create_dir_all(&dir)?;
    let stamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let body = serde_json::json!({
        "generated_at_unix": stamp,
        "diagnostics": diagnostics,
        "daemon_log_tail": redact(&tail_of(&logs_dir(data).join("daemon.log"), MAX_LOG_TAIL)),
    });
    let path = dir.join(format!("diagnostics-{stamp}.json"));
    fs::write(
        &path,
        serde_json::to_vec_pretty(&body).map_err(std::io::Error::other)?,
    )?;
    prune_exports(&dir);
    Ok(path)
}

fn prune_exports(dir: &Path) {
    let Ok(read) = fs::read_dir(dir) else { return };
    let mut names: Vec<PathBuf> = read
        .flatten()
        .map(|e| e.path())
        .filter(|p| {
            p.file_name()
                .and_then(|n| n.to_str())
                .is_some_and(|n| n.starts_with("diagnostics-") && n.ends_with(".json"))
        })
        .collect();
    names.sort();
    while names.len() > MAX_EXPORTS_KEPT {
        let _ = fs::remove_file(names.remove(0));
    }
}

/// Which folder `open_data_folder` may reveal. A closed enum: the renderer
/// never supplies a path.
#[derive(Debug, Clone, Copy, serde::Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Folder {
    Logs,
    Diagnostics,
}

pub fn folder_path(kind: Folder, data: &Path) -> PathBuf {
    match kind {
        Folder::Logs => logs_dir(data),
        Folder::Diagnostics => diagnostics_dir(data),
    }
}

/// Reveal a folder in Explorer. The fixed system binary is addressed by its
/// absolute path (`%SystemRoot%`), never through PATH or the working directory.
pub fn reveal(folder: &Path) -> std::io::Result<()> {
    fs::create_dir_all(folder)?;
    #[cfg(windows)]
    {
        let root = std::env::var_os("SystemRoot")
            .ok_or_else(|| std::io::Error::other("SystemRoot unset"))?;
        std::process::Command::new(PathBuf::from(root).join("explorer.exe"))
            .arg(folder)
            .spawn()?;
        Ok(())
    }
    #[cfg(not(windows))]
    {
        webbrowser::open(&folder.to_string_lossy()).map_err(std::io::Error::other)?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tmp(tag: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("studio-diag-{tag}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn secrets_are_redacted_from_log_text() {
        let text = "Authorization: Bearer abc.def-123456 token=xyz password: hunter2 \
                    GET https://user:pw@host/x?signature=deadbeef&a=1 api_key=AKIA1234";
        let out = redact(text);
        for leaked in [
            "abc.def-123456",
            "xyz",
            "hunter2",
            "pw@",
            "deadbeef",
            "AKIA1234",
        ] {
            assert!(!out.contains(leaked), "{leaked} leaked: {out}");
        }
        assert!(out.contains("[REDACTED]"));
        assert!(out.contains("a=1"), "non-secret query parts are kept");
    }

    #[test]
    fn shared_redaction_vectors_hold() {
        let vectors: serde_json::Value = serde_json::from_str(include_str!(
            "../../../tests/fixtures/log_redaction_vectors.json"
        ))
        .unwrap();
        for case in vectors["redacted"].as_array().unwrap() {
            let name = case["name"].as_str().unwrap();
            let out = redact(case["input"].as_str().unwrap());
            for secret in case["secrets"].as_array().unwrap() {
                let secret = secret.as_str().unwrap();
                assert!(!out.contains(secret), "{name}: {secret} leaked: {out}");
            }
            for kept in case["kept"].as_array().into_iter().flatten() {
                let kept = kept.as_str().unwrap();
                assert!(out.contains(kept), "{name}: lost {kept}: {out}");
            }
            assert_eq!(redact(&out), out, "{name}: not idempotent");
        }
        for value in vectors["unchanged"].as_array().unwrap() {
            let value = value.as_str().unwrap();
            assert_eq!(redact(value), value);
        }
    }

    #[test]
    fn the_user_profile_path_is_masked() {
        let home = dirs::home_dir().unwrap();
        let out = redact(&format!("opened {}\\StudioOS\\logs", home.display()));
        assert!(!out.contains(&home.to_string_lossy().to_string()));
        assert!(out.contains("%USERPROFILE%"));
    }

    #[test]
    fn the_data_format_marker_fails_closed_on_a_newer_format() {
        let dir = tmp("format");
        assert_eq!(read_data_format(&dir), DataFormat::Unstamped);
        fs::write(dir.join(FORMAT_FILE), r#"{"format":1}"#).unwrap();
        assert_eq!(read_data_format(&dir), DataFormat::Supported { format: 1 });
        fs::write(dir.join(FORMAT_FILE), r#"{"format":99}"#).unwrap();
        assert_eq!(
            read_data_format(&dir),
            DataFormat::TooNew {
                format: 99,
                supported: SUPPORTED_DATA_FORMAT
            }
        );
        fs::write(dir.join(FORMAT_FILE), "garbage").unwrap();
        assert_eq!(read_data_format(&dir), DataFormat::Unreadable);
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn an_export_holds_a_redacted_log_tail_and_is_pruned() {
        let data = tmp("export");
        fs::create_dir_all(logs_dir(&data)).unwrap();
        fs::write(
            logs_dir(&data).join("daemon.log"),
            "ok line\nauthorization: Bearer topsecret123\n",
        )
        .unwrap();
        let diag = collect(
            SidecarState::NotStarted,
            Some("https://studio.example.com".into()),
            None,
            false,
        );
        let path = export(&diag, &data).unwrap();
        let text = fs::read_to_string(&path).unwrap();
        assert!(text.contains("ok line"));
        assert!(!text.contains("topsecret123"));
        assert!(path.starts_with(diagnostics_dir(&data)));
        for i in 0..8 {
            let extra = diagnostics_dir(&data).join(format!("diagnostics-{i:010}.json"));
            fs::write(extra, "{}").unwrap();
        }
        prune_exports(&diagnostics_dir(&data));
        let kept = fs::read_dir(diagnostics_dir(&data)).unwrap().count();
        assert_eq!(kept, MAX_EXPORTS_KEPT);
        let _ = fs::remove_dir_all(&data);
    }

    #[test]
    fn folders_are_a_closed_choice_under_the_data_root() {
        let data = PathBuf::from("data-root");
        assert_eq!(folder_path(Folder::Logs, &data), data.join("logs"));
        assert_eq!(
            folder_path(Folder::Diagnostics, &data),
            data.join("diagnostics")
        );
        assert!(serde_json::from_str::<Folder>("\"../../etc\"").is_err());
    }
}
