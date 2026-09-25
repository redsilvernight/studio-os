# DESKTOP P9 — Harness Adapters (`desktop/harness-adapters`)

Base : `origin/desktop/integration` `4b8aad17f1b08840d68ea54d171231dc2f874d58` (P0→P8).
Contrats P1 (`studio.local/v1`) utilisés tels quels : les commandes
`harness.detect/status/preview/apply/rollback` existaient déjà. Ajouts
additifs ultérieurs : `harness.verify` / `token_missing` (DEC-0104 §1),
`HarnessChange.scope` et `HarnessPreviewRequest.renew` (DEC-0104 §2).

**Règle absolue.** Studi'OS ne gère ni modèle, ni abonnement, ni clé de
fournisseur. P9 ne demande, ne stocke, ne lit ni ne modifie jamais
`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, une clé OpenCode Go, un jeton de modèle ou
un compte Claude/OpenAI. Il configure uniquement *harnais → MCP Studi'OS*.
Chaque couple poste + outil reçoit **son propre identifiant Studi'OS**
(DEC-0104 §2), écrit uniquement dans la configuration utilisateur de l'outil ;
le credential Desktop ne quitte jamais le trousseau. Voir § « Identifiant dédié ».

## Audit : CURRENT / TARGET / GAP

| | Avant P9 | Cible P9 | Écart comblé |
|---|---|---|---|
| Contrat | `harness.*` défini (P1), non servi | inchangé | — |
| Daemon | commandes refusées (`not_supported`) | servies par `LocalFeatures` | `harness/service.py`, `daemon/local_features.py` |
| Détection | aucune | réelle, bornée, fail-closed | `probe.py`, adaptateurs |
| Écriture | aucune | aperçu → sauvegarde → écriture atomique → vérification | `fsafe.py`, `backup.py`, `service.py` |
| Retour arrière | aucun | rollback avec détection de divergence | `backup.py`, `service.py` |
| Dashboard | aucun écran | Paramètres › Intégrations IA (Desktop) ; page d'état côté Web | `views/integrations.ts`, `harnessApi.ts` |
| Tauri | commandes non autorisées | `harness.*` dans l'allowlist | `allowlist.rs`, `info.rs` |

Scope réel de la configuration MCP (audité sur Claude Code 2.1.272 et
OpenCode 1.18.31) :

- **Claude Code** : entrée `studio-os` au scope utilisateur (`~/.claude.json`,
  clé `mcpServers`), écrite et retirée **uniquement par la CLI officielle**
  (`claude mcp add-json|remove --scope user`) : le fichier mélange état
  applicatif et comptes, Studi'OS ne l'édite pas lui-même. Le `.mcp.json` du
  projet n'est touché que pour en retirer l'ancienne entrée par référence.
- **OpenCode** : entrée `studio-os` dans le fichier global
  `~/.config/opencode/opencode.json[c]` (clé `mcp`), par édition JSONC non
  destructive (fournisseurs et clés de modèles conservés octet pour octet).
  `opencode.json[c]` du projet : seule l'ancienne entrée par référence est
  retirée.

Aucun balayage du disque : les seuls chemins possibles sont des noms de fichiers
fixes sous la racine d'un dossier de travail que Studi'OS connaît déjà, ou sous
le home de l'utilisateur (`HarnessChange.scope = user`, cible relative au home).

## Architecture

```
Dashboard ─▶ plateforme ─▶ pont Tauri (allowlist) ─▶ daemon (LocalFeatures)
                                                        │
                                              HarnessService
                                                        │
                                              HarnessRegistry
                                       ┌────────────────┴───────────────┐
                                 ClaudeCodeAdapter               OpenCodeAdapter
                                       └── JsonMcpAdapter (base commune JSON/JSONC)
```

Le Dashboard n'exécute, ne lit ni n'analyse jamais un fichier de harnais : il
envoie des commandes `harness.*` et affiche des réponses validées. Tout ce qui
est propre à un éditeur (nom de fichier, clé, forme de l'entrée, question de
version) vit dans l'adaptateur ; il n'existe aucun `if harness == …` hors des
adaptateurs.

| Chemin | Rôle |
|---|---|
| `packages/studio-client/src/studio_client/harness/base.py` | `HarnessAdapter`, `HarnessContext`, `Detection`, `PlannedEdit`, `AdapterRefusal` |
| `.../harness/registry.py` | `HarnessRegistry` (register / adapters / get / detect_all) |
| `.../harness/json_mcp.py` | Édition non destructive commune (JSON/JSONC) |
| `.../harness/claude_code.py`, `opencode.py` | Les deux adaptateurs (≈30 lignes chacun) |
| `.../harness/jsonc.py` | Analyseur/éditeur JSONC préservant commentaires et propriétés inconnues |
| `.../harness/fsafe.py` | Confinement des chemins, lecture bornée, écriture atomique |
| `.../harness/probe.py` | Recherche d'exécutable et sonde de version bornée |
| `.../harness/backup.py` | Sauvegardes locales, rétention, restauration |
| `.../harness/service.py` | Aperçu / application / rollback, plans en mémoire |
| `.../harness/credentials.py` | Création/révocation des machines par outil, registre local non secret |
| `.../harness/redaction.py` | Masquage de l'entrée `studio-os` (plans, hashs, sauvegardes, journaux) |
| `dashboard/src/harnessApi.ts`, `views/integrations.ts` | Client typé et écran |
| `tests/harness/` | Tests (unitaires sur système de fichiers temporaire, sécurité, pont, exécutables réels) |
| `dashboard/e2e/harness-p9.spec.ts` | Scénarios navigateur (Web propre, Desktop simulé) |

## Registre

`HarnessRegistry.register(adapter)` refuse un `adapter_id` en double. `detect_all`
interroge les adaptateurs en parallèle. `default_adapters()` liste les adaptateurs
livrés. Les capacités d'un adaptateur (`capabilities`) sont exposées dans
`HarnessStatus`.

## Détection

États internes → états du contrat P1 :

| Détection | `HarnessState` (contrat) |
|---|---|
| `not_installed` | `not_detected` |
| `configuration_missing` | `detected` |
| `configured` | `configured` |
| `configuration_invalid`, `unavailable` | `error` (avec `reason`) |
| `incompatible` | `incompatible` |

Sonde : recherche de l'exécutable **uniquement** dans les entrées absolues du
`PATH`, hors répertoire courant et hors dossier de travail (anti-usurpation) ;
lancement `shell=False` avec environnement assaini (aucune variable de type clé
ou jeton), 8 s de délai maximum, sortie ≤ 4 Kio, sortie de version validée par
expression régulière d'identité. Rien n'est téléchargé, installé ni exécuté
au-delà de `--version`. `detect` et `status` fonctionnent même si
`features.harness` est désactivé ; `preview/apply/rollback` répondent alors
`feature_disabled`.

## Compatibilité de version (fail-closed)

Claude Code : majeure 2. OpenCode : majeure 1. Toute autre version est
`incompatible` et n'est jamais modifiée. Un exécutable qui ne s'identifie pas,
ou une version illisible, mène au même refus.

## Aperçu, application, rollback

1. **`harness.preview`** : lit, calcule les modifications (`create/modify/delete`,
   résumé), n'écrit rien. Le plan (`plan_id`, `plan_hash`) vit 600 s en mémoire et
   n'est consommable qu'une fois.
2. **`harness.apply`** (`confirmed=true`, `plan_hash` identique) : revérifie que
   le fichier n'a pas changé depuis l'aperçu, crée la **sauvegarde**, valide le
   résultat, écrit un fichier temporaire dans le même dossier, le revalide,
   remplace atomiquement, relit et vérifie. En cas d'échec, l'original est
   rétabli (`verify_failed`) ; si ce rétablissement échoue lui-même, l'erreur
   `restore_failed` le dit et la sauvegarde reste restaurable. Rien n'est déclaré
   appliqué avant la vérification.
3. **`harness.rollback`** : compare le hash actuel au hash *après application*. Si
   l'utilisateur a modifié le fichier depuis, le rollback est refusé
   (`INVALID_REQUEST`, `details.reason = rollback_conflict`) : aucune
   restauration à l'aveugle. L'alias `latest:<workspace>:<adapter>` désigne la
   sauvegarde restaurable la plus récente.

**Idempotence** : une seconde configuration produit un plan vide (« Déjà à jour »),
ne réécrit rien et ne crée aucune sauvegarde.

**Non destructif** : les autres serveurs MCP, plugins, permissions, hooks,
fournisseurs, commentaires JSONC et propriétés inconnues sont conservés
octet pour octet hors de l'entrée `studio-os`. S'il n'existe pas d'édition sûre
(JSON invalide, clés dupliquées, fichier trop gros, non UTF-8, imbriquation
abusive, nombre hors limites, lien symbolique, plusieurs fichiers candidats),
l'écriture est refusée. Une entrée `studio-os` déjà présente mais différente n'est
remplacée qu'après aperçu et confirmation (l'aperçu l'indique) ; sa valeur
précédente reste dans la sauvegarde.

## Sauvegardes

- Emplacement : `<data_root>/harness-backups/<workspace_uuid>/<adapter_id>/<rb-id>/`
  (donnée locale de Desktop ; jamais envoyée au serveur, jamais dans Git).
- Identifiant : `rb-<32 hex>` ; un manifeste porte les hashs avant/après.
- Rétention : 10 sauvegardes par dossier de travail et par adaptateur, les plus
  anciennes sont supprimées après une application réussie.
- Bornes : chaque fichier ≤ 1 Mio ; si la sauvegarde est impossible, l'écriture
  n'a pas lieu.
- Une sauvegarde est la copie fidèle du fichier de l'utilisateur, qui peut donc
  contenir ses propres réglages ou clés (ex. un fournisseur dans `opencode.jsonc`) :
  elle reste locale (dossier en mode 0700 là où l'OS le permet), jamais envoyée,
  jamais journalisée. Côté configuration utilisateur de l'outil, seule l'entrée
  `studio-os` **masquée** est sauvegardée (`redaction.py`), jamais le fichier
  ni l'identifiant Studi'OS.

## Formes écrites

Claude Code (`~/.claude.json`, via `claude mcp add-json --scope user`) :

```json
{"mcpServers": {"studio-os": {"type": "http", "url": "<origine>/mcp",
  "headers": {"Authorization": "Bearer <identifiant de l'outil>"}}}}
```

OpenCode (`~/.config/opencode/opencode.json[c]`) :

```json
{"mcp": {"studio-os": {"type": "remote", "url": "<origine>/mcp", "enabled": true,
  "headers": {"Authorization": "Bearer <identifiant de l'outil>"}}}}
```

`<origine>` est l'origine serveur configurée dans Desktop. Aucun fichier du
dépôt ne reçoit d'entrée `studio-os`.

## Identifiant dédié (DEC-0104 §2)

- **Création** : à l'application, Desktop crée via l'API, avec son propre
  credential lu dans le trousseau, une machine `<POSTE> · <Outil>` (ex.
  « FLO-LAPTOP · Claude Code ») appartenant au même propriétaire (droits V1 du
  propriétaire, isolation par projet). Le credential renvoyé n'est écrit que dans
  la configuration utilisateur de l'outil.
- **Jamais ailleurs** : ni plan, ni diff, ni résultat, ni erreur, ni journal, ni
  diagnostic, ni sauvegarde. Seule exception technique : pour Claude Code, il
  transite par l'argv du processus enfant `claude mcp add-json` (jamais
  journalisé).
- **Registre local** (`credentials.json`, données du daemon) : id, nom et
  empreinte de la machine de chaque outil, révocations en attente si le serveur
  est injoignable (rejouées plus tard). Aucun credential.
- **Renouvellement** (« Renouveler l'identifiant », `harness.preview` avec
  `renew: true`) : nouvelle machine → écriture de la config → révocation de
  l'ancienne.
- **Restauration / suppression** : retrait de l'entrée → révocation.
- **Migration** : une ancienne entrée projet `${STUDIO_MCP_MACHINE_TOKEN}` /
  `{env:…}` est retirée du fichier du dépôt (supprimé s'il ne contenait
  qu'elle, sauvegardé sinon). Une entrée projet `studio-os` étrangère est un
  conflit signalé (`project_entry_conflict`), jamais écrasée.

Vérification (`harness.verify`, action « Vérifier la connexion » de l'écran) :

| État | Sens |
|---|---|
| `unconfigured` | pas d'entrée `studio-os` |
| `token_missing` | entrée par référence à une variable d'environnement (`reason=token_reference`) ou sans Bearer : à reconfigurer |
| `verified` | `initialize` + `tools/call studio_get_projects` réussis avec l'identifiant de la config |
| `failed` | détection en erreur ou appel MCP refusé (`mcp_unauthorized` si révoqué : renouveler) |

`configured` reste dans le contrat pour compatibilité mais n'est plus renvoyé
par `harness.verify`. Le daemon ne lit jamais `STUDIO_MCP_MACHINE_TOKEN`.

## Sécurité

Confinement (traversée, chemins absolus, `\`, lecteurs, liens symboliques et
jonctions, racine liée), exécutables (usurpation, délai, sortie bornée,
environnement assaini), fichiers hostiles (non UTF-8, taille, clés dupliquées,
imbriquation, contenu après la valeur, vide), écriture interrompue, sauvegarde
impossible, lecture seule, conflit de rollback, absence de secret dans logs,
plans, sauvegardes et erreurs, absence de toute référence à un identifiant de
fournisseur dans le paquet : `tests/harness/test_security.py`,
`test_service.py`, `test_adapters.py`. Côté Dashboard, les messages sont des
phrases fixes en français (jamais de texte brut du daemon, de chemin ou de
secret) et tout contenu est échappé.

## Interface

Paramètres › **Intégrations IA** (`#/configuration/integrations[/<workspace_uuid>]`) :
une carte par harnais (état, version, état MCP, fichier géré) ; actions
Configurer / Reconfigurer / Vérifier la connexion / Renouveler l'identifiant /
Restaurer (la restauration révoque l'identifiant de l'outil) ; cible
utilisateur affichée `~/…` ; aperçu affiché avant application ;
confirmation avant restauration ; le changement n'est présenté comme appliqué
qu'après une réponse `configured` sans erreur. Le Dashboard renégocie les
capacités du pont (`runtime.handshake`) une fois si le daemon a redémarré.

**Dashboard Web** : aucune détection, aucun accès fichier, aucune erreur de pont ;
la page indique que c'est une fonction de Studi'OS Desktop.

## Ajouter un troisième harnais

1. Créer `harness/<nom>.py` avec une sous-classe de `JsonMcpAdapter` (fichier(s)
   candidat(s), clé conteneur, forme de l'entrée, exécutables, majeure prise en
   charge) — ou de `HarnessAdapter` pour un format non JSON.
2. L'ajouter à `default_adapters()` dans `registry.py`.
3. Ajouter ses libellés éventuels dans le Dashboard (l'écran est piloté par
   `harness.detect`) et ses tests dans `tests/harness/`.

Aucun changement du domaine serveur, du contrat ni du service n'est requis.

## Limites et dettes

- Windows d'abord : validé sur Windows 11. Le code n'utilise ni chemin
  spécifique à un OS ni API Windows exclusive hors des tests de jonction, mais
  **aucune validation Linux/macOS n'est revendiquée**.
- Versions réellement sondées : Claude Code 2.1.272, OpenCode 1.18.31.
- Le pont ne sert pas `workspace.*` : l'écran prend l'identifiant du dossier dans
  la route ou un formulaire (dette : liste de dossiers via le pont).
- Identifiant en clair dans la config utilisateur de l'outil (lisible par les
  processus de l'utilisateur) : compromis assumé par DEC-0104, limité par la
  révocation par outil.
- Preuve live `desktop/e2e/mcp_harness_live.py` (identifiant dédié, rollback avec
  révocation) : exige la gate Postgres.
- `cargo fmt` / `cargo clippy` : composants non installés dans l'environnement de
  validation.
