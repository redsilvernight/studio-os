---
id: DEC-0092
title: 'Desktop P0 : CodeGraphProvider neutre, Graphify optionnel installé séparément'
status: active
date: '2026-09-20'
superseded_by: null
source: docs/DECISIONS.md
sync_hash: sha256:012df5bcc15450ce7fdecbc3074cfe90a6eca51633c478ad58f96f7f9d9ec2b2
---

# DEC-0092 — Desktop P0: CodeGraphProvider boundary and Graphify distribution

Status: **accepted** (human validation 2026-09-20)
Date: 2026-09-20
Task: `[Desktop P0] Architecture Gate & audit`
Server decision UUID: `98e41032-4197-4213-b1eb-3980b43ba2b6`

## Context

Studio OS currently reads Graphify's local `graph.json` and `manifest.json`
through `GraphifyGraphProvider`. Graphify itself is installed externally as the
`graphifyy` uv tool and invoked by a project launcher. The Desktop roadmap must
not assume that this third-party runtime can or should be redistributed.

The verified local installation is Graphify `0.9.59`, Python `>=3.10`, roughly
175.5 MB and 6,806 files. Its installed distribution includes Apache-2.0,
`NOTICE`, and retained MIT licence text. Core redistribution appears permitted,
but an embedded product still requires a complete transitive licence, notices,
trademark, packaging and updater review.

## Decision

P1 defines a provider-neutral `CodeGraphProvider`; no Desktop or Dashboard code
depends directly on Graphify formats or commands. Graphify is the first optional
adapter and, for the initial Desktop architecture, remains a **managed separate
installation** detected and version-checked by Studi'OS.

The feature is explicitly optional. Absence, incompatibility, indexing, stale
data and errors are visible states. No repository content or graph is uploaded
without an explicit publish contract and user action.

Embedding Graphify as a sidecar or vendored package remains open for a later
decision after the full distribution audit and a reproducible Windows packaging
prototype. P0 does not authorize bundling it.

## Consequences

- Existing `GraphifyGraphProvider` can back the new interface after adaptation.
- Graphify updates remain independent initially; compatibility ranges and an
  explicit repair/install flow are required.
- Markdown/Vault and Code Graph remain separate providers and canonical sources.
- P7 can replace Graphify in the future without changing Dashboard or bridge
  contracts.
- P1 fixtures must cover provider absent, disabled, incompatible, indexing,
  ready, stale, permission denied, corrupt index and error states.

## Evidence

See `docs/DESKTOP_P0_ARCHITECTURE_GATE.md`,
`packages/studio-client/src/studio_client/knowledge/graph.py`,
`packages/studio-client/src/studio_client/context/composer.py`, and
`scripts/graphify-studio.ps1`.

## Numbering note

The Studio OS server allocated readable ID `DEC-0091` to this proposal while
the preceding server proposal collided with repository `DEC-0090`. Versioned
files remain authoritative, so this ADR uses repository ID `DEC-0092` and keeps
the immutable server UUID above for reconciliation.
