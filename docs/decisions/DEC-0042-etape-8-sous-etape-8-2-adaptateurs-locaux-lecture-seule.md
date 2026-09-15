---
id: DEC-0042
title: 'Etape 8 (roadmap), sous-etape 8.2 : adaptateurs locaux Obsidian/Graphify en lecture seule, portee fermee par defaut'
status: active
date: '2026-09-15'
superseded_by: null
source: docs/DECISIONS.md
---

# DEC-0042 — Etape 8, sous-etape 8.2 : adaptateurs locaux en lecture seule

Sous-etape 8.2 de `docs/ROADMAP_STEP8_BREAKDOWN.md` (etape 8, "Connaissance IA
et experience de collaboration"). Bloc B uniquement, aucun octet ne quitte le
poste, aucun contrat versionne touche (ni API, ni Event, ni Auth/Sync, ni Data
Model, ni MCP) — pas de `contract-guardian` requis. `studio-architect` non
requis (aucune frontiere Bloc A/Bloc B).

### Probleme

`TECH/09` declare deux interfaces — `MemoryProvider` et `GraphProvider` — dont
aucune ligne de code n'existait. C'est la cause explicite du report des 4
outils MCP manquants (`TECH/07`, DEC-0023). Deux invariants rendent la naivete
dangereuse : "aucune memoire privee n'est synchronisee" et "Qwen reste en
lecture seule sur la memoire partagee par defaut". Par ailleurs `TECH/09`
postule trois niveaux `private|project|studio` alors que le vault reel est
structure en `global/`, `conventions/`, `templates/`, `projects/<nom>/` (plus
des dossiers hors memoire : `ai/`, `tools/`, `environment/`, `gdscript/`...) —
la correspondance n'existait nulle part (question ouverte n°7 du decoupage).

### Decision

1. **Nouveau sous-paquet `studio_client.knowledge`** (`memory.py`, `graph.py`,
   `scope.py`, `errors.py`), dependances locales uniquement : `pyyaml` pour le
   frontmatter, jamais `studio_api`, jamais de dependance reseau.
2. **`MemoryProvider` en lecture seule pour cette sous-etape** : `search` et
   `read` implementes dans `VaultMemoryProvider`. Les methodes d'ecriture
   (`propose`, `write_if_authorized`, `append_task_log`,
   `create_decision_note`) sont declarees dans le `Protocol` mais levent
   `KnowledgeError("write_unsupported")` — leur boucle d'approbation traverse
   le serveur et releve de 8.4/8.5. Le `Protocol` fige ainsi des le premier
   jour les noms de `TECH/09`, sans livrer d'ecriture partielle sans
   approbation.
3. **Portee fermee par defaut** (`ScopePolicy`, meme philosophie que
   `scripts/graphify_update_policy.py` pour l'extraction semantique) :
   `ClientConfig.knowledge_scope_allow` (prefixe `STUDIO_CLIENT_`) declare les
   prefixes relatifs exposables ; defaut `()` = refus total. Tout chemin hors
   portee est refuse quel que soit le chemin demande (`../`, absolu, lien
   symbolique fuyant resolu puis recontrole) — jamais lu, jamais indexe,
   jamais renvoye. Correspondance actee ici :
   - niveau `project` de `TECH/09` ↔ `projects/<slug>/` ;
   - niveau `studio` de `TECH/09` ↔ `global/`, `conventions/` ;
   - `templates/` = echafaudage, jamais expose sauf mention explicite ;
   - niveau `private` de `TECH/09` ↔ tout ce qui n'est pas liste (pas un
     dossier reel : la confidentialite par defaut, pas un marquage) ;
   - tout autre dossier du vault (`ai/`, `tools/`, ...) ↔ jamais expose sauf
     mention explicite.
4. **Chemins configurables, jamais codes en dur** : `ClientConfig`
   (`knowledge_vault_path`, `knowledge_graph_dir`, `knowledge_source_root`
   optionnelle). Vault absent = `search` vide avec `reason="vault_missing"`,
   `read` en `KnowledgeError("vault_missing")` — degrade explicite, jamais
   d'exception non typee ni de plantage du daemon.
5. **`GraphProvider` en lecture seule** : `GraphifyGraphProvider` lit
   directement les artefacts JSON (`graph.json` format node-link,
   `manifest.json`, `decisions_subgraph.json` en complement) — aucun
   sous-processus PowerShell dans le chemin de lecture (le lanceur canonique
   `scripts/graphify-studio.ps1` reste l'outil de la conversation principale,
   pas d'un appel d'agent). `refresh_graph` leve
   `KnowledgeError("refresh_unsupported")` et ne lance rien : la mise a jour
   du graphe est une operation de fin de tache pilotee par la conversation
   principale.
6. **Fracheur via le manifest, jamais via les seuls mtime** : le
   `manifest.json` central est un registre de couverture
   (`{chemin: {mtime, ...}}`). Un fichier demande absent du manifest =
   reponse marquee `stale` (`"not_covered"`), jamais servie comme fraiche.
   Si `knowledge_source_root` est renseignee, un ecart entre le mtime disque
   et le mtime enregistre au manifest = `stale` (`"changed_since_indexed"`)
   ; sans racine source, seule la couverture est verifiable. Un graphe ou un
   manifest absent/invalide = reponse `stale` (`"graph_missing"`,
   `"manifest_missing"`, `"graph_invalid"`), jamais une reponse
   silencieusement incomplete.
7. **Reponses compactes et bornees** (`max_results`/`limit`, extraits
   tronques avec `truncated: true`) : ces providers alimenteront un outil
   MCP en 8.3.
8. **Question ouverte n°1 du decoupage (ou s'execute le Context Package)
   explicitement non tranchee ici** : ce lot ne fournit que les briques
   locales ; le tranchant ADR interviendra avant 8.3.

### Consequences

- Aucun changement de contrat : `TECH/07` garde son ecart 25/29 documente
  jusqu'en 8.3 ; `TECH/02/03/04/05` inchanges.
- `packages/studio-client/pyproject.toml` gagne `pyyaml>=6.0` (frontmatter).
- Qwen et tout agent non privilegie ne voient que `search`/`read` sur la
  portee declaree — l'invariant "lecture seule par defaut" tient par
  construction (aucune ecriture n'existe dans ce sous-paquet).
- Limite assumee : `search` est une concordance de sous-chaine insensible a
  la casse, pas une recherche semantique ; suffisant pour fermer le critere
  "chercher et lire sans serveur", a reevaluer si 8.3 exige un classement.

### Preuves

Suite complete locale : **411 passed, 2 skipped** (374 passed avant ce lot,
cf. DEC-0041). 37 nouveaux tests : 19 dans
`tests/client/test_knowledge_memory.py` (recherche bornee, invisibilite
hors-portee en `search` comme en `read` exact, refus `../`/absolu, vault
absent/fichier/vide, frontmatter invalide ignore en recherche et bruyant en
lecture, notes sans frontmatter, bornes `max_results`/extraits/`read`,
portee vide par defaut, 4 ecritures refusees `write_unsupported` sans toucher
au vault, octets non-UTF-8 ignores), 14 dans
`tests/client/test_knowledge_graph.py` (requete bornee, fichiers pertinents,
dependances 1 saut, fraicheur `not_covered`/`changed_since_indexed`,
graphe/manifest absent/invalide en `stale` explicite, `refresh_graph`
`refresh_unsupported`, symboles lies par fichier et par label) et 4 dans
`tests/client/test_knowledge_config.py` (defauts deny-all, init, env JSON,
TOML). 2 tests symlink skippes sur Windows (creation de lien non permise —
le refus de fuite est couvert par les tests `../`/absolu). `ruff check`,
`ruff format --check` verts (279 fichiers). `mypy` strict :
`Success: no issues found in 102 source files` (97 avant ce lot). Aucun
contrat touche : `TECH/02/03/04/05/07` inchanges, pas de `contract-guardian`
requis. Revue `studio-tester`/`contract-guardian` non rejouable dans cette
session (agents projet non disponibles) — validation autonome ci-dessus.

Fichiers ajoutes : `packages/studio-client/src/studio_client/knowledge/`
(`__init__.py`, `errors.py`, `scope.py`, `memory.py`, `graph.py`),
`tests/client/test_knowledge_{memory,graph,config}.py`,
`docs/decisions/DEC-0042-*.md`.
Fichiers modifies : `packages/studio-client/src/studio_client/{__init__.py,
config.py}`, `packages/studio-client/pyproject.toml` (`pyyaml>=6.0`),
`tests/client/conftest.py` (isolation des nouvelles variables
`STUDIO_CLIENT_KNOWLEDGE_*`), `docs/ROADMAP_STEP8_BREAKDOWN.md`,
`docs/Studio_OS_Documentation_Pack/studio_os_docs/TECH/09_OBSIDIAN_GRAPHIFY.md`
(pointeur d'implementation).
