//! Deny-by-default navigation policy for the main WebView.
//!
//! The packaged Dashboard is the only content that ever runs with the IPC
//! bridge. Any other top-level destination is either handed to the system
//! browser (plain http/https, never inside the app) or refused. The decision
//! is a pure function of the target URL so it can be tested exhaustively.

use url::Url;

/// Host the packaged Dashboard is served from on Windows (WebView2 custom
/// protocol mapped to `http://tauri.localhost`).
pub const APP_HOST: &str = "tauri.localhost";

#[derive(Debug, PartialEq, Eq, Clone, Copy)]
pub enum Decision {
    /// Stay in the WebView (packaged Dashboard, or the dev server in dev).
    Allow,
    /// Refuse in the WebView and open with the system browser.
    OpenExternally,
    /// Refuse outright.
    Deny,
}

/// `dev_origin` is only `Some` for a dev build (the Vite dev server); a release
/// build passes `None`, so a stray localhost URL is external there.
pub fn decide(target: &Url, dev_origin: Option<&Url>) -> Decision {
    // Credentials in the authority are how `http://tauri.localhost@evil.test`
    // spoofs are built: never internal, never even external.
    if !target.username().is_empty() || target.password().is_some() {
        return Decision::Deny;
    }
    if is_internal(target, dev_origin) {
        return Decision::Allow;
    }
    match target.scheme() {
        "http" | "https" if target.host_str().is_some() => Decision::OpenExternally,
        _ => Decision::Deny,
    }
}

fn is_internal(target: &Url, dev_origin: Option<&Url>) -> bool {
    if target.scheme() == "http" && target.host_str() == Some(APP_HOST) && target.port().is_none()
    {
        return true;
    }
    match dev_origin {
        Some(dev) => {
            target.scheme() == dev.scheme()
                && target.host_str() == dev.host_str()
                && target.port_or_known_default() == dev.port_or_known_default()
        }
        None => false,
    }
}

/// Only http(s) links may leave the app. Anything else is refused.
pub fn external_target(target: &Url) -> Option<&str> {
    match target.scheme() {
        "http" | "https"
            if target.host_str().is_some()
                && target.username().is_empty()
                && target.password().is_none() =>
        {
            Some(target.as_str())
        }
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn u(s: &str) -> Url {
        Url::parse(s).unwrap()
    }

    #[test]
    fn packaged_dashboard_is_internal() {
        for s in [
            "http://tauri.localhost/",
            "http://tauri.localhost/index.html",
            "http://tauri.localhost/#/configuration",
            "http://tauri.localhost/assets/app.js?x=1",
        ] {
            assert_eq!(decide(&u(s), None), Decision::Allow, "{s}");
        }
    }

    #[test]
    fn external_http_and_https_go_to_the_system_browser() {
        for s in [
            "https://example.com/",
            "http://example.com:8080/x",
            "https://tauri.localhost/",
            "http://tauri.localhost:8080/",
            "http://sub.tauri.localhost/",
            "http://tauri.localhost./",
            "http://TAURI.LOCALHOST.:80/",
            "http://localhost:5173/",
            "http://127.0.0.1:8000/api",
        ] {
            assert_eq!(decide(&u(s), None), Decision::OpenExternally, "{s}");
        }
    }

    #[test]
    fn dangerous_schemes_are_refused() {
        for s in [
            "file:///C:/Windows/System32/cmd.exe",
            "javascript:alert(1)",
            "data:text/html,<script>1</script>",
            "blob:http://tauri.localhost/abc",
            "ms-msdt:/id",
            "ms-settings:privacy",
            "vbscript:msgbox(1)",
            "ftp://example.com/",
            "ws://example.com/",
            "tauri://localhost/",
            "ipc://localhost/",
            "about:blank",
            "mailto:a@b.c",
            "steam://run/1",
            "search-ms:query=x",
        ] {
            assert_eq!(decide(&u(s), None), Decision::Deny, "{s}");
        }
    }

    #[test]
    fn credential_spoofing_is_refused() {
        for s in [
            "http://tauri.localhost@evil.test/",
            "http://user:pw@tauri.localhost/",
            "https://a:b@example.com/",
        ] {
            assert_eq!(decide(&u(s), None), Decision::Deny, "{s}");
        }
        // The spoof resolves to the *evil* host, never to the app.
        assert_eq!(u("http://tauri.localhost@evil.test/").host_str(), Some("evil.test"));
    }

    #[test]
    fn dev_origin_is_internal_only_when_provided() {
        let dev = u("http://localhost:5173");
        assert_eq!(decide(&u("http://localhost:5173/x"), Some(&dev)), Decision::Allow);
        assert_eq!(decide(&u("http://localhost:5174/"), Some(&dev)), Decision::OpenExternally);
        assert_eq!(decide(&u("http://localhost:5173/x"), None), Decision::OpenExternally);
    }

    #[test]
    fn only_http_family_may_leave_the_app() {
        assert!(external_target(&u("https://example.com/a")).is_some());
        assert!(external_target(&u("file:///C:/x")).is_none());
        assert!(external_target(&u("javascript:1")).is_none());
        assert!(external_target(&u("https://u:p@example.com/")).is_none());
    }
}
