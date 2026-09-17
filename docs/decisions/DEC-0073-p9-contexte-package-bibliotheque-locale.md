---
id: DEC-0073
title: 'P9 Integration Context Package locale : AI Library comme source du composeur DEC-0057 via StudioApiClient'
status: active
date: '2026-09-17'
superseded_by: null
source: docs/DECISIONS.md
---

# DEC-0073 — P9 Intégration Context Package locale : AI Library comme source du composeur DEC-0057 via StudioApiClient

Ferme le gate P9 (« Bibliothèque intégrée au composeur local DEC-0057 ») :
la Library distant devient une source supplémentaire du composeur local
existant — pas un second pipeline, pas un composeur VPS/MCP, pas un second
backend Bloc B, pas une persistance serveur du package/manifeste.

## 1. Réutilisation 8.2 / frontières

- Le composeur reste `packages/studio-client/src/studio_client/context/`
  (composition + manifeste + budget + priorité + `omitted[]` inchangés dans
  leur rôle) ; la Library s'y insère comme **une source de plus** à côté de
  `task/project_state/claims/decisions/ai_work/events` (partagées),
  `memory/graph` (providers 8.2) et `git`.
- Nouveau `LibraryContextProvider` (`context/library.py`) : même forme que
  les providers 8.2 (lit, normalise, ne décide jamais du package final).
  Il ne duplique aucune logique métier : shadowing et visibilité restent
  côté serveur, la sélection client n'applique que l'ordre total public
  DEC-0065 sur des lignes déjà visibles.
- Accès distant exclusivement via `StudioApiClient` étendu de 4 méthodes
  GET alignées P7/DEC-0071 (`list_library_resources`,
  `get_library_resource`, `list_library_versions`, `list_library_locks`) —
  aucun second client HTTP, aucun `httpx` dispersé, aucun appel MCP
  (`studio_discover_definitions` reste réservé aux agents/harnesses, P8
  inchangé : aucun `studio_compose_context`, aucun output MCP package).
- P7 inchangé (aucune route `/context-package`, aucun budget serveur) ;
  P8 inchangé ; aucun contrat partagé modifié → pas de `contract-change`,
  pas de guardian (intégration interne au client local).
- Aucune migration, aucune table `context_packages`/`context_manifests`,
  aucune logique `compose_*`/`apply_context_budget`/`build_context_manifest`
  dans `services/api` ni `services/mcp`, aucun backend Bloc B nouveau.
- CLI `studio context generate` : `--with-library` (opt-in, défaut off
  comme `memory/graph/git`) + `--library-limit`.

## 2. Kinds : P0 appliqué

- Taxonomie Library fermée P1 (`rule/skill/agent_definition/model_profile/
  workflow`, `LibraryKind`) conservée telle quelle ; elle voyage dans chaque
  item comme `library_kind`, jamais fusionnée.
- Kind Context : un seul kind additif `library` (DEC-0057 §6 autorise
  l'ajout, jamais le renommage). Chaque entrée `sources[]` porte
  `ref = "library:{project_id}"` (identifiants logiques sûrs uniquement).
- Mapping (`LIBRARY KIND | CONTEXT KIND | COMPORTEMENT`) :
  `rule → library | texte `RuleContent.text` injecté` ;
  `skill → library | texte `SkillContent.text` injecté` ;
  `agent_definition → library | ignoré `out_of_scope` (structurel, la
  résolution P5 n'est jamais déclenchée par P9 — composer ne requiert
  aucune AgentDefinition)` ;
  `model_profile → library | ignoré `out_of_scope` (exigences de
  capacités, pas de prose injectable)` ;
  `workflow → library | ignoré `out_of_scope` (forme libre, P11)`.
- Ressource sans version utilisable (`active_version <= 0` et sans lock) ou
  version introuvable → `missing`. Contenu violant son schéma P3/DEC-0066 →
  `ContextError(invalid_library_content)` propagée (jamais avalée, §6).

## 3. schema_version : P0 appliqué

- Manifeste : `schema_version: 1` entier (DEC-0057 §6), inchangé, au même
  endroit ; test anti-confusion dédié.
- `content_schema` Library (`studio.library.rule/v1`, …) est un contrat de
  contenu versionné distinct : il voyage dans chaque item et ne remplace
  jamais `schema_version`. Aucun bump (ajout additif pur).

## 4. Priorité et déterminisme : P0 appliqué

- Ordre de retrait DEC-0057 conservé, `library` inséré entre `decisions`
  et `ai_work` (contenu partagé curé : survit aux sources locales
  volatiles, jamais au socle) : `task/project_state/claims/decisions >
  library > ai_work > events > memory > graph > git` — déterministe,
  trié `(priorité, nom)`, indépendant de l'ordre HTTP/DB.
- Shadowing client : une définition effective par `(kind, stable_key)`,
  rang `user > project(project_id) > studio` (miroir de l'ordre public
  DEC-0065, appliqué aux lignes visibles retournées par le listing P7 qui
  ne résout pas le shadowing lui-même) ; lignes `project` d'un autre
  projet exclues, scope inconnu fail-closed, candidats écartés tus
  (provenance minimale DEC-0065 §7). Items triés `(kind, stable_key)`.
- Version effective : lock projet (`version_origin: "lock"`) sinon
  `active_version` (`"active"`, DEC-0065 §4) ; `deprecated` conservé avec
  `deprecated: true` (la résolution l'aurait résolu ainsi).
- Aucune re-résolution de bindings P2/P5 côté client : les `DependencyPin`
  ne sont pas suivis (pas de second moteur de résolution dans
  `studio-client`). Pas de déduplication inter-providers nouvelle (le
  composeur 8.2 n'en a pas ; P9 n'en ajoute pas).

## 5. Budget 256 Kio : exact

- `256 * 1024` octets, mesuré en octets UTF-8 de la sérialisation finale
  exacte (`{"manifest": …, "data": …}`, mêmes réglages `json.dumps` que
  `ContextPackage.size_bytes()`), jamais `len(str)`, jamais des tokens.
- Correctif 8.2 inclus : l'estimation héritée (manifeste + payloads,
  sans l'enveloppe) sous-comptait de quelques octets ; `_apply_budget`
  mesure désormais le document final à chaque itération — package à la
  limite exacte accepté, tout octet au-delà retire une source
  (`truncated: true`, `omitted(budget)`). Comportement 8.2 existant
  préservé (ordre, socle non retirable auto, flag si le socle dépasse).
- Le VPS ignore le budget (aucun `max_bytes` serveur) ; le composeur local
  l'applique. Tests frontière + UTF-8 non-ASCII dédiés (dont le couplage
  `limits.budget_bytes` chiffres/largeur documenté dans le test).

## 6. omitted[] et lecture dégradée

- `omitted[]` reste `{kind, count, reason}` — jamais de chemin privé par
  construction (aucun champ chemin) ; vérifié Linux + Windows par tests
  (racines vault privées absentes du package sérialisé).
- `TransportError` (refus de connexion, timeout, sans réponse HTTP) →
  `omitted(library, server_unreachable)`, package local-only valide.
  Toute autre erreur (`401/403/404/422`, `5xx` mappée, contenu invalide)
  **propage** : le mode dégradé ne masque ni l'auth ni un contrat violé
  (pas de `except Exception: continue`).
- Pas d'outbox de lecture : la composition dégradée n'écrit rien
  (test `outbox unchanged` sur les trois tables `pending_*`) ; pas de
  cache persistant implicite créé.
- Isolation de panne : `memory/graph OK + Library unreachable → package +
  omitted(library/server_unreachable)`, sources locales intactes.

## 7. Sécurité

- Provenance sûre : `kind/stable_key/version/version_origin/scope` ;
  `SourceRef.ref = "library:{project_id}"`. Aucun chemin local, nom de
  fichier, token/auth header, diagnostic réseau ou métadonnée runtime
  dans package/manifeste/omitted.

## 8. Frontière P10

- P10 (adapteurs d'exécution) hors périmètre : P9 ne résout aucun agent
  (`POST /resolutions` jamais appelé), ne choisit aucun runtime, ne
  touche ni bindings stockés ni registry. Les `model_profile`/`workflows`
  ignorés ici restent disponibles pour P10 via les surfaces P7/P8.
