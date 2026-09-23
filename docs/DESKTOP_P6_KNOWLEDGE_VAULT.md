# DESKTOP P6 — Knowledge Vault & Knowledge Graph (lane `desktop/knowledge`)

Base : `origin/desktop/integration` `b49ae5dfd3c32eb7efeb2f3563e526504ca2b911`
(P0→P5 + Wave 1b validée). Aucun merge/rebase depuis P7/P8.

Contrats P1 (`studio.local/v1`, DEC-0093) utilisés tels quels : **aucune
modification de contrat**. Aucun nouveau type n'est introduit dans
`packages/studio-contracts/src/studio_contracts/local/` ; seules des fixtures
P8 sont ajoutées.

## Contenu

| Chemin | Rôle |
|---|---|
| `packages/studio-client/src/studio_client/knowledge/vault.py` | Structure canonique, init non destructive, états du dossier, fingerprint |
| `.../knowledge/markdown.py` | Parseur Markdown (titres, liens, wikilinks, tags, frontmatter) |
| `.../knowledge/index.py` | Index SQLite dérivé + extraction du graphe |
| `.../knowledge/provider.py` | `VaultKnowledgeProvider` (P1) + adaptateur `MemoryProvider` |
| `.../knowledge/obsidian.py` | Détection optionnelle + ouverture bornée |
| `.../knowledge/service.py` | Câblage `LocalWorkspaceConfig` (P5) + dissociation |
| `.../knowledge/watch.py` | `VaultIndexWatcher` (réutilise `PollingWatcher` P4) |
| `tests/knowledge/` | 92 tests pytest (aucune base, aucun réseau) |
| `tests/mcp/test_local_knowledge_index.py` | 7 tests de l'outillage MCP local indexé |
| `docs/DESKTOP_P6_KNOWLEDGE_VAULT.md` | Ce fichier |

Réutilisation, pas de second système : le parseur de frontmatter/titre reste
`studio_client.knowledge.memory.parse_note` (DEC-0042) ; `ScopePolicy` porte
toujours la portée fermée par défaut ; `GraphifyGraphProvider` (code graph,
P7) n'est ni touché ni dupliqué.

## Structure canonique du Vault

Dossiers ordinaires, fichiers Markdown ordinaires, aucun format propriétaire :

```
<vault_root>/
  projects/<slug>/     mémoire projet      (exposé : project, DEC-0042)
  global/              mémoire studio      (exposé : studio)
  conventions/         conventions studio  (exposé : studio)
  templates/           échafaudage         (jamais exposé par défaut)
  .studio/vault.json   métadonnées Studi'OS (jamais indexé)
  README.md            créé seulement s'il est absent
```

Ne sont jamais indexés : `.studio/`, `.obsidian/`, `.git/`, `.trash/`,
`node_modules/`, `__pycache__/` et tout dossier caché. Un Vault existant
structuré autrement (`ai/`, `tools/`, `environment/`, `gdscript/`…) est
connecté tel quel : ces dossiers ne sont simplement pas indexés par défaut.
Markdown est la source de vérité ; l'index et le graphe sont dérivés.

## Initialisation non destructive

`initialize_vault()` ne crée que ce qui manque et ne remplace jamais rien :
un `README.md` ou un `vault.json` existant est conservé, un chemin canonique
occupé par un fichier utilisateur est laissé intact (listé en `skipped`), et
un dossier Markdown non vide est connecté sans réorganisation.

P12 expose cette primitive par la commande locale additive
`knowledge.init_vault`. La requête contient uniquement le `workspace_id` et
`confirmed: true` : le daemon résout `KnowledgeConfig.content_root` dans le
workspace confirmé, refuse les symlinks/junctions et ne renvoie jamais de chemin
absolu. La capability optionnelle `knowledge.init` reste distincte de
`knowledge.index`; l'indexation est déclenchée séparément par
`knowledge.reindex`.

États explicites (`VaultState`) : `missing`, `not_a_directory`, `inaccessible`
(PermissionError à l'énumération), `empty`, `markdown_existing`,
`studios_vault`. Un chemin déplacé ou inaccessible n'est jamais deviné : le
provider répond `unavailable` avec `workspace_inaccessible` et le motif exact.

## Index dérivé

- Emplacement : cache du daemon, `<cache_dir>/<KnowledgeConfig.index.directory_name>`
  (`IndexLocation.scope = "workspace_cache"`), fichier `knowledge-index.sqlite3`.
- Supprimable et reconstruisible : `drop()` efface le fichier, un
  `full_rebuild` le recrée à l'identique (mêmes identifiants de nœuds/arêtes).
- Incrémental : un document dont le hash et le `mtime_ns` n'ont pas bougé
  n'est pas réécrit ; ajout/modification/suppression sont répercutés, et les
  documents disparus voient leurs lignes et leurs arêtes supprimées.
- États : `absent` (jamais construit), `indexing` (drapeau persistant +
  pourcentage pendant un rebuild), `ready` (fingerprint à jour), `stale`
  (fichiers modifiés depuis), `corrupt` (fichier illisible ou schéma inconnu).
  Un index corrompu est signalé puis réparé par un `full_rebuild`.
- Aucun accès réseau : le module n'importe ni httpx, ni keyring, ni le client
  API (vérifié par test de sous-processus et par blocage de `socket`).

## KnowledgeProvider (P1)

`VaultKnowledgeProvider` implémente la surface P1 : `status`,
`search`, `get_document`, `reindex`, plus `graph_page` / `graph_expand` pour le
schéma de graphe commun. Il n'ajoute aucun champ ni aucune capacité au contrat :

- `KnowledgeStatus` : provider `markdown-files`, `canonical_source =
  markdown_files`, index dérivé/rebuildable, intégrations optionnelles,
  erreur structurée (`feature_disabled`, `index_absent`, `index_corrupt`,
  `workspace_inaccessible`).
- `KnowledgeSearchResult` : `index_state` en `ComponentState`, `complete`
  faux dès que l'index n'est pas `ready`.
- `KnowledgeDocument` : le Markdown est **relu du disque** à chaque appel
  (l'index ne sert jamais de copie canonique), tronqué à `max_bytes`.
- `KnowledgeReindexResult` : `accepted` + `operation_id` + état résultant ;
  un refus porte toujours une erreur.
- Un libellé ou un extrait qui ressemblerait à un secret ou à un chemin absolu
  est neutralisé avant d'atteindre un modèle de contrat.

## Knowledge Graph

Nœuds : `document`, `heading`, `tag` (uniquement les kinds knowledge autorisés
par le schéma commun). Arêtes, chacune avec provenance
(`source_id`, `extractor`, `confidence = extracted`, `evidence`) :

| Relation | Origine démontrée |
|---|---|
| `contains` | document → titre du même document |
| `links_to` | lien Markdown ou wikilink résolu vers un fichier du Vault (ou vers un titre via `#L<ligne>` / `#Titre`) |
| `embeds` | `![[note]]` vers un document du Vault |
| `tagged_with` | document → tag (frontmatter ou inline) |

Aucune relation heuristique : un lien externe, un lien mort, un embed d'image
ou une cible absente ne produisent **aucune** arête (testé). `GraphPage` est
borné (`limit`, `next_cursor`) ; les extrémités hors page vont dans `frontier`,
jamais dans une arête pendante. `graph_expand` fait un seul saut, filtré par
direction et par relations.

## Obsidian (optionnel)

Détection (`detect_obsidian`) : exécutable local ou `PATH` → `ready`, sinon
`not_installed`. `open_vault_in_obsidian` n'utilise qu'une primitive bornée :
une URI `obsidian://open?path=…` remise à l'ouvreur de plateforme. La
configuration d'Obsidian est lue (vaults connus) et **jamais écrite**. Aucune
fonction de lecture, d'indexation ou de recherche ne dépend de sa présence.

## Workspace (P5)

`knowledge_service_from_workspace(config, cache_dir)` consomme
`KnowledgeConfig` : feature `disabled` → aucun service, aucun index, aucun
watcher (testé : le dossier de cache n'est même pas créé). Feature activée →
`vault_root = workspace_root / content_root`. Workspace déplacé → état
explicite. `detach()` ne supprime que l'index dérivé : les fichiers Markdown
restent octet pour octet identiques.

## MCP local / Context

`KnowledgeMemoryProvider` a la forme du `MemoryProvider` existant : les outils
`studio_memory_search` / `studio_memory_read` et le Context Package
l'utilisent sans modification de leur code ni de leurs budgets. La portée
reste fermée par défaut (DEC-0042) : `memory_provider()` n'expose rien sans
préfixes explicites. `create_local_server_from_knowledge` /
`create_local_server_from_workspace` sont additifs dans
`services/mcp/src/studio_mcp/local_server.py` ; `studio_client.knowledge`
reste exempt de httpx/keyring, y compris via le MCP local.

## Privacy

Invariant tenu : Vault local ≠ donnée serveur. Aucun upload, aucune
télémétrie, aucune publication automatique. Le client MCP n'ouvre aucune
connexion ; l'index et la recherche ne touchent que le disque local.

## Fixtures P8

Ajoutées dans `packages/studio-contracts/src/studio_contracts/local/fixtures.py`
et exportées dans `contracts/local/fixtures/valid/` :

`knowledge.status.stale`, `knowledge.status.unavailable`,
`knowledge.status.error`, `graph.knowledge.empty`, `graph.knowledge.links`,
`graph.knowledge.partial`, `graph.knowledge.after_deletion`.
Elles couvrent Vault vide, liens, provenance par extracteur, page partielle
(frontier + curseur) et document supprimé (aucune référence pendante).

## Fichiers partagés susceptibles de confliter avec P7/P8

| Fichier | Nature du chevauchement |
|---|---|
| `packages/studio-contracts/src/studio_contracts/local/fixtures.py` | P7 ajoutera ses fixtures code graph, P8 ses fixtures de rendu ; ajout purement additif ici |
| `contracts/local/` (généré) | Régénéré par l'export : toute autre lane qui régénère doit relire le diff |
| `tests/contracts/test_local_p1.py` | `REQUIRED_FIXTURES` étendu (additif) |
| `services/mcp/src/studio_mcp/local_server.py` | P7 branche son provider code graph ; deux fonctions ajoutées ici, aucune signature modifiée |
| `packages/studio-client/src/studio_client/knowledge/__init__.py`, `errors.py` | Exports et constantes d'erreur additifs ; P7 peut vouloir y exporter `CodeGraphProvider` |
| `packages/studio-client/src/studio_client/knowledge/` (paquet) | P7 travaille dans `graph.py` (Graphify) ; P6 n'y touche pas |

Non touchés volontairement (points de composition à fort conflit) :
`daemon/runtime.py`, `daemon/service.py`, `context/composer.py`, le dashboard.
Le watcher P6 est une sous-classe de `PollingWatcher` prête à être ajoutée au
runtime par l'intégrateur, pas un second système de surveillance.

## Limites assumées

- La recherche est lexicale (jetons, score borné), pas sémantique.
- La pagination est un offset encodé dans un curseur opaque ; le tri est
  déterministe par identifiant de nœud / URI.
- Un nom de fichier impossible à adresser par une URI canonique (caractères
  interdits par P1) est ignoré, jamais renommé.
- Le rebuild est synchrone et borné ; le streaming/background relève du
  watcher du daemon.
- L'index stocke le corps Markdown pour la recherche locale ; il est
  supprimable et n'est jamais synchronisé.
