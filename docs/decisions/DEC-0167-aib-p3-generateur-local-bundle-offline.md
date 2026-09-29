---
id: DEC-0167
title: 'AIB P3 : générateur local du bundle, offline d''abord'
status: proposed
date: '2026-09-29'
superseded_by: null
source: docs/AI_BOOTSTRAP_ROADMAP.md
---

# DEC-0167 — AIB P3 : générateur local du bundle, offline d'abord

Tâche `c691ac49` (étape P3, roadmap `53ca8479`). Statut `proposed` (en attente
d'accord humain explicite — fichier et serveur alignés).

## Contexte

P1 (`studio.bootstrap/v1`, DEC-0143) et P2 (plan serveur en lecture seule,
DEC-0144) sont livrés côté Core. Le plan P2 ne porte qu'un `content_hash`, pas
le contenu des artefacts. DEC-0144 tranche : le client ne réimplémente pas la
résolution ; il lit le manifest, appelle le plan, génère.

## Proposition

Les commandes locales `studio-client bootstrap init|check|diff|sync` (nouveau
groupe `bootstrap`) assemblent le bundle projet **hors ligne**, à partir des
sources canoniques `.agents/` (`build_offline_resolved`), projetées par les
adapters locaux et `materialize` — jamais un second moteur de résolution :

- manifeste minimal `.agents/bootstrap.json` (`studio.bootstrap/v1` : slug,
  harnesses ciblés, politique `on_modified`) ;
- `check` / `diff` produisent un `BootstrapDryRunReport` (contrat P1) ; l'état
  `up_to_date` se compare au contenu généré, fins de ligne CRLF normalisées ;
- `sync` n'écrit que les fichiers non `up_to_date`, sauvegarde tout remplacement
  sous `.studio-os/backups/bootstrap/<ts>/`, refuse un conflit (`refuse`) ou
  exige une confirmation explicite (`ask`), écrit de façon atomique et confinée
  au dépôt ; la seconde exécution n'écrit rien ;
- le plan serveur P2 (`POST /api/v1/bootstrap-plan`) servira d'oracle en ligne en
  incrément **additif** (hors de cette tâche).

## Alternatives rejetées

- Générer directement depuis le plan P2 : impossible sans contenu (hash seul) ;
  le transporter exigerait d'étendre le contrat P1/P2, périmètre plus large que
  P3.
- Agrégation ou résolution côté client : second Resolution Engine, interdit par
  DEC-0144.

## Pourquoi une DEC

Tranche l'interface P2↔P3 (source de contenu = canonique hors ligne ; plan =
oracle) et fixe la surface publique locale (`bootstrap`), contraintes pour les
tâches sœurs P3 : blocs gérés CLAUDE.md/AGENTS.md (`ee3d48da`), diff unifié et
rollback (`5d0a6ac8`), câblage MCP machine-local (`c907a31b`).
