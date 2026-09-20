//! The closed `studio.local/v1` command allowlist.
//!
//! Single source of truth: the P1 export `contracts/local/allowlist.json`,
//! embedded at compile time. Nothing here restates a command name by hand, so
//! the Desktop cannot drift from the contract (a P1 change that renames or
//! adds a command changes this table and the tests below).

use serde::Deserialize;
use std::collections::HashMap;
use std::sync::OnceLock;

const ALLOWLIST_JSON: &str = include_str!("../../../contracts/local/allowlist.json");

pub const PROTOCOL: &str = "studio.local/v1";

/// Commands the P2 sidecar spike answers. Every other allowlisted command is a
/// valid P1 command that is deliberately not served yet (`not_supported`);
/// the daemon that serves them is P4, the UI that calls them is P3+.
pub const SERVED_IN_P2: &[&str] = &["runtime.handshake", "daemon.status", "identity.get_view"];

#[derive(Debug, Clone, Deserialize)]
pub struct CommandSpec {
    pub command: String,
    pub mutating: bool,
    pub max_request_bytes: usize,
}

#[derive(Debug, Deserialize)]
struct Allowlist {
    protocol: String,
    commands: Vec<CommandSpec>,
}

fn table() -> &'static HashMap<String, CommandSpec> {
    static TABLE: OnceLock<HashMap<String, CommandSpec>> = OnceLock::new();
    TABLE.get_or_init(|| {
        let parsed: Allowlist =
            serde_json::from_str(ALLOWLIST_JSON).expect("contracts/local/allowlist.json is valid");
        assert_eq!(parsed.protocol, PROTOCOL, "allowlist protocol drifted");
        parsed
            .commands
            .into_iter()
            .map(|c| (c.command.clone(), c))
            .collect()
    })
}

pub fn lookup(command: &str) -> Option<&'static CommandSpec> {
    table().get(command)
}

pub fn all_commands() -> Vec<&'static str> {
    let mut names: Vec<&str> = table().keys().map(String::as_str).collect();
    names.sort_unstable();
    names
}

pub fn is_served_in_p2(command: &str) -> bool {
    SERVED_IN_P2.contains(&command)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn allowlist_matches_p1_export() {
        assert_eq!(all_commands().len(), 28, "P1 exports 28 commands");
        assert!(lookup("runtime.handshake").is_some());
        assert!(lookup("daemon.status").is_some());
    }

    #[test]
    fn unknown_and_dangerous_commands_are_not_allowlisted() {
        for name in [
            "execute_shell",
            "spawn_process",
            "read_file",
            "write_file",
            "proxy_http",
            "execute",
            "run_command",
            "daemon.exec",
            "",
            "RUNTIME.HANDSHAKE",
            "runtime.handshake ",
        ] {
            assert!(lookup(name).is_none(), "{name:?} must not be allowlisted");
        }
    }

    #[test]
    fn served_commands_are_a_subset_of_the_allowlist() {
        for name in SERVED_IN_P2 {
            assert!(lookup(name).is_some(), "{name} not in P1 allowlist");
            assert!(!lookup(name).unwrap().mutating, "P2 serves read-only commands only");
        }
    }

    #[test]
    fn no_allowlisted_name_carries_a_forbidden_primitive_term() {
        // Mirrors studio_contracts.local.bridge.FORBIDDEN_PRIMITIVE_TERMS.
        let terms = [
            "exec", "shell", "spawn", "process", "filesystem", "fs.", "http", "proxy", "eval",
            "raw", "stdin", "command_line",
        ];
        for name in all_commands() {
            assert!(
                !terms.iter().any(|t| name.contains(t)),
                "{name} contains a forbidden primitive term"
            );
        }
    }
}
