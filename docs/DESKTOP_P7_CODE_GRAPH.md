# DESKTOP P7 — Code Graph & Graphify Provider (`desktop/code-graph`)

Base : `origin/desktop/integration` `b49ae5dfd3c32eb7efeb2f3563e526504ca2b911`.
Contrats P1 (`studio.local/v1`) utilisés tels quels : **aucune modification de
contrat** (pas de `contract-guardian`).

## Contenu

| Chemin | Rôle |
|---|---|
| `packages/studio-code-graph/` | Provider, service d'index, adaptateur Graphify isolé, fixtures P8 |
| `tests/code_graph/` | Tests pytest (233 passés, 4 ignorés dans l'environnement de validation) |
| `packages/studio-client/src/studio_client/watchers/git_watcher.py` (+ `daemon/`) | Crochet additif `on_change` du GitWatcher existant |

## Architecture

```
GitWatcher (P4/P5, unique) ──on_change──▶ CodeGraphService ──▶ CodeGraphProvider (Protocol)
                                              │                        ▲
                                     IndexStore (cache local)          │
                                                                GraphifyProvider
                                                          (seul code qui connaît Graphify)
```

- `provider.py` : `CodeGraphProvider` (Protocol), `ProviderProbe`/`ProbeState`,
  `BuildRequest`, `RepoGraph`, `CodeGraphBuildError`. Tout est déjà exprimé dans
  le schéma commun P1 ; rien de propre à un moteur ne franchit la frontière.
- `service.py` : `CodeGraphService` ne dépend que du Protocol. Il applique le
  `CodeGraphConfig` P5, calcule les états, sérialise les builds par dépôt, gère
  l'invalidation et répond à `status` / `search_symbols` / `graph_page` depuis
  l'index en cache (aucun appel au moteur par requête ; une vérification Git de
  fraîcheur au plus toutes les 5 s, sonde du provider au plus toutes les 60 s).
- `graphify/` : `locator.py` (détection, jamais d'installation), `runner.py`
  (sous-processus), `translate.py` (`graph.json` → schéma commun),
  `adapter.py` (`GraphifyProvider`). Un test d'AST (`test_boundary.py`) impose
  que `graphify` n'apparaisse que dans ce sous-paquet, qu'aucun module réseau ni
  shell ne soit importé, et que seuls `runner.py`, `locator.py` et `gitstate.py`
  lancent des processus.
- `gitstate.py` : identité par contenu d'un dépôt (chemin → blob Git), digest,
  résumé ajouté/modifié/supprimé/renommé.
- `store.py` : instantané par dépôt, écriture atomique, confinement sous la
  racine du cache, lecture corrompue signalée (`StoreCorruptError`).
- `fixtures.py` : jeux de graphes pour P8 (voir plus bas).

Remplaçabilité : un second provider n'a qu'à satisfaire le Protocol
(`probe`, `build`, `capabilities`, `language_by_extension`) ; le service accepte
une liste de providers et `test_service.py` valide le remplacement.

## États

`disabled`, `not_installed`, `unavailable`, `incompatible`, `indexing`, `ready`,
`stale`, `error` (contrat `CodeGraphStatus`).

| Situation | État |
|---|---|
| `features.code_graph` faux | `disabled`, aucun index, aucun sous-processus |
| exécutable Graphify absent | `not_installed` |
| version hors `[0.9.0, 1.0.0)` | `incompatible` |
| exécutable présent mais sonde en échec | `unavailable` |
| build en cours | `indexing` (progression) |
| index à jour | `ready` |
| code différent de l'index (commit, changement de branche) | `stale`, puis reconstruction |
| dépôt manquant ou déplacé | `unavailable` (`workspace_inaccessible`), rien n'est supprimé ; reconfiguré vers le nouveau chemin, il est réindexé |
| timeout, processus en échec, sortie manquante/corrompue | `error` borné, sans chemin local |

Dissocier un dépôt n'efface jamais le dépôt. Son cache d'index n'est purgé que
par `forget(purge_cache=True)` ; retirer un dépôt de la config le laisse en
mémoire et sur disque comme cache orphelin (aucun nettoyage automatique).
Un arbre sale n'invalide que le statut (`stale`), pas de rebuild sur simple sondage.

## Capacités réelles (Graphify 0.9.59)

Exposées : fichiers, classes/types, fonctions/méthodes, `contains`, `imports`,
`calls` (statique, marqué `INFERRED` avec preuve), `inherits`.

Non exposées (aucune relation inventée) : `references`, `defines` distinct de
`contains`, appels dynamiques, résolution de symboles externes (comptés dans
`dropped`, jamais fabriqués), relations sémantiques. Les chemins non sûrs
(hors dépôt) sont écartés et comptés.

Chaque nœud/arête porte `source=code`, une provenance (`source_id`, extracteur,
confiance ; preuve pour `INFERRED`), une URI locale et un identifiant stable.
Le graphe Code n'écrit aucune relation vers le Knowledge Graph (rôle des
projections P8).

## Incrémental vs reconstruction

Commande figée : `graphify update . --no-cluster --force`, sortie redirigée hors
du dépôt (le dépôt utilisateur n'est jamais modifié : `git status` propre).

- **Réellement incrémental** : le cache AST de Graphify est réutilisé
  (`index.cache_assisted`). Seul ce niveau est incrémental.
- **Reconstruction** : l'assemblage du graphe est complet à chaque exécution.
- **Décision du service** : un événement Git déclenche un contrôle du digest de
  contenu ; s'il est identique (commit doc seul, branche au code identique,
  `touch`), aucun build. Sinon, un build debounced (le plus petit build sûr).
  Suppression et renommage suppriment les anciens nœuds ; un renommage est
  détecté par identité de blob.

Mesures réelles (Windows, Graphify 0.9.59, `STUDIO_CODE_GRAPH_PERF=1`) :

| Taille | Fichiers | Nœuds | Initial | Après commit | Requête | Pic Python |
|---|---|---|---|---|---|---|
| petit | 10 | 40 | 2,0 s | 1,6 s | 1 ms | 1 Mo |
| moyen | 200 | 800 | 7,4 s | 5,9 s | 7 ms | 8 Mo |
| grand | 2000 | 8000 | 50,2 s | 42,2 s | 14 ms | 74 Mo |

Le pic mesure le processus Python (tracemalloc), pas le sous-processus Graphify.
Le build s'exécute en tâche de fond avec timeout : ni le daemon ni l'UI ne sont
bloqués.

## Intégration GitWatcher

Aucun second watcher. `GitWatcher` reçoit un `on_change` optionnel (dataclass
`GitChange`) appelé après la transaction outbox ; une exception du listener est
journalisée et n'interrompt jamais le watcher ni le flux d'événements.
`WorkspaceWatchSet(change_listener=...)` et `DaemonRuntime(git_change_listener=...)`
propagent le même crochet. Le service consomme un `GitChangeLike(repo_path)`
structurel et n'importe pas `studio_client`.

## Graphe développeur vs provider produit

Le graphe central de développement (`scripts/graphify-studio.ps1`,
`GRAPHIFY_OUT` externe) est inchangé et sans lien avec le provider produit.
Le provider ne connaît aucun chemin de machine (`E:\Graphify` interdit par test) :
l'exécutable vient d'un chemin explicite, de `STUDIO_CODE_GRAPH_GRAPHIFY_EXE`
(réglé par l'opérateur du daemon) ou du `PATH`. Rien n'est téléchargé ni installé
automatiquement ; l'installation reste une action explicite, gérée séparément.

## Fixtures P8

`build_fixture(nom)` / `all_fixtures()` : `empty`, `small`, `files`, `functions`,
`imports`, `calls`, `contains`, `partial`, `stale`, `indexing`,
`provider_absent`, `error`, `corrupt`. Statut et graphe passent par le schéma
commun ; P8 ne dépend pas de Graphify.

## Sécurité

- Aucun envoi serveur ; aucun module réseau dans le paquet (test AST).
- Arguments Graphify construits côté service (argv figé, pas de shell,
  environnement filtré, timeout, arrêt de l'arbre de processus).
- Confinement : `paths.py` refuse traversal, chemins absolus et échappements ;
  symlinks et sous-modules ne sont pas suivis ; les erreurs surfacées ne
  contiennent aucun chemin local.
- Sortie Graphify plafonnée (256 Mo) et validée avant traduction.

## Audit de licences (factuel)

| Élément | Constat |
|---|---|
| `graphifyy` 0.9.59 (import `graphify`) | `License-Expression: Apache-2.0` dans les métadonnées ; le paquet livre aussi `LICENSE-MIT` et `NOTICE`, dont la portée exacte n'est pas auditée |
| Dépendances de base déclarées | `networkx`, `numpy`, `rapidfuzz`, `tree-sitter` et ~25 grammaires `tree-sitter-*` ; extras optionnels non utilisés par P7 |
| Dépendances de `studio-code-graph` | uniquement `studio-contracts` ; Graphify n'est ni dépendance Python ni vendored |

Licences des dépendances transitives, fichiers NOTICE et marques **non auditées
ici** : la redistribution n'est **pas validée**. Le choix de packaging
(installation séparée recommandée par P0) reste une décision P10.

## Limites connues

- La commande de pont `code_graph` (exposition renderer) n'est pas câblée : P9 /
  intégration.
- Les suites `tests/client` exigent PostgreSQL, indisponible ici ; seuls les
  tests watcher/runtime/workspace ont été exécutés en isolation (48 passés,
  `--noconftest` et config inexistante). Erreur mypy préexistante de
  `studio-client` (`context/library.py`), hors périmètre.
- Langages : ceux que Graphify sait extraire ; les autres fichiers sont ignorés.
