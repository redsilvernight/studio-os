//! Runtime-configurable `server_origin` (P3).
//!
//! The origin of the Studi'OS server the Dashboard talks to. It is NOT the
//! Desktop origin (`http://tauri.localhost`, the origin the server allows in
//! CORS): the two are never mixed, and this module refuses the Desktop origin
//! as a server value.
//!
//! This module is the single source of truth for validation. The renderer only
//! maps the machine `reason` codes to messages. The value is non-secret and is
//! stored as a small JSON file in the per-user application config directory.
//! The webview CSP is static per build, so a persisted origin is added to
//! `connect-src` at the next start (never `*`, no other directive is touched).

use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};
use url::{Host, Url};

const MAX_LEN: usize = 2048;
const SETTINGS_FILE: &str = "shell-settings.json";
/// Overrides the config directory (test isolation, portable installs).
pub const CONFIG_DIR_ENV: &str = "STUDIO_DESKTOP_CONFIG_DIR";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OriginError {
    Empty,
    TooLong,
    Invalid,
    UnsupportedScheme,
    CredentialsNotAllowed,
    NotAnOrigin,
    InsecureScheme,
    DesktopOrigin,
}

impl OriginError {
    pub fn code(self) -> &'static str {
        match self {
            Self::Empty => "origin_empty",
            Self::TooLong => "origin_too_long",
            Self::Invalid => "origin_invalid",
            Self::UnsupportedScheme => "origin_unsupported_scheme",
            Self::CredentialsNotAllowed => "origin_credentials_not_allowed",
            Self::NotAnOrigin => "origin_not_an_origin",
            Self::InsecureScheme => "origin_insecure_scheme",
            Self::DesktopOrigin => "origin_is_desktop_origin",
        }
    }

    pub fn message(self) -> &'static str {
        match self {
            Self::Empty => "The server address is empty.",
            Self::TooLong => "The server address is too long.",
            Self::Invalid => "The server address is not a valid URL.",
            Self::UnsupportedScheme => "Only https:// (or http:// for localhost) is supported.",
            Self::CredentialsNotAllowed => "The server address must not contain a user name or password.",
            Self::NotAnOrigin => "Give the server origin only (scheme, host, optional port): no path, query or fragment.",
            Self::InsecureScheme => "http:// is only accepted for localhost or 127.0.0.1; use https://.",
            Self::DesktopOrigin => "This is the Desktop application origin, not a server address.",
        }
    }
}

fn is_local_dev_host(url: &Url) -> bool {
    match url.host() {
        Some(Host::Domain(d)) => d.eq_ignore_ascii_case("localhost"),
        Some(Host::Ipv4(ip)) => ip.octets() == [127, 0, 0, 1],
        _ => false,
    }
}

fn is_desktop_origin_host(url: &Url) -> bool {
    match url.host() {
        Some(Host::Domain(d)) => {
            let d = d.trim_end_matches('.').to_ascii_lowercase();
            d == "tauri.localhost" || d == "ipc.localhost" || d == "tauri"
        }
        _ => false,
    }
}

/// Validate and normalise a server origin (`scheme://host[:port]`, no trailing
/// slash).
pub fn validate(raw: &str) -> Result<String, OriginError> {
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        return Err(OriginError::Empty);
    }
    if trimmed.len() > MAX_LEN {
        return Err(OriginError::TooLong);
    }
    if trimmed.chars().any(|c| c.is_whitespace() || c.is_control() || c == '*') {
        return Err(OriginError::Invalid);
    }
    let url = Url::parse(trimmed).map_err(|_| OriginError::Invalid)?;
    match url.scheme() {
        "http" | "https" => {}
        _ => return Err(OriginError::UnsupportedScheme),
    }
    if !url.username().is_empty() || url.password().is_some() {
        return Err(OriginError::CredentialsNotAllowed);
    }
    if url.host().is_none() {
        return Err(OriginError::Invalid);
    }
    if (url.path() != "/" && !url.path().is_empty()) || url.query().is_some() || url.fragment().is_some() {
        return Err(OriginError::NotAnOrigin);
    }
    if is_desktop_origin_host(&url) {
        return Err(OriginError::DesktopOrigin);
    }
    if url.scheme() == "http" && !is_local_dev_host(&url) {
        return Err(OriginError::InsecureScheme);
    }
    Ok(url.origin().ascii_serialization())
}

/// Add `origin` to the `connect-src` directive of `csp` (created when absent).
/// Idempotent; every other directive is returned untouched.
pub fn csp_with_connect_origin(csp: &str, origin: &str) -> String {
    let mut found = false;
    let mut directives: Vec<String> = csp
        .split(';')
        .map(str::trim)
        .filter(|d| !d.is_empty())
        .map(|d| {
            let mut parts = d.split_whitespace();
            if parts.next() == Some("connect-src") {
                found = true;
                if d.split_whitespace().any(|s| s == origin) {
                    d.to_owned()
                } else {
                    format!("{d} {origin}")
                }
            } else {
                d.to_owned()
            }
        })
        .collect();
    if !found {
        directives.push(format!("connect-src 'self' {origin}"));
    }
    directives.join("; ")
}

#[derive(Debug, Default, Serialize, Deserialize)]
#[serde(default)]
struct SettingsFile {
    server_origin: Option<String>,
}

/// Non-secret shell settings, persisted in the per-user config directory.
#[derive(Debug, Clone)]
pub struct SettingsStore {
    dir: PathBuf,
}

impl SettingsStore {
    pub fn new(dir: PathBuf) -> Self {
        Self { dir }
    }

    /// `<config dir>/<identifier>`, the same place Tauri calls the app config
    /// directory, resolvable before the app is built.
    pub fn for_identifier(identifier: &str) -> Option<Self> {
        if let Some(dir) = std::env::var_os(CONFIG_DIR_ENV).filter(|d| !d.is_empty()) {
            return Some(Self::new(PathBuf::from(dir)));
        }
        dirs::config_dir().map(|base| Self::new(base.join(identifier)))
    }

    fn file(&self) -> PathBuf {
        self.dir.join(SETTINGS_FILE)
    }

    /// The persisted origin. A missing, unreadable or invalid file yields
    /// `None` (the build default applies) — a corrupt file never blocks start.
    pub fn load(&self) -> Option<String> {
        let text = fs::read_to_string(self.file()).ok()?;
        let parsed: SettingsFile = serde_json::from_str(&text).ok()?;
        validate(&parsed.server_origin?).ok()
    }

    /// Persist an already validated origin, or clear it with `None`.
    pub fn save(&self, origin: Option<&str>) -> std::io::Result<()> {
        fs::create_dir_all(&self.dir)?;
        let body = serde_json::to_string_pretty(&SettingsFile { server_origin: origin.map(str::to_owned) })
            .map_err(std::io::Error::other)?;
        write_atomic(&self.file(), body.as_bytes())
    }
}

fn write_atomic(path: &Path, bytes: &[u8]) -> std::io::Result<()> {
    let tmp = path.with_extension("json.tmp");
    fs::write(&tmp, bytes)?;
    fs::rename(&tmp, path)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn https_origins_are_accepted_and_normalised() {
        assert_eq!(validate("https://studio.example.com").unwrap(), "https://studio.example.com");
        assert_eq!(validate("  https://Studio.Example.com:443/ ").unwrap(), "https://studio.example.com");
        assert_eq!(validate("https://studio.example.com:8443").unwrap(), "https://studio.example.com:8443");
    }

    #[test]
    fn http_is_only_accepted_for_local_development() {
        assert_eq!(validate("http://localhost:8000").unwrap(), "http://localhost:8000");
        assert_eq!(validate("http://127.0.0.1:8000").unwrap(), "http://127.0.0.1:8000");
        for bad in ["http://studio.example.com", "http://192.168.1.10:8000", "http://[::1]:8000", "http://10.0.0.1"] {
            assert_eq!(validate(bad), Err(OriginError::InsecureScheme), "{bad}");
        }
    }

    #[test]
    fn invalid_values_are_refused_with_a_reason() {
        let cases = [
            ("", OriginError::Empty),
            ("   ", OriginError::Empty),
            ("studio.example.com", OriginError::Invalid),
            ("https://", OriginError::Invalid),
            ("https://*.example.com", OriginError::Invalid),
            ("https://exa mple.com", OriginError::Invalid),
            ("ftp://studio.example.com", OriginError::UnsupportedScheme),
            ("file:///C:/secret", OriginError::UnsupportedScheme),
            ("javascript:alert(1)", OriginError::UnsupportedScheme),
            ("https://user:pw@studio.example.com", OriginError::CredentialsNotAllowed),
            ("https://user@studio.example.com", OriginError::CredentialsNotAllowed),
            ("https://studio.example.com/api", OriginError::NotAnOrigin),
            ("https://studio.example.com/?x=1", OriginError::NotAnOrigin),
            ("https://studio.example.com/#frag", OriginError::NotAnOrigin),
        ];
        for (raw, want) in cases {
            assert_eq!(validate(raw), Err(want), "{raw:?}");
        }
        assert_eq!(validate(&format!("https://{}.com", "a".repeat(2100))), Err(OriginError::TooLong));
    }

    #[test]
    fn the_desktop_origin_is_never_a_server_origin() {
        for bad in ["http://tauri.localhost", "https://tauri.localhost", "http://ipc.localhost", "https://TAURI.localhost:1420"] {
            assert_eq!(validate(bad), Err(OriginError::DesktopOrigin), "{bad}");
        }
    }

    #[test]
    fn equivalent_spellings_of_the_desktop_origin_are_refused() {
        for bad in [
            "http://tauri.localhost.",
            "https://tauri.localhost..:8443",
            "http://TAURI.LOCALHOST.",
            "http://ipc.localhost.",
            "https://tauri\u{3002}localhost",
            "https://tauri.local\u{FF48}ost",
            "https://%74auri.localhost",
        ] {
            assert_eq!(validate(bad), Err(OriginError::DesktopOrigin), "{bad}");
        }
    }

    #[test]
    fn lookalike_hostnames_are_still_valid_servers() {
        for good in [
            "https://tauri.localhost.example.com",
            "https://mytauri.localhost.dev",
            "https://ipc.localhost.evil.test",
        ] {
            assert!(validate(good).is_ok(), "{good}");
        }
    }

    #[test]
    fn every_error_has_a_stable_code_and_a_message() {
        let all = [
            OriginError::Empty, OriginError::TooLong, OriginError::Invalid, OriginError::UnsupportedScheme,
            OriginError::CredentialsNotAllowed, OriginError::NotAnOrigin, OriginError::InsecureScheme,
            OriginError::DesktopOrigin,
        ];
        let mut codes: Vec<_> = all.iter().map(|e| e.code()).collect();
        codes.sort_unstable();
        codes.dedup();
        assert_eq!(codes.len(), all.len());
        assert!(all.iter().all(|e| !e.message().is_empty()));
    }

    const BASE: &str = "default-src 'self'; script-src 'self'; connect-src 'self' ipc: http://ipc.localhost; object-src 'none'";

    #[test]
    fn csp_gets_only_the_connect_origin_added() {
        let out = csp_with_connect_origin(BASE, "https://studio.example.com");
        assert!(out.contains("connect-src 'self' ipc: http://ipc.localhost https://studio.example.com"));
        assert!(out.contains("default-src 'self'; script-src 'self'"));
        assert!(out.contains("object-src 'none'"));
        assert!(!out.contains('*'));
    }

    #[test]
    fn csp_injection_is_idempotent_and_creates_connect_src_when_absent() {
        let once = csp_with_connect_origin(BASE, "https://studio.example.com");
        assert_eq!(csp_with_connect_origin(&once, "https://studio.example.com"), once);
        let bare = csp_with_connect_origin("default-src 'self'", "https://s.example.com");
        assert_eq!(bare, "default-src 'self'; connect-src 'self' https://s.example.com");
    }

    fn temp_store(tag: &str) -> SettingsStore {
        let dir = std::env::temp_dir().join(format!("studio-desktop-test-{tag}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        SettingsStore::new(dir)
    }

    #[test]
    fn origin_is_persisted_reloaded_and_cleared() {
        let store = temp_store("roundtrip");
        assert_eq!(store.load(), None);
        store.save(Some("https://studio.example.com")).unwrap();
        assert_eq!(store.load().as_deref(), Some("https://studio.example.com"));
        store.save(None).unwrap();
        assert_eq!(store.load(), None);
        let _ = fs::remove_dir_all(&store.dir);
    }

    #[test]
    fn a_corrupt_or_tampered_file_never_blocks_the_start() {
        let store = temp_store("corrupt");
        fs::create_dir_all(&store.dir).unwrap();
        fs::write(store.file(), "not json").unwrap();
        assert_eq!(store.load(), None);
        fs::write(store.file(), r#"{"server_origin":"http://evil.example.com"}"#).unwrap();
        assert_eq!(store.load(), None, "an invalid persisted origin is ignored");
        let _ = fs::remove_dir_all(&store.dir);
    }

    #[test]
    fn the_settings_file_holds_no_secret_field() {
        let store = temp_store("shape");
        store.save(Some("https://studio.example.com")).unwrap();
        let text = fs::read_to_string(store.file()).unwrap();
        let v: serde_json::Value = serde_json::from_str(&text).unwrap();
        assert_eq!(v.as_object().unwrap().keys().collect::<Vec<_>>(), vec!["server_origin"]);
        let _ = fs::remove_dir_all(&store.dir);
    }
}
