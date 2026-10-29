# Collecte locale de la consommation (sessions desktop)

Statut : implémenté côté client (daemon), à livrer avec la prochaine version desktop.
Code : `packages/studio-client/src/studio_client/usage/local/`, boucle
`packages/studio-client/src/studio_client/daemon/usage_scan.py`.

## Problème

Le ledger d'usage n'était alimenté que par les lancements Mission Control
(`LaunchUsageRecorder`). Une session exécutée depuis l'application desktop d'un
agent (Claude Code, Codex, OpenCode) ne passait par aucun lancement : ses tâches
affichaient « Aucune mesure de consommation », sans qu'aucune donnée n'existe.

## Principe

Le daemon lit, **en lecture seule**, les stockages natifs de chaque harnais sur le
poste qui les a exécutés, puis enfile des entrées `usage.create` / `usage.correct`
par la file outbox existante — le serveur et le dashboard n'ont pas changé.

| Harnais | Source lue | Jetons | Coût |
|---|---|---|---|
| Claude Code | `~/.claude/projects/*/*.jsonl` (`usage` par message assistant) | mesurés | estimé (grille EUR) |
| Codex | `~/.codex/sessions/AAAA/MM/JJ/*.jsonl` (`token_usage_record`) | mesurés | estimé (grille EUR) |
| OpenCode | `~/.local/share/opencode/opencode.db` (`message` assistant) | mesurés | estimé (grille EUR) |

Aucun contenu de conversation ni identifiant d'authentification n'est copié : seuls
compteurs, horodatages, modèle et répertoire de travail de la session sont lus.

## Rattachement à la tâche (agnostique)

La session est rattachée à la tâche qu'elle a elle-même déclarée : le premier
appel `studio_start_work` (ou l'ancien `studio_claim_task`) que l'agent a enregistré
dans son propre transcript, quel que soit l'outil. Les lecteurs reconnaissent les
trois formes réelles :

- Claude Code : bloc `tool_use` `mcp__studio-os__studio_start_work` (arguments JSON) ;
- Codex : `custom_tool_call`/`exec` dont le code contient l'appel (littéral à clés
  non quotées) ;
- OpenCode : `part` de type `tool` nommée `studio-os_studio_start_work`.

Sans appel Studio, la session est rattachée au **projet** du workspace qui contient
son répertoire de travail (préfixe le plus long) et apparaît « Sans tâche ». Hors
workspace enregistré, rien n'est envoyé (compté `unattributed`).

## Comptage et coût

- Une entrée par `(session, tâche ou projet, modèle, jour UTC)`. Les compteurs
  Claude/OpenCode sont ramenés à la convention disjointe du contrat
  (`tokens_in` hors cache, `tokens_cached` = lectures de cache, `tokens_out` =
  sortie + réflexion) ; Codex fournit un `input_tokens` inclusif, le lecteur
  soustrait les sous-ensembles cache avant de compter.
- Le coût est une **estimation EUR** (couverture `estimated`, jamais présentée comme
  un montant exact) calculée sur une grille datée (`public-eur-2026-10`) :
  entrée / sortie / cache lu / cache écrit, prix au million de jetons. Un modèle
  inconnu de la grille reste « inconnu » — aucun prix par défaut n'est inventé.
- Grille surchargeable sans code : `<data_root>/pricing.json`
  (`{"price_list_id": "...", "effective_from": "...", "models": {"préfixe": {
  "input": 0, "output": 0, "cache_read": 0, "cache_write": 0}}}`) — un préfixe
  personnalisé l'emporte sur la grille fournie.
- Un bucket qui grossit pendant une session encore ouverte est renvoyé comme
  **correction** du fait déjà enregistré (`expected_version`), jamais comme seconde
  entrée. Les clés d'idempotence sont stables : un rejeu ne duplique rien.

## Limites assumées

- Session = fichier de transcript (Claude, Codex) ou base OpenCode ; la lecture est
  incrémentale (offset par fichier, 8 Mio max par scan et par fichier, 4 fichiers en
  parallèle) et bornée aux stockages modifiés dans la fenêtre de rétro-lecture.
- Un champ absent reste `unknown` ; zéro mesuré et absence de mesure ne sont jamais
  confondus. Une session sans jeton (annulée) n'émet rien.
- Les formats des trois outils sont internes : certifiés par version (Claude Code
  2.1.x, Codex 0.16x, OpenCode 1.18.x). Un format inconnu dégrade la session, il ne
  casse ni le daemon ni le rejeu.
- Aucune reprise de l'historique antérieur à la première exécution n'est garantie :
  la fenêtre `usage_scan_lookback_days` (défaut 7) s'applique au premier scan.
- Une session desktop ne déclare pas de session Studio OS : `session_id` et
  `task_launch_id` restent `null`, seul `task_id` est renseigné.

## Configuration (daemon)

| Réglage | Défaut | Rôle |
|---|---|---|
| `usage_scan_enabled` | `true` | désactive toute la collecte locale |
| `usage_scan_interval_seconds` | `120` | période de scan |
| `usage_scan_lookback_days` | `7` | fenêtre de rétro-lecture au premier scan |

Variables `STUDIO_CLIENT_USAGE_SCAN_*` ou fichier TOML du client, comme les autres
réglages. Le premier scan démarre après un court délai (15 s max) pour ne pas
retarder le démarrage du daemon.

## Vérifier

1. Laisser tourner le daemon quelques minutes, puis ouvrir une fiche tâche exécutée
   manuellement : la section « Consommation » doit afficher durée, coût estimé et
   jetons, avec la source `studio-local-claude-code` (ou `-codex`, `-opencode`).
2. Outbox du poste : `pending_mutations.kind = 'usage.create'` puis `usage.correct`
   rejoués vers `POST /api/v1/usage`.
3. Vue projet → Consommation : les sessions sans tâche apparaissent en « Sans
   tâche » ; un modèle non tarifé affiche un coût « inconnu ».
