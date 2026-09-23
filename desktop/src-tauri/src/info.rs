//! Desktop identity shown in Settings and the Desktop side of the handshake.

use crate::allowlist::PROTOCOL;
use crate::sidecar::SidecarState;
use serde::Serialize;
use serde_json::{json, Value};

pub const PRODUCT: &str = "Studi'OS Desktop";
pub const DESKTOP_VERSION: &str = env!("CARGO_PKG_VERSION");

/// What the Desktop really speaks in P2: daemon status and identity view.
/// More capabilities are declared by the phase that implements them, never
/// ahead of time (negotiation is by capability, not by wishful thinking).
pub const P2_CAPABILITIES: &[&str] = &["daemon.control", "identity.view"];

/// Additive P4 capability (`daemon.health`). Offered but never required, so a
/// P2-only daemon stays compatible (`compatible_degraded`) and the health read
/// is simply absent instead of failing the handshake.
pub const OPTIONAL_CAPABILITIES: &[&str] = &["daemon.health"];

/// Additive Wave 2 capabilities (P6 Knowledge, P7 Code Graph, P9 Harness). Offered but
/// never required: a daemon without local features answers `compatible_degraded`
/// and the graph views simply report the source as unavailable.
pub const LOCAL_FEATURE_CAPABILITIES: &[&str] = &[
    "knowledge.read",
    "knowledge.graph",
    "knowledge.index",
    "knowledge.init",
    "code_graph.read",
    "code_graph.graph",
    "code_graph.index",
    "harness.read",
    "harness.plan",
    "harness.apply",
    "harness.verify",
];

/// Additive P11 capability (workspace configuration, served by the daemon
/// since P11). Offered but never required: an older daemon answers
/// `compatible_degraded` and the setup assistant reports the folder step as
/// unavailable instead of failing the handshake.
pub const WORKSPACE_CAPABILITIES: &[&str] = &["workspace.config"];

fn offered_capabilities() -> Vec<&'static str> {
    P2_CAPABILITIES
        .iter()
        .chain(OPTIONAL_CAPABILITIES.iter())
        .chain(LOCAL_FEATURE_CAPABILITIES.iter())
        .chain(WORKSPACE_CAPABILITIES.iter())
        .copied()
        .collect()
}

fn optional_capabilities() -> Vec<&'static str> {
    OPTIONAL_CAPABILITIES
        .iter()
        .chain(LOCAL_FEATURE_CAPABILITIES.iter())
        .chain(WORKSPACE_CAPABILITIES.iter())
        .copied()
        .collect()
}

#[derive(Debug, Serialize)]
pub struct DesktopInfo {
    pub product: &'static str,
    pub desktop_version: &'static str,
    pub mode: &'static str,
    pub protocol: &'static str,
    /// P1 `PeerInfo` for the Desktop role.
    pub peer: Value,
    pub sidecar: SidecarState,
}

pub fn peer_info() -> Value {
    json!({
        "role": "desktop",
        "protocol_id": "studio.local",
        "protocol": {
            "minimum": { "major": 1, "minor": 0 },
            "maximum": { "major": 1, "minor": 0 }
        },
        "component_version": DESKTOP_VERSION,
        "server_origin": null,
        "capabilities": offered_capabilities(),
        "required_capabilities": P2_CAPABILITIES,
        "optional_capabilities": optional_capabilities(),
        "optional_components": []
    })
}

pub fn desktop_info(sidecar: SidecarState) -> DesktopInfo {
    DesktopInfo {
        product: PRODUCT,
        desktop_version: DESKTOP_VERSION,
        mode: "desktop",
        protocol: PROTOCOL,
        peer: peer_info(),
        sidecar,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn peer_matches_the_p1_handshake_fixture_shape() {
        let fixture: Value = serde_json::from_str(
            &std::fs::read_to_string(concat!(
                env!("CARGO_MANIFEST_DIR"),
                "/../../contracts/local/fixtures/valid/bridge.request.handshake.json"
            ))
            .unwrap(),
        )
        .unwrap();
        let expected = &fixture["data"]["payload"]["peer"];
        let mut a: Vec<_> = peer_info().as_object().unwrap().keys().cloned().collect();
        let mut b: Vec<_> = expected.as_object().unwrap().keys().cloned().collect();
        a.sort();
        b.sort();
        assert_eq!(a, b);
        assert_eq!(peer_info()["protocol"], expected["protocol"]);
        assert_eq!(peer_info()["role"], expected["role"]);
        // Values, not just keys: every capability the Desktop offers must be
        // one the P1 fixture peer knows, or negotiation can never grant it
        // (P11 caught `workspace.config` missing here).
        let offered = peer_info()["capabilities"].as_array().unwrap().clone();
        let known = expected["capabilities"].as_array().unwrap();
        for capability in &offered {
            assert!(
                known.contains(capability),
                "{capability} not in the P1 fixture peer"
            );
        }
        assert!(offered.contains(&json!("harness.verify")));
        assert!(offered.contains(&json!("workspace.config")));
    }

    #[test]
    fn required_capabilities_are_all_declared() {
        let peer = peer_info();
        for req in peer["required_capabilities"].as_array().unwrap() {
            assert!(peer["capabilities"].as_array().unwrap().contains(req));
        }
    }

    #[test]
    fn health_is_optional_and_never_required() {
        let peer = peer_info();
        assert!(peer["capabilities"]
            .as_array()
            .unwrap()
            .contains(&json!("daemon.health")));
        assert!(!peer["required_capabilities"]
            .as_array()
            .unwrap()
            .contains(&json!("daemon.health")));
        assert!(peer["optional_capabilities"]
            .as_array()
            .unwrap()
            .contains(&json!("daemon.health")));
    }

    #[test]
    fn local_feature_capabilities_are_optional_and_never_required() {
        let peer = peer_info();
        for capability in LOCAL_FEATURE_CAPABILITIES {
            assert!(peer["capabilities"]
                .as_array()
                .unwrap()
                .contains(&json!(capability)));
            assert!(!peer["required_capabilities"]
                .as_array()
                .unwrap()
                .contains(&json!(capability)));
            assert!(peer["optional_capabilities"]
                .as_array()
                .unwrap()
                .contains(&json!(capability)));
        }
    }

    #[test]
    fn workspace_config_is_offered_but_never_required() {
        let peer = peer_info();
        for capability in WORKSPACE_CAPABILITIES {
            assert!(peer["capabilities"]
                .as_array()
                .unwrap()
                .contains(&json!(capability)));
            assert!(!peer["required_capabilities"]
                .as_array()
                .unwrap()
                .contains(&json!(capability)));
            assert!(peer["optional_capabilities"]
                .as_array()
                .unwrap()
                .contains(&json!(capability)));
        }
    }
}
