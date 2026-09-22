# DESKTOP P9 — Harness Adapters (`desktop/harness-adapters`)

Base : `origin/desktop/integration` `4b8aad17f1b08840d68ea54d171231dc2f874d58` (P0→P8).
Contrats P1 (`studio.local/v1`) utilisés tels quels : les commandes
`harness.detect/status/preview/apply/rollback` existaient déjà. **Aucune
modification de contrat** ; seul le bundle Dashboard des schémas locaux a été
étendu (`gen-local-contracts.mjs`).

**Règle absolue.** Studi'OS ne gère ni modèle, ni abonnement, ni clé de
fournisseur. P9 ne demande, ne stocke, ne lit ni ne modifie jamais
`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, une clé OpenCode Go, un jeton de modèle ou
un compte Claude/OpenAI. Il configure uniquement *harnais → MCP Studi'OS*. Le
jeton Studi'OS n'est jamais écrit : les fichiers ne contiennent qu'une
**référence** à la variable d'environnement `STUDIO_MCP_MACHINE_TOKEN`.

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

- **Claude Code** : fichier de projet `.mcp.json` à la racine du dossier de
  travail, clé `mcpServers`. Le scope utilisateur (`~/.claude.json`) n'est pas
  touché : il mélange de l'état applicatif et des comptes.
- **OpenCode** : `opencode.json` ou `opencode.jsonc` à la racine du dossier de
  travail, clé `mcp`. Le fichier global (`~/.config/opencode/`) n'est pas
  touché : il porte les fournisseurs et clés de modèles.

Aucun balayage du disque : les seuls chemins possibles sont des noms de fichiers
fixes sous la racine d'un dossier de travail que Studi'OS connaît déjà.

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
  jamais journalisée. P9 n'ajoute lui-même aucun secret : seul le nom de la
  variable `STUDIO_MCP_MACHINE_TOKEN` est écrit.

## Formes écrites

Claude Code (`.mcp.json`) :

```json
{"mcpServers": {"studio-os": {"type": "http", "url": "<origine>/mcp",
  "headers": {"Authorization": "Bearer ${STUDIO_MCP_MACHINE_TOKEN}"}}}}
```

OpenCode (`opencode.json[c]`) :

```json
{"mcp": {"studio-os": {"type": "remote", "url": "<origine>/mcp", "enabled": true,
  "headers": {"Authorization": "Bearer {env:STUDIO_MCP_MACHINE_TOKEN}"}}}}
```

`<origine>` est l'origine serveur configurée dans Desktop. La variable
`STUDIO_MCP_MACHINE_TOKEN` doit être fournie à l'environnement du harnais par le
mécanisme d'identifiants existant de Desktop ; P9 ne la lit ni ne l'écrit.

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
Configurer / Reconfigurer / Restaurer ; aperçu affiché avant application ;
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
- Scope utilisateur/global des deux harnais volontairement non géré.
- La résolution `${STUDIO_MCP_MACHINE_TOKEN}` / `{env:…}` par les harnais suit
  leur documentation ; elle n'a pas été éprouvée de bout en bout avec un serveur
  Studi'OS réel dans cette phase.
- `cargo fmt` / `cargo clippy` : composants non installés dans l'environnement de
  validation.
