---
id: DEC-0158
title: 'AIB-I : ensure agent serveur par stable_key, distinct d''AgentDefinition'
status: superseded
date: '2026-09-28'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0158 — AIB-I : ensure agent serveur par stable_key, distinct d'AgentDefinition

AIB-I : l'identité agent porte une clé stable locale via `POST /agents/ensure` (find-or-create serveur sur `(machine_id, stable_key)`, contrainte unique, mismatch → 409 `idempotency_key_payload_mismatch` réutilisé). `AgentCreate`/`Agent` gagnent `stable_key` optionnel ; `POST /agents` reste création pure (collision → 409 `duplicate_stable_key`). `AgentDefinition.stable_key` reste un paramètre de résolution, jamais une identité. Fichier : branche task/project-ai-bootstrap/L1-5376f5a0-agent-identity (migration 0019, service ensure_agent, route /ensure, client + CLI + MCP pass-through, docs 02/05).
