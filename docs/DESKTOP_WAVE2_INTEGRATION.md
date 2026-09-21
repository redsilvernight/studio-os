# DESKTOP WAVE 2 — Knowledge × Code Graph × Visualizers (`desktop/integration-wave2`)

Baseline : `origin/desktop/integration` `b49ae5dfd3c32eb7efeb2f3563e526504ca2b911`.

Lanes intégrées, chacune un commit au-dessus de la même baseline :

| Lane | Branche | Commit |
|---|---|---|
| P6 Knowledge | `desktop/knowledge` | `448ff9f` |
| P7 Code Graph | `desktop/code-graph` | `8130d75` |
| P8 Visualizers | `desktop/visualizers` | `cf997ca` |

Aucun fichier n'est modifié par deux lanes : l'intégration est un empilement
`P6 → P7 → P8` sans conflit. Wave 2 ajoute la **réconciliation** : câblage réel
des providers derrière le bridge local, tests d'intégration, contrats générés.

## Architecture Knowledge

```
Workspace (P5) ── KnowledgeConfig ──▶ VaultKnowledgeProvider (P6)
                                            │
                              KnowledgeIndex (SQLite dérivé, reconstructible)
                                            │
                                     Knowledge Graph (P1)
                                            │
                              adaptateur GraphDataSource (P8)
                                            │
                                   Knowledge Graph Viewer (P8)
```

- **Le Markdown est la source de vérité.** L'index SQLite est dérivé et
  jetable : `KnowledgeService.detach()` le supprime, jamais un fichier `.md`.
- Le provider lit et recherche les fichiers localement ; l'édition reste
  externe (Obsidian est optionnel, jamais requis).
- Le daemon sert `knowledge.status|search|get_document|graph_page|graph_expand|reindex`.

## Architecture Code Graph

```
Workspace Git (P5) ── CodeGraphConfig ──▶ CodeGraphService (P7)
                                              │
                                    CodeGraphProvider (Protocol)
                                              │
                                    GraphifyProvider (adaptateur isolé)
                                              │
                                       Common Graph (P1)
                                              │
                                    adaptateur GraphDataSource (P8)
                                              │
                                      Code Graph Viewer (P8)
```

- `CodeGraphService` ne connaît que le `Protocol` ; le seul code qui connaît
  Graphify est `studio_code_graph.graphify` (locator/runner/translate/adapter).
- L'index est en cache local ; une requête ne relance **jamais** Graphify.
- Invalidation par digest de contenu Git (`gitstate.py`), rebuild débouncé.
- Le daemon sert `code_graph.status|find_symbols|graph_page|graph_expand|reindex`.

## Rôle de Graphify

Graphify est un **binaire externe**, localisé au runtime (variable
`STUDIO_CODE_GRAPH_GRAPHIFY_EXE`, sinon `PATH`), version de référence `0.9.59`
(plage supportée `0.9.x`). Jamais téléchargé, jamais installé, jamais bundlé,
jamais copié sur le VPS. `studio-code-graph` ne dépend pas de `graphifyy` : le
paquet ne dépend que de `studio-contracts`. Graphify reste remplaçable par un
autre `CodeGraphProvider`.

## Rôle des visualizers (P8)

Le Dashboard ne lit **jamais** directement le Vault, ne parse pas de Markdown,
ne connaît ni Obsidian, ni SQLite, ni Graphify, ni ses caches. Il consomme
uniquement la frontière locale : `platform.request(command, payload)` →
bridge Tauri → sidecar daemon. En navigateur normal (`mode === "web"`),
`platform.request` refuse sans jamais toucher au système de fichiers, et les
pages graphes affichent que la fonctionnalité est disponible dans Studi'OS
Desktop.

## Knowledge Graph / Code Graph / Project Graph

| | Source | Nature |
|---|---|---|
| **Knowledge Graph** | Markdown du vault (local) | Source de vérité locale |
| **Code Graph** | Arbre de travail Git (local) | Source de vérité locale |
| **Project Graph** | Projection des deux précédents | **Projection**, jamais une source |

**Project Graph = projection.** Ce n'est pas une troisième base, pas un nouvel
index, pas une source de vérité. Il n'expose que des relations inter-sources
**explicites et vérifiables** (`kind === "projection"`, exactement deux
`member_sources`, relation `documents` portant une `evidence`). Aucune relation
heuristique (nom identique, proximité, similarité, inférence) n'est créée.
En l'absence de référence explicite, deux sous-graphes non reliés sont le
résultat correct.

## Données locales vs serveur

Les deux sources sont **locales**. Aucune intégration Wave 2 n'upload
automatiquement : ni Markdown, ni graphe Knowledge, ni graphe Code, ni contenu
source, ni chemin local, ni cache Graphify. Le serveur distant ne devient pas
propriétaire de ces données. Les seuls fichiers créés sont les index dérivés,
sous le cache du daemon. Le bridge ne fait que répondre à des requêtes de
lecture ; la politique local/shared P1 est respectée.

## États possibles

| Provider | États préservés jusqu'à l'UI |
|---|---|
| Knowledge | `disabled`, `ready`, `indexing`, `stale`, `unavailable`, `permission_denied`, `error` |
| Code Graph | `disabled`, `not_installed`, `incompatible`, `unavailable`, `indexing`, `ready`, `stale`, `error` |

Un état précis n'est jamais aplati en `error` : le daemon renvoie un
`LocalError` structuré (`feature_disabled`, `provider_not_installed`,
`index_corrupt`, `workspace_config_missing`, …) que P8 affiche tel quel. Un
état non applicable à un provider n'est pas fabriqué.

## Limites

- Le Project Graph ne produit aucune relation tant qu'aucune référence
  explicite n'existe : c'est volontaire, pas un manque.
- L'indexation initiale du vault est faite par le watcher (première passe
  immédiate) ; une vue ouverte pendant cette passe affiche `indexing`.
- Le code graph est limité aux langages du provider (`LANGUAGE_BY_EXTENSION`) ;
  les autres sont comptés dans `dropped`, jamais inventés.
- `cargo fmt`/`cargo clippy` non exécutés dans l'environnement de validation
  (composants non installés).

## Dette packaging Graphify (P10)

La décision packaging/licence de Graphify **reste P10**. Audit actuel :
metadata `Apache-2.0`, `LICENSE-MIT` également livré, `NOTICE` livré, licences
transitives non complètement auditées, redistribution **non validée**. Wave 2
préserve explicitement cette dette : rien n'est bundlé, aucune dépendance
Python directe à `graphifyy` n'est introduite, aucune redistribution n'est
décidée.

## Décisions

Aucune décision architecturale nouvelle : Wave 2 exécute `DEC-0091` (shell
Tauri mince autour du Dashboard autonome, pont local typé), `DEC-0092`
(`CodeGraphProvider`, Graphify séparé, redistribution différée) et `DEC-0093`
(contrats locaux `studio.local/v1`, bridge à allowlist fermée, fixtures
partagées). Les commandes `knowledge.*`/`code_graph.*` étaient déjà déclarées
par les contrats P1 ; Wave 2 les rend **servies** par le daemon, sans modifier
le contrat. Le changement de `contracts/local/` est purement additif (fixtures
+ entrées de manifest) : `schema_version`, protocole et allowlist inchangés,
aucun bump requis (`contract-guardian` CONFORME).

`LOCAL_CONTRACT_DIGEST` (Dashboard) est un marqueur de dérive, pas un gate de
compatibilité : il est calculé sur `manifest.json + allowlist.json + schémas`,
donc toute fixture additive le fait bouger. Il ne doit pas devenir un gate
d'égalité côté Bloc B — la compatibilité se négocie par protocol range et
capabilities (`DEC-0093`), jamais par version de paquet.
