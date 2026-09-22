---
id: DEC-0095
title: 'Desktop P10 : installateur NSIS par utilisateur, sidecar onedir, Graphify détecté et non redistribué'
status: proposed
date: '2026-09-22'
superseded_by: null
---

# DEC-0095 — Desktop P10: packaging, data separation and Graphify distribution

Status: **proposed** (awaiting human validation)
Date: 2026-09-22
Task: `[Desktop P10] Windows packaging, installation, update & security`

## Context

P0–P8 produce a Tauri 2 shell, a Python daemon and a shared Dashboard that run
from a developer checkout. P10 must ship them as a Windows application that
needs no Python, Node, Rust, Git or pip on the user's machine. DEC-0092 left
open whether Graphify may be bundled, pending a distribution audit.

## Decision

1. **One canonical installer: NSIS, per-user** (`installMode: currentUser`, no
   administrator, installs under `%LOCALAPPDATA%`). It is the only format the
   pinned Tauri 2.11 toolchain builds and verifies here without extra tooling.
   MSI/WiX is not produced.
2. **The daemon is frozen with PyInstaller `--onedir`** and installed read-only
   in `<install dir>\sidecar\`. `--onefile` is rejected: it extracts to `%TEMP%`
   at every start, which is slower, antivirus-suspicious and leaves debris.
   `sidecar-manifest.json` records daemon/desktop version and the bridge
   protocol; the shell refuses a protocol mismatch.
3. **Binaries and user data are separate.** Nothing mutable lives in the install
   directory. Daemon data stays in `%APPDATA%\StudioOS` (with a `format.json`
   marker and stepwise, backed-up migrations that fail closed on an unknown or
   newer format), shell settings in `%APPDATA%\dev.studio-os.desktop`,
   credentials in Windows Credential Manager. Uninstall keeps all of it unless
   the user ticks the explicit full-clean option; a Vault is never moved or
   deleted automatically.
4. **Graphify is not redistributed (strategy C/D).** It remains a separately
   installed component that Studi'OS only detects and version-checks
   (`>=0.9.0,<1.0.0`). Absent → `not_installed`; out of range → `incompatible`.
   The Desktop starts and works without it.
5. **Git is not bundled.** It is detected; absence degrades to `git_absent`.
6. **Updates use `tauri-plugin-updater` (minisign)**, compiled in only when a
   public key and endpoint are configured, user-initiated, fail-closed. The
   updater signature is distinct from Windows Authenticode signing. The
   development installer is unsigned; no SmartScreen reputation is claimed and
   no key or certificate is committed.
7. **Executables are resolved only from absolute, non-working-directory PATH
   entries** (Graphify, Git) to prevent PATH hijacking.

## Graphify audit (facts, 2026-09-22)

- Installed distribution `graphifyy` 0.9.59, Python ≥3.10, about 175 MB and
  6,806 files, i.e. more than twice the whole current sidecar (70 MB).
- Its own licence and NOTICE are Apache-2.0 with retained MIT text; redistribution
  of the core looks permitted.
- Not proven: the complete transitive licence set and notices of its dependency
  tree, trademark use, and an update path that keeps the bundled copy inside the
  supported range. The repository ships no `LICENSE` of its own yet.
- Per the fail-closed rule, integrated redistribution is therefore not enabled.
  A later decision may supersede this once that review is done.

## Consequences

- Installer ≈ 40 MB, installed ≈ 80 MB; Graphify would add ≈ 175 MB.
- Users who want Code Graph install Graphify themselves; the Dashboard shows the
  provider state and the way to install it.
- A per-machine (Program Files) install is out of scope.
- The NSIS pre-install/uninstall hook stops any running `studio-daemon.exe`
  of the user, including a development daemon; this is documented.

## Evidence

`docs/DESKTOP_P10_PACKAGING.md`, `desktop/scripts/build.mjs`,
`desktop/scripts/build-sidecar.mjs`, `desktop/scripts/install-test.mjs`,
`desktop/src-tauri/installer/hooks.nsh`,
`packages/studio-client/src/studio_client/data_format.py`,
`packages/studio-client/src/studio_client/knowledge/locator.py`.
