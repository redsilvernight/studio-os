//! WebView2 browser arguments for the main window.
//!
//! wry always hands WebView2 its own `AdditionalBrowserArguments`; recent
//! WebView2 runtimes (seen with 152 on the GitHub Windows runner) then ignore
//! `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS`, so the local debug port the
//! install and E2E tests open through that variable never listens. The shell
//! forwards only that switch — nothing else from the variable — and otherwise
//! keeps wry's defaults untouched.
//!
//! The port is honoured only when the variable is set for this launch (as the
//! install and E2E scripts do). A value stored as a persistent user or machine
//! variable is refused: a forgotten `setx` must not leave every launch of the
//! installed app drivable over CDP.

/// The variable WebView2 documents for extra browser arguments.
pub const ENV: &str = "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS";

/// What wry passes when no arguments are set (autoplay is on by default).
pub const WRY_DEFAULT_ARGS: &str =
    "--disable-features=msWebOOUI,msPdfOOUI,msSmartScreenProtection --autoplay-policy=no-user-gesture-required";

const DEBUG_PORT_SWITCH: &str = "--remote-debugging-port=";

/// The remote-debugging port requested in `value`, if any (never port 0).
pub fn debug_port(value: Option<&str>) -> Option<u16> {
    value?
        .split_whitespace()
        .find_map(|arg| arg.strip_prefix(DEBUG_PORT_SWITCH)?.parse::<u16>().ok())
        .filter(|&port| port != 0)
}

/// Arguments to set on the webview, or `None` to keep wry's defaults.
/// `persisted` is the value stored as a persistent variable, if any.
pub fn browser_args(value: Option<&str>, persisted: Option<&str>) -> Option<String> {
    if debug_port(persisted).is_some() {
        return None;
    }
    debug_port(value).map(|port| format!("{WRY_DEFAULT_ARGS} {DEBUG_PORT_SWITCH}{port}"))
}

/// The variable as stored for the user or the machine (Windows registry),
/// independently of this process's environment.
#[cfg(windows)]
pub fn persisted_value() -> Option<String> {
    use winreg::enums::{HKEY_CURRENT_USER, HKEY_LOCAL_MACHINE};
    use winreg::RegKey;
    [
        (HKEY_CURRENT_USER, "Environment"),
        (
            HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
        ),
    ]
    .into_iter()
    .filter_map(|(root, path)| RegKey::predef(root).open_subkey(path).ok())
    .filter_map(|key| key.get_value::<String, _>(ENV).ok())
    .find(|value| debug_port(Some(value)).is_some())
}

#[cfg(not(windows))]
pub fn persisted_value() -> Option<String> {
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn without_a_debug_port_wry_defaults_are_kept() {
        assert_eq!(browser_args(None, None), None);
        assert_eq!(browser_args(Some(""), None), None);
        assert_eq!(browser_args(Some("--lang=fr"), None), None);
    }

    #[test]
    fn only_the_debug_port_is_forwarded_on_top_of_wry_defaults() {
        assert_eq!(
            browser_args(
                Some("--lang=fr --remote-debugging-port=9444 --no-sandbox"),
                None
            ),
            Some(format!("{WRY_DEFAULT_ARGS} --remote-debugging-port=9444"))
        );
    }

    #[test]
    fn a_debug_port_stored_as_a_persistent_variable_is_refused() {
        let persisted = Some("--remote-debugging-port=9444");
        assert_eq!(browser_args(persisted, persisted), None);
        // Even when this launch asks for another port.
        assert_eq!(
            browser_args(Some("--remote-debugging-port=9555"), persisted),
            None
        );
        // A persistent value without a debug port does not block a launch-scoped one.
        assert_eq!(
            browser_args(Some("--remote-debugging-port=9555"), Some("--lang=fr")),
            Some(format!("{WRY_DEFAULT_ARGS} --remote-debugging-port=9555"))
        );
    }

    #[test]
    fn a_malformed_or_zero_port_is_ignored() {
        for value in [
            "--remote-debugging-port=",
            "--remote-debugging-port=0",
            "--remote-debugging-port=70000",
            "--remote-debugging-port=12ab",
            "--remote-debugging-address=0.0.0.0",
        ] {
            assert_eq!(debug_port(Some(value)), None, "{value}");
        }
    }
}
