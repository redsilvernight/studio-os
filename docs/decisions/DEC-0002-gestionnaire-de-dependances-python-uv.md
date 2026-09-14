---
id: DEC-0002
title: 'Gestionnaire de dependances Python : `uv`'
status: active
date: '2026-09-12'
superseded_by: null
source: docs/DECISIONS.md
sync_hash: sha256:0ba4bdeef3f83d9bb7f3c4505713e78bcaad0416cf44e045f23bf3def77998e4
graphify_entities:
- kind: package
  node_id: pkg_studio_os
  path: pyproject.toml
  project: studio-os
  relation: concerns
  symbol: studio-os
---

# DEC-0002 — Gestionnaire de dependances Python : `uv`

Non tranche par la documentation. `uv` retenu : workspace multi-packages,
lockfile, rapide en build Docker.
