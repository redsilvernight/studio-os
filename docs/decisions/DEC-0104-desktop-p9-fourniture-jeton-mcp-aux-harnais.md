---
id: DEC-0104
title: 'Desktop P9 : un identifiant Studi''OS dédié par couple poste + outil d''IA, état token_missing'
status: proposed
date: '2026-09-24'
superseded_by: null
source: docs/DECISIONS.md
---

# DEC-0104 — Fourniture du jeton machine aux harnais

Complète DEC-0096 (jeton par référence), qui supposait que « le mécanisme
d'identifiants existant de Desktop » fournissait `STUDIO_MCP_MACHINE_TOKEN` à
l'environnement du harnais. Constat sur Windows 11 : aucun code de `desktop/` ni
de `packages/` ne pose cette variable (seuls `tests/` et `desktop/e2e/` le font) ;
Claude Code envoie alors le texte `${STUDIO_MCP_MACHINE_TOKEN}` et le MCP répond
`unauthenticated: invalid or revoked machine token`.

## Partie 1 — état `token_missing` (appliquée dans ce lot)

`VerifyState` de `studio.local/v1` gagne `token_missing` : configuration en place
mais aucun jeton disponible, donc aucun appel MCP ne peut s'authentifier. Ce
n'est ni `configured` ni `verified` ; comme `configured`, il ne porte pas
d'`error`. `harness.verify` le renvoie au lieu de `configured` +
`details.reason=token_missing`. Le Dashboard (Paramètres › Intégrations IA)
ajoute l'action « Vérifier la connexion » et affiche une phrase française fixe
et actionnable.

Classification : ajout d'une valeur d'enum dans une réponse, derrière la
capability optionnelle `harness.verify`. Aucun consommateur existant n'appelait
`harness.verify` ; un Dashboard plus ancien qui l'appellerait rejetterait la
valeur inconnue à la validation de schéma (fail-closed), sans fausse réussite.

## Partie 2 — identifiant dédié par couple poste + outil (appliquée)

Remplace la recommandation « credential helper / relais » initiale (et la
décision serveur DEC-0116 qui la détaillait) : abandonnées, la première pour
ses inconnues Windows (shell, `PATH`, approbation de confiance d'un helper
versionné) et le coût d'un processus par connexion, le second pour la surface
d'un relais local.

- **Une machine Studi'OS par couple poste + outil**, nommée
  `<POSTE> · <Outil>` (ex. « FLO-LAPTOP · Claude Code »), créée par Desktop au
  nom de son propriétaire via l'API avec le credential Desktop lu dans le
  trousseau. Le credential Desktop n'est **jamais** transmis à un outil.
- **Droits V1** : ceux du propriétaire, avec l'isolation par projet existante.
- **Stockage** : le credential de l'outil n'existe en clair que dans la
  configuration utilisateur du harnais (`~/.claude.json` pour Claude Code,
  `~/.config/opencode/opencode.json[c]` pour OpenCode), en en-tête
  `Authorization: Bearer …`. Jamais dans le dépôt, les aperçus, diffs,
  résultats, erreurs, journaux, diagnostics ni sauvegardes (entrée masquée
  partout ailleurs). Amende DEC-0024 §3 pour ce seul cas.
- **Écriture** : Claude Code par sa CLI officielle (`claude mcp add-json
  --scope user` / `claude mcp remove --scope user`) ; le credential transite
  donc par l'argv de ce processus enfant, jamais par un journal. OpenCode par
  édition JSONC préservant le reste du fichier.
- **Migration** : les entrées projet `${STUDIO_MCP_MACHINE_TOKEN}` /
  `{env:STUDIO_MCP_MACHINE_TOKEN}` sont retirées du `.mcp.json` /
  `opencode.json[c]` du dépôt (fichier supprimé s'il ne contenait qu'elles) ;
  une entrée projet étrangère nommée `studio-os` est un conflit signalé, jamais
  écrasée.
- **Registre local non secret** (`credentials.json` du daemon) : id, nom et
  empreinte de la machine de chaque outil, et révocations en attente si le
  serveur est injoignable (rejouées ensuite). Aucun credential.
- **Renouvellement** (`HarnessPreviewRequest.renew=true`) : nouvelle machine,
  puis écriture de la config, puis révocation de l'ancienne.
- **Suppression / restauration** : retrait de l'entrée, puis révocation.
- **`verify()`** ne lit plus l'environnement du daemon : entrée qui référence
  une variable d'environnement → `token_missing` (`reason=token_reference`) ;
  entrée sans Bearer → `token_missing` ; entrée absente → `unconfigured` ;
  sinon appel MCP réel avec le credential de la config ; 401 → `failed`
  (`reason=mcp_unauthorized`).

Contrat local `studio.local/v1` : ajouts optionnels `HarnessChange.scope`
(`workspace` | `user`, cible relative au home pour `user`) et
`HarnessPreviewRequest.renew` (défaut `false`) ; additifs.

Options rejetées :

- **Credential helper (`headersHelper`) + relais stdio OpenCode** : voir
  ci-dessus.
- **Réutiliser le credential Desktop** : un outil compromis obtiendrait
  l'identité du poste ; pas de révocation par outil.
- **Variable d'environnement utilisateur (HKCU)** : jeton lisible par tout
  processus de l'utilisateur, propagation tardive, copie périmée après rotation.
- **Proxy MCP local dans le daemon** : tout processus local pourrait utiliser
  le jeton via le port ; point de défaillance unique.

Contrat Auth/Sync (`TECH/04_AUTH_SYNC_CONTRACT.md`) inchangé : le MCP reçoit
toujours le Bearer d'un jeton machine (DEC-0023/DEC-0024).
