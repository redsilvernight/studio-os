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
        "capabilities": P2_CAPABILITIES,
        "required_capabilities": P2_CAPABILITIES,
        "optional_capabilities": [],
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
    }

    #[test]
    fn required_capabilities_are_all_declared() {
        let peer = peer_info();
        for req in peer["required_capabilities"].as_array().unwrap() {
            assert!(peer["capabilities"].as_array().unwrap().contains(req));
        }
    }
}
