---
id: DEC-0057
title: 'Etape 8 (roadmap), sous-etape 8.3b : Context Package compose localement par le Bloc B, part partagee lue par HTTP canonique, manifeste versionne ephemere'
status: active
date: '2026-09-15'
superseded_by: null
source: docs/DECISIONS.md
---

# DEC-0057 — Sous-étape 8.3b : frontière d'exécution du Context Package

Cette décision rouvre `studio_generate_context_package`, DEFERRED par
UC-3/DEC-0047, et tranche les points laissés ouverts par le découpage de
l'étape 8 (questions n° 1, 2, 5, 6 et 8). Elle ne livre aucun code : elle
fixe la frontière d'exécution, le format du manifeste et la règle de
confidentialité avant implémentation.

## Contexte

`TECH/09` dit « le serveur compose le contexte partagé ; le client complète
avec Git, Graphify, fichiers et mémoire locale », tandis que `TECH/07`
liste `studio_generate_context_package` parmi les outils MCP. Or :

- `TECH/01` : le serveur détient l'état partagé, le client détient le
  contexte local, l'accès au repo, au vault et au graphe ;
- le MCP local du poste est **sans DB, sans token et sans réseau** par
  construction (DEC-0047) et le test
  `tests/mcp/test_local_knowledge.py::test_local_server_imports_without_server_state`
  interdit explicitement `studio_client.api_client`, `studio_client.tokens`
  et `studio_client.transfers` dans ce processus ;
- le graphe et le vault ne doivent jamais être copiés sur le VPS.

Deux lectures naïves sont donc impossibles : mettre le paquet dans le MCP
du VPS (il ne voit pas le local), ou dans le MCP local (il n'a pas le
token). La question n° 1 du découpage reste ouverte pour le seul paquet.

## Décision

1. **Option (c), hybride explicite, composition locale.** Le paquet est
   composé par le **Bloc B** (daemon/CLI), seul composant détenant à la fois
   le token machine et l'accès aux sources locales. Ni le MCP du VPS ni le
   MCP local stdio n'exécutent la composition.

2. **Part partagée = HTTP canonique existant** (DEC-0046). Le composeur lit
   task, ProjectState, claims, decisions, AIWorkLog et événements récents
   via les endpoints déjà exposés, avec `StudioApiClient` et le token
   machine déjà en place. **Aucun nouvel endpoint, aucun nouvel outil MCP
   VPS, aucune table, aucun `EventType`** dans cette sous-étape. Un
   agrégateur `GET /projects/{id}/context` offrant un `as_of` atomique est
   un follow-up optionnel, non requis ici.

3. **Part locale = providers 8.2** (`VaultMemoryProvider`,
   `GraphifyGraphProvider`) sous `ScopePolicy` deny-all (DEC-0042), plus une
   lecture Git bornée. Le composeur appelle **les mêmes méthodes providers**
   que les handlers MCP locaux — jamais les outils MCP eux-mêmes :
   pas de client MCP imbriqué, pas de sous-processus, pas de logique
   dupliquée.

4. **Surface 8.3b : CLI `studio context generate`.** Le CLI Bloc B porte
   déjà le token et suit le modèle `argparse` existant. Le nom
   `studio_generate_context_package` est conservé comme **nom de la
   capacité Bloc B**, mais il **sort de l'inventaire des outils MCP**
   (`TECH/07` amendée) : ce n'est pas un outil MCP du VPS, et il n'est pas
   enregistré sur le MCP local, qui reste sans credential (DEC-0047).

5. **Exposition MCP différée (variante c2).** Si un besoin réel apparaît
   plus tard, la seule forme compatible avec les invariants est : outil VPS
   read-only renvoyant le **fragment partagé** + une enveloppe de
   provenance, et outil local `studio_generate_context_package` recevant ce
   fragment en argument, composant localement **sans réseau et sans
   credential**. Tant qu'aucun consommateur réel ne l'exige, elle n'est pas
   construite ; un seul chemin de composition doit exister à la fois, pour
   ne pas créer deux notions concurrentes de « paquet ».

6. **Format et portée du manifeste.** Le manifeste est un **document
   d'artefact** versionné, pas une réponse d'outil MCP :

   - `schema_version: 1` (entier, comme `EventEnvelope.schema_version`) ;
   - champs obligatoires : `schema_version`, `package_id` (UUID par
     génération), `generated_at`, `project_id`, `task_id` (nullable),
     `generator.machine_id`, `manifest_scope` (`"local"`), `limits`,
     `sources[]`, `omitted[]`, `truncated` ;
   - chaque entrée de `sources[]` : `kind`, `ref`, et selon la source
     `version`, `server_timestamp`, `seq`, `stale`, `stale_reason`,
     `included`, `truncated` ;
   - `kind` fermé pour 8.3b : `task`, `project_state`, `claims`,
     `decisions`, `ai_work`, `events`, `memory`, `graph`, `git` — un
     nouveau `kind` est additif, jamais un renommage ;
   - `omitted[]` : `{kind, count, reason}` — **jamais** de chemin privé,
     seulement un comptage et une raison (`out_of_scope`, `too_large`,
     `missing`, `stale`, `server_unreachable`, `budget`) ;
   - l'ajout de champ est additif ; suppression, renommage ou changement de
     nécessité → `schema_version` incrémentée. Le manifeste n'entre pas
     dans `studio-contracts` tant qu'aucune surface réseau ne l'expose.

7. **Persistance : éphémère par défaut.** Le paquet et son manifeste ne
   sont pas persistés côté serveur : aucune entité, aucune table, aucun
   événement. Écriture locale optionnelle via `--out` uniquement, jamais
   uploadée automatiquement. La traçabilité d'usage reste possible par
   l'AIWorkLog existant, que l'agent écrit explicitement ; l'AIWorkLog ne
   référence que `package_id` et un résumé, jamais le manifeste brut (il
   contiendrait des chemins de notes exposées).

8. **Frontière local → partagé.** Seuls des flux serveur → client
   alimentent la composition. Aucun octet local ne remonte : ni vault, ni
   graphe, ni Git, ni manifeste. Le sens inverse n'existe que par les
   écritures déjà existantes et explicitement déclenchées par l'agent
   (AIWorkLog/Event). La frontière est unidirectionnelle par construction.

9. **Confidentialité, règle par source et bornage.** Le paquet n'est pas un
   dump :
   - mémoire : uniquement la portée exposée (deny-all par défaut) ; une note
     privée n'est jamais lue, jamais listée, jamais hachée ; la mémoire est
     en opt-in (nécessite une requête explicite), pas incluse par défaut ;
   - graphe : uniquement sur un sujet ou un fichier demandé, avec le signal
     de fraîcheur du provider (`stale`, `stale_reason`) préservé ;
   - Git : branche, HEAD, état propre/sale, commits récents bornés — pas de
     diff complet par défaut ;
   - part partagée : fenêtres bornées (`limit`, fenêtre d'événements) ;
   - budget global dur (ex. 256 Kio sérialisés) ; en dépassement, les
     sources sont retirées dans l'ordre de priorité
     `project_state/task/claims/decisions > ai_work > events > memory >
     graph > git`, `truncated: true` et omissions tracées.

10. **Offline.** L'absence de serveur ne produit ni exception ni mise en
    file : le paquet est produit en mode local-only, les sources partagées
    sont marquées `omitted` avec `reason = "server_unreachable"`. Aucune
    écriture dans l'outbox (ce n'est pas une mutation).

## Conséquences

- Aucune modification runtime : `TECH/02/03/04/05` inchangés, aucune
  migration, aucun `auth_role`, aucun `EventType`. `TECH/07` et `TECH/09`
  amendées dans le même lot (le doc est la spec).
- Implémentation à venir (Bloc B uniquement) : `studio_client/context/`
  (composition + manifeste), sous-commande CLI `studio context generate`,
  méthode cliente additive `list_decisions` (absente aujourd'hui,
  `TECH/02` l'expose déjà), éventuel lecteur d'événements borné, tests
  `tests/client/test_context_*.py` sur fixtures `tmp_path` + `MockStudioApiClient`.
- Le MCP local stdio reste sans credential ni réseau : DEC-0047 n'est pas
  rouverte, seulement précisée.
- Tension avec DEC-0048 explicitement levée : la règle « aucun
  `schema_version` dans une réponse MCP » vise l'enveloppe d'outil, pas un
  document d'artefact transporté. Le manifeste porte sa propre version
  d'artefact ; l'enveloppe MCP éventuelle, elle, reste non versionnée.

## Vérification

- Aucune preuve d'exécution dans cette décision : lot de conception pur,
  pas une ligne de code.
- Séquence attendue après création de l'ADR :
  `uv run python -m scripts.adr_index --root . --apply` puis
  `uv run python -m scripts.adr_index --root . --check`.

## Compatibilité avec les DEC existantes

Opérationnalise DEC-0047 (le 4e outil sort du différé, avec sa propre
Décision) ; respecte DEC-0042 (providers/portée inchangés) ; suit DEC-0046
(HTTP canonique, MCP subset) ; précise DEC-0048 (version d'artefact ≠
version d'enveloppe) ; compatible DEC-0005/0026 (pas de duplication de
logique) et TECH/01 (répartition serveur/client).
