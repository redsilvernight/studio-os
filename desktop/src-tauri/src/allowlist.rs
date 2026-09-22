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

/// Commands implemented by the daemon. Publication operations remain owned by
/// their later lane and are not routed to this process; workspace (P5, served
/// since P11), Knowledge (P6) and Code Graph (P7) are served by the daemon
/// behind the `WorkspaceStore`/`VaultKnowledgeProvider`/`CodeGraphProvider`
/// boundary, and the harness commands (P9) behind the `HarnessAdapter`
/// registry.
pub const SERVED_BY_DAEMON: &[&str] = &[
    "runtime.handshake",
    "daemon.status",
    "daemon.attach",
    "daemon.start",
    "daemon.stop",
    "daemon.restart",
    "daemon.health",
    "identity.get_view",
    "workspace.validate",
    "workspace.get_config",
    "workspace.confirm_roots",
    "workspace.git_status",
    "workspace.save_config",
    "knowledge.status",
    "knowledge.init_vault",
    "knowledge.search",
    "knowledge.get_document",
    "knowledge.graph_page",
    "knowledge.graph_expand",
    "knowledge.reindex",
    "code_graph.status",
    "code_graph.find_symbols",
    "code_graph.graph_page",
    "code_graph.graph_expand",
    "code_graph.reindex",
    "harness.detect",
    "harness.status",
    "harness.preview",
    "harness.apply",
    "harness.rollback",
];

#[derive(Debug, Clone, Deserialize)]
pub struct CommandSpec {
    pub command: String,
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

#[cfg(test)]
pub fn all_commands() -> Vec<&'static str> {
    let mut names: Vec<&str> = table().keys().map(String::as_str).collect();
    names.sort_unstable();
    names
}

pub fn is_served_by_daemon(command: &str) -> bool {
    SERVED_BY_DAEMON.contains(&command) && lookup(command).is_some()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn allowlist_matches_p1_export() {
        assert_eq!(
            all_commands().len(),
            32,
            "studio.local/v1 exports 32 commands"
        );
        assert!(lookup("runtime.handshake").is_some());
        assert!(lookup("daemon.status").is_some());
        assert!(lookup("daemon.health").is_some());
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
        for name in SERVED_BY_DAEMON {
            assert!(lookup(name).is_some(), "{name} not in P1 allowlist");
        }
    }

    #[test]
    fn no_allowlisted_name_carries_a_forbidden_primitive_term() {
        // Mirrors studio_contracts.local.bridge.FORBIDDEN_PRIMITIVE_TERMS.
        let terms = [
            "exec",
            "shell",
            "spawn",
            "process",
            "filesystem",
            "fs.",
            "http",
            "proxy",
            "eval",
            "raw",
            "stdin",
            "command_line",
        ];
        for name in all_commands() {
            assert!(
                !terms.iter().any(|t| name.contains(t)),
                "{name} contains a forbidden primitive term"
            );
        }
    }
}
