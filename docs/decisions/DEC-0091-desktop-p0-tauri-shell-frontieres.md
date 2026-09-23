---
id: DEC-0091
title: 'Desktop P0 : Tauri 2 comme shell mince, frontières Desktop/bridge/daemon/serveur'
status: active
date: '2026-09-20'
superseded_by: null
source: docs/DECISIONS.md
sync_hash: sha256:f25aa8dcb1fd375a1d4e224bbfa0a8e3c1e813af2f638ec84eddca82c3aa4ca7
---

# DEC-0091 — Desktop P0: Tauri 2 shell and architectural boundaries

Status: **accepted** (human validation 2026-09-20)
Date: 2026-09-20
Task: `[Desktop P0] Architecture Gate & audit`
Server decision UUID: `642acc21-4335-409f-b44b-f1c558aea7de`

## Context

Studi'OS has a standalone Vite Dashboard, a Python local client/daemon, and a
canonical FastAPI/MCP server. It has no Desktop shell or local Desktop bridge.
The product needs Windows installation, native lifecycle, filesystem dialogs,
tray, secure storage and updates without creating a second business backend.

## Decision

Use Tauri 2 as the primary Desktop shell, subject to a bounded P2 technical
gate. Reuse the same Dashboard code in web and Desktop modes. Expose native and
local capabilities through a narrow, typed, allowlisted bridge. Run the existing
Python daemon/local services as the managed sidecar rather than rewriting them
in Rust or TypeScript.

Ownership is fixed as follows:

- Desktop: window, tray, native dialogs, updater, secure storage integration,
  process lifecycle and native security policy.
- Local Bridge: validation and adaptation only; no server business rules.
- Daemon/local services: outbox/replay, heartbeat, watchers, transfers,
  Knowledge/Code Graph and other long-running local functions.
- Server: all canonical shared state, authorization and business transitions.
- Dashboard: common business UI, independently deployable on the web.

Human JWT and daemon machine credentials stay distinct. The local protocol is
versioned independently from Desktop, daemon, API and event schema versions.
Electron is the fallback only if the P2 gate disproves Tauri's suitability.

## Consequences

- P1 must freeze the local handshake, bridge, daemon lifecycle, workspace,
  identity, capability and error contracts before implementation.
- P2 must prove Dashboard embedding, IPC, sidecar lifecycle, REST/SSE, keyring,
  Windows build and signing before later lanes begin.
- No native API is imported directly into reusable Dashboard business modules.
- The MCP local stdio server remains a read-only agent interface, not the
  Desktop control bridge.
- The decision adds no server endpoint, event, schema or database object.

## Evidence

See `docs/DESKTOP_P0_ARCHITECTURE_GATE.md`. Primary implementation evidence:
`dashboard/`, `packages/studio-client/src/studio_client/daemon/heartbeat.py`,
`packages/studio-client/src/studio_client/outbox/`, and
`services/mcp/src/studio_mcp/local_server.py`.

## Numbering note

The Studio OS server allocated readable ID `DEC-0090`, which collides with the
already versioned file `DEC-0090-roadmaps-p10-validation-finale-et-cloture.md`.
Per current project policy, versioned files are authoritative; this ADR uses the
next free repository ID, `DEC-0091`, and records the immutable server UUID.
