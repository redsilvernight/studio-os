---
id: DEC-0186
title: 'MCP : déprécier les outils redondants de session et de claim, retrait après
  la fenêtre de transition'
status: accepted
date: '2026-10-04'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0186 — MCP : déprécier les outils redondants de session et de claim, retrait après la fenêtre de transition

## Contexte

Trois paires d'outils se chevauchent : `studio_start_session` / `studio_end_session`
contre `studio_start_work` / `studio_handoff` (DEC-0159, DEC-0163) ;
`studio_claim_task` / `studio_release_task` contre les mêmes composites, qui
réclament et libèrent déjà la tâche ; `studio_claim_resource` contre
`studio_claim_resources` (DEC-0135), qui accepte une liste d'un seul chemin et le
même `idempotency_key`. Le profil `session` (DEC-0183) ne publie déjà que les
composites ; les outils redondants ne subsistent que sur le profil `admin`,
dans l'allowlist des identifiants de lancement et dans les skills.

## Décision proposée

Surface conservée : `studio_start_work`, `studio_handoff`,
`studio_claim_resources`, `studio_release_resource`, `studio_update_task`.

Dépréciés, sans changement de comportement :

| Outil | Remplaçant |
|---|---|
| `studio_start_session` | `studio_start_work` |
| `studio_end_session` | `studio_handoff` |
| `studio_claim_task` | `studio_start_work` |
| `studio_release_task` | `studio_handoff` |
| `studio_claim_resource` | `studio_claim_resources` (un chemin) |

Marquage (changement **additif**, TECH/07 « Évolution des contrats d'outils ») :
description préfixée `DEPRECATED, removal on or after 2026-11-04: use <remplaçant>
instead.` et objet `deprecation` (`replaced_by`, `sunset`) ajouté aux réponses
réussies ; les erreurs restent inchangées. Fenêtre de transition : jusqu'au
`2026-11-04`.

Retrait (changement **cassant**, tâche distincte, skill `contract-change`) après
cette date : suppression des cinq outils de `server.py`, `access_registry.py`,
`LAUNCH_MCP_ALLOWLIST` et de la section « Outils de base » de TECH/07, après
migration des tests qui les appellent directement. Les routes HTTP
(`POST /sessions`, `PATCH /sessions/{id}/end`, `POST /tasks/{id}/claim`,
`POST /tasks/{id}/release`, `POST /claims`) ne sont pas concernées.

## Conséquences

- Aucun consommateur existant ne casse avant le retrait ; il voit le remplaçant
  dans `tools/list` et dans chaque réponse.
- Seul cas non couvert par un composite : la libération, par un rôle privilégié,
  d'un claim de tâche laissé par une autre machine sans session reprise ; elle
  reste possible par `POST /tasks/{id}/release`.
- Les skills et règles du dépôt ne référencent plus les outils dépréciés ; les
  skills de la bibliothèque serveur (`studio-session`, `studio-handoff`, publiés
  hors dépôt) restent à republier.
