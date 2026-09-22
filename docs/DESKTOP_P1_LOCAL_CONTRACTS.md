# Desktop P1 — Contrats locaux `studio.local/v1`

Statut : P1 clos (validation humaine 2026-09-20). Décision associée : `DEC-0093`
(**active**, acceptée). Prérequis : `DEC-0091`, `DEC-0092`
(`docs/DESKTOP_P0_ARCHITECTURE_GATE.md`).

P1 ne contient que des contrats, des fixtures et leurs tests. Aucune
implémentation du shell Tauri, du daemon, du bridge ou des providers (P2+).
Aucun contrat serveur n'est modifié.

## Emplacement

| Élément | Chemin |
| --- | --- |
| Contrats | `packages/studio-contracts/src/studio_contracts/local/` |
| Export JSON (schémas, fixtures, allowlist, manifeste) | `contracts/local/` |
| Tests | `tests/contracts/test_local_p1.py` |
| Régénération | `uv run python -m studio_contracts.local.export` |
| Contrôle de dérive | `uv run python -m studio_contracts.local.export --check` |

Les modèles héritent de `LocalContractModel` (Pydantic v2, `extra=forbid`,
gelés). Le package n'importe ni Tauri, ni Graphify, ni Obsidian, ni SDK d'agent.
Les fichiers de `contracts/local/` sont générés : ne pas les éditer à la main ;
un test échoue si l'export diverge des builders Python.

## Modules

| Module | Rôle |
| --- | --- |
| `common` | Protocole, enums communs, URIs `studio-local://`, gardes anti-secret |
| `handshake` | `LocalRuntimeHandshake` et `negotiate()` |
| `bridge` | Protocole Local Bridge, allowlist fermée |
| `daemon_control` | Statut, cycle de vie, reprise sur crash, outbox |
| `workspace` | `LocalWorkspaceConfig`, santé du workspace |
| `identity` | `HumanIdentity`, `MachineIdentity`, `SecretReference` |
| `provider` | Invariant d'état partagé (`check_provider_state`) |
| `knowledge` | `KnowledgeProvider` |
| `code_graph` | `CodeGraphProvider` |
| `harness` | `HarnessAdapter` |
| `graph` | Schéma de graphe commun |
| `publication` | Politique local/partagé |
| `fixtures`, `export` | Fixtures nommées et export JSON |

## Points de conception

- **Handshake** : négociation par plage de protocole et capabilities, jamais par
  version de paquet. Résultats : `compatible`, `compatible_degraded`,
  `daemon_too_old`, `desktop_too_old`, `capability_missing`,
  `protocol_incompatible`. Échec = fail-closed (`silent_fallback: false`).
- **Bridge** : 29 commandes et 4 événements, table `CommandSpec` par commande
  (capability, mutation, annulation, délai, tailles). Aucune primitive shell,
  filesystem arbitraire, spawn ou proxy HTTP ; `allowlist_violations()` doit
  renvoyer `[]`.
- **Daemon / outbox** : partition d'outbox = sha256(origine, profil, machine) ;
  verrou d'instance = sha256(origine, profil). Rejeu sous une autre identité
  refusé (`IDENTITY_MISMATCH`).
- **Workspace** : aucun secret, uniquement `SecretReference`. Six états de santé.
- **Identités** : `HumanIdentity` et `MachineIdentity` sont deux types ; seules
  les références et leur statut traversent la frontière.
- **Providers** : Knowledge (Markdown canonique, index dérivé, Obsidian
  optionnel), Code Graph (aucun détail Graphify dans les contrats publics ;
  `graphify` n'apparaît que comme valeur d'identifiant d'adaptateur dans les
  fixtures), Harness (aucun concept propre à un éditeur, aucun identifiant
  fournisseur).
- **Graphe commun** : sources `knowledge` / `code` / `projection`, provenance
  obligatoire, relations autorisées par source, frontière pour les graphes
  partiels, arêtes inter-sources uniquement via une projection.
- **Publication** : tout est `LOCAL_ONLY` ; seul `SharedStatusSummary` peut être
  partagé, jamais automatiquement, toujours après confirmation.

## Durcissements issus de la revue

- Le handshake refuse ou dégrade toute capability dont le composant n'est pas
  `ready`/`stale`, qu'elle soit requise, optionnelle ou simplement offerte ;
  rôles et `protocol_id` doivent correspondre, et la majeure négociée doit être 1.
- Chemins : racines de workspace ni racine système/lecteur ni UNC ; globs relatifs
  sans `..` ni `{ } [ ] ~ $ %` (dialecte `*`, `**`, `?` uniquement) ; les
  chemins absolus sont refusés dans les messages et `details` d'erreur ; `RelativePath` refuse `:`, noms de périphériques Windows, segments
  terminés par un point ou une espace, caractères bidi/invisibles ; les cibles de
  harness protégées (`.git`, `.ssh`, `.env*`, …) sont refusées.
- Confirmation de racine au niveau de la transition : `workspace.save_config`
  porte `current_roots` (racines stockées vues par l'appelant, `null` si aucune
  config). Toute différence avec `config.roots` (racine de workspace ou de dépôt,
  première autorisation comprise) est une transition `old -> new` qui échoue sans
  `root_confirmation_id`, émis par le daemon après sélection native confirmée.
  Sans transition, l'identifiant est refusé : une config stable n'en conserve
  jamais, et `LocalWorkspaceConfig` n'a aucun champ de confirmation. Le contrat
  impose la forme ; le daemon (P2+) émet l'identifiant et vérifie que
  `current_roots` correspond à la config stockée.
- `LocalError.message` refuse chemins absolus et secrets ; les identifiants
  opaques refusent les formes de credential ; `SecretKind` ne contient que le
  credential machine.
- Une réponse de corrélation ne peut être ni une requête ni une annulation.

## Versionnage

Modèles stricts (`extra=forbid`) : tout champ ajouté, même optionnel, n'est
émis à un pair qu'après négociation d'une capability dédiée ; retirer, renommer
ou rendre obligatoire un champ exige un nouveau protocole majeur. Le test de
dérive compare à l'export courant, pas à une référence figée : toute régénération
de `contracts/local/` doit être relue dans le diff.

P4 ajoute `daemon.health` derrière la capability négociée `daemon.health`
(`DEC-0094`, proposed). Cette commande séparée est additive : elle ne modifie
pas les réponses strictes `daemon.status` des pairs P1 existants.

P11 sert `workspace.validate/get_config/save_config` (capability existante
`workspace.config`, formes inchangées) et ajoute deux commandes sous cette
même capability (`DEC-0097`, proposed) : `workspace.confirm_roots` (lie des
racines lisibles choisies dans le dialogue natif à un identifiant opaque
single-use à TTL court, consommé par `save_config`) et `workspace.git_status`
(sonde Git en lecture seule : état, branche, remote, détaché). Les anciens
pairs ignorent ces commandes ; l'export compte 31 commandes.

## Fixtures

94 fixtures valides et 23 invalides nommées, couvrant : runtime
compatible/incompatible, daemon running/unavailable/crash-recovery, workspace
valide/absent-déplacé, Knowledge disabled/indexing/ready, Code Graph
absent/indexing/ready, Graphify incompatible, graphes vide / Knowledge / Code /
partiel / projection, harness absent/détecté/configuré, permission refusée,
keyring indisponible, mauvais profil. Elles sont déterministes (horodatage et
UUID fixes) et ne contiennent aucune valeur secrète.

## Écarts et limites assumés

- Le JWT du serveur correspond à la machine du dashboard : la distinction
  humain/machine est portée côté local uniquement ; aucune évolution serveur en P1.
- Le transport de `SharedStatusSummary` est différé
  (`PublicationOutcome.TRANSPORT_UNAVAILABLE`) : il exige un contrat serveur
  versionné, hors périmètre P1.
- Enregistrement, rotation et révocation de machine (R4) et cible d'API serveur
  négociée au-delà de `PeerInfo.server_origin` (informatif) sont différés.
- Résidus connus, à couvrir par l'implémentation : le daemon doit émettre et
  contrôler `root_confirmation_id` et comparer `current_roots` à la config
  stockée ; les cibles de harness sensibles hors liste protégée
  (`.github/workflows`, `.gitmodules`, `package.json`…) restent couvertes par la
  confirmation et le hash du plan ; la détection de secrets et de chemins par
  forme est best-effort ; un consommateur rejoue `negotiate()` au lieu de faire
  confiance à une `HandshakeResponse`.
- Les contrats décrivent le comportement attendu ; aucun n'a été éprouvé contre un
  vrai daemon, Tauri, keyring, Graphify ou harness.

## Décisions humaines (2026-09-20)

1. `DEC-0093` acceptée.
2. Report du transport de publication et de l'identité humaine côté serveur
   validé.
3. `studio.local/v1` est la baseline commune de P2–P10 ; aucune lane ne la
   redéfinit unilatéralement (évolutions additives compatibles seulement).
4. `root_confirmation_id` obligatoire sur la transition de racines, pas sur
   toute config.
