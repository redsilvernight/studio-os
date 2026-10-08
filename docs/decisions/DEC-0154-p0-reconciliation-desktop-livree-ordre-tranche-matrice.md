---
id: DEC-0154
title: 'P0 : reconciliation Desktop livree, ordre tranche, matrice validee'
status: accepted
date: '2026-10-08'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0154 — P0 : reconciliation Desktop livree, ordre tranche, matrice validee

Gate P0 (tâche `bb818697`). Clôt les critères « matrice validée » et
« réconciliation Desktop » de l'étape P0. Statut `accepted` (accord humain du
2026-09-27 — fichier et serveur alignés). Vérifié sur `dev` `ab1995a` (roadmap Desktop `d46f7b4a` livrée).

## Réconciliation §8 : les 4 trous sont comblés, on consomme, on ne recrée pas

| Trou §8 | Brique livrée (dev) | Preuve |
|---|---|---|
| Registre projet↔chemin | `LocalWorkspaceConfig` (studio.local/v1, `SecretReference`, sans secret) + package `studio-workspaces` (`registration`, `flows`) | `C/local/workspace.py:92`, `packages/studio-workspaces/` |
| Détection des harnesses | `HarnessRegistry` + `HarnessAdapter` (`claude-code`, `opencode` ; `codex` en P3) | `K/harness/registry.py`, `default_adapters()` |
| Canal local | Bridge allowlisté (`daemon.*`, `identity.enroll`, `workspace.*`, `harness.*`, …) | `desktop/src-tauri/src/allowlist.rs` |
| Écriture sûre | `HarnessService` detect/preview/apply/rollback + backup (DEC-0104) | `K/harness/service.py:1` |

## Ordre tranché (question §11.1)

- P1–P2 (contrat `studio.bootstrap/v1` + plan serveur, AIB-A/B) avancent **seuls,
  côté Core**.
- P3 (commandes locales `init/check/diff/sync`) **consomme** les contrats Desktop
  P5/P9 ci-dessus ; aucune réimplémentation.
- Reste ouvert en P3 : `codex` dans `HarnessRegistry` (tâche `c907a31b`).

## Questions §11 arbitrées ici

- §11.3 : pas de scope session dans la Library ; l'héritage « Studio → projet →
  session » du PDF se lit : ressources Studio/projet, **session = runtime
  uniquement**. Rappel pour P4.
- §11.4 : un preset (Godot…) est un `ProjectInitializationPlan` de départ, pas
  un template (cf AIB-A).
- §11.5 : la syntaxe d'indirection d'environnement MCP **par harness** reste non
  vérifiée → prérequis P3, pas de P0.
- §11.6 : `studio-init-project.ps1` reste **hors dépôt** (script utilisateur),
  référencé par la documentation ; ni absorbé ni appelé par le Core.
- §11.7 : déjà résolu (adr_index en CI).
- §11.8 : références `ROADMAP_CORRECTIONS_AUDIT` disparues de `CLAUDE.md` /
  `AGENTS.md` ; reste le commentaire `dashboard/src/machinesApi.ts:4` (« GET
  /machines n'existe pas ») devenu faux depuis DEC-0082 — suivi : corriger le
  commentaire (tâche dashboard, hors P0).

## Matrice validée (§3, §5)

Classification A/B/C/D/E/F et matrice de réutilisation confirmées par les
preuves ci-dessus. Cases MANQUE résiduelles rattachées : plan agrégé → P2,
commandes locales → P3, publication des skills `studio-*` → P4, statut du poste
et section Dashboard → phases UI/remote.
