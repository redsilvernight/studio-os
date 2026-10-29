---
id: DEC-0214
title: 'Rejeu P04 : aperçu en lecture seule + retry P02 confirmé, sans re-épinglage'
status: accepted
date: '2026-10-14'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0214 — Rejeu P04 : aperçu en lecture seule + retry P02 confirmé, sans re-épinglage

Contexte : P04-replay-option. Le retry P02 revalide déjà droits et politique (authorize_create) mais utilise la résolution courante et la branche task/* actuelle ; rien ne montrait l'écart avec le snapshot DEC-0199.

Décision : pas de rejeu « à l'identique ». On ajoute (additif) :
- GET /api/v1/task-launches/{id}/replay-preview -> TaskLaunchReplayPreview : lecture seule, compare le snapshot (harness, ressources Library par (role, stable_key), runtime) à ce que le retry utiliserait aujourd'hui ; verdict ready|limited|refused ; vocabulaire fermé de limitations (refus : launch_not_terminal, already_retried, snapshot_missing, snapshot_capture_failed, not_authorized, target_not_admissible, agent_unresolvable ; limitations : resolution_unrecorded, library_version_unavailable, source_worktree_dirty, source_git_unrecorded, git_state_not_pinned, profile_rechecked_on_machine, output_not_reproducible). preview_digest sha256 sur tout sauf generated_at.
- POST /retry accepte `replay: {snapshot_content_hash, preview_digest}` optionnel : le serveur recalcule l'aperçu ; refus -> 409 replay_refused (codes), digest/hash différent -> 409 replay_preview_stale (digest courant) ; sinon la nouvelle tentative porte replay_basis (source, hash, digest, verdict, substitutions != unchanged, codes). Snapshot source jamais réécrit.
- Migration 0034 : colonne JSONB nullable task_launches.replay_basis.

Hors périmètre : épinglage du git_sha / worktree neuf au snapshot, budget (toujours vérifié à la création), profil recalculé côté daemon seulement.
