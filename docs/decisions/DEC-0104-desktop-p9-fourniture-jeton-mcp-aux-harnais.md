---
id: DEC-0104
title: 'Desktop P9 : fourniture du jeton machine aux harnais par credential helper, état token_missing'
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

## Partie 2 — mécanisme de fourniture (proposé, non implémenté)

Recommandation : **credential helper**, le jeton reste dans le trousseau de l'OS
(`KeyringTokenStore`, service `studio-os`, clé = origine serveur).

- Claude Code : l'entrée `.mcp.json` utilise `headersHelper:
  "studio-client mcp-headers"` au lieu de `headers` avec `${…}`. La commande
  lit `CLAUDE_CODE_MCP_SERVER_URL`, résout le jeton pour `origin_of(url)` et écrit
  `{"Authorization":"Bearer …"}` sur stdout ; jamais de journalisation, erreur
  sans secret sur stderr. Aucun chemin ni argument propre à l'utilisateur dans le
  fichier du dépôt.
- OpenCode (pas de helper, seulement `{env:}`/`{file:}`) : entrée `type: "local"`
  lançant `studio-client mcp-relay <url>`, relais stdio → HTTP qui ajoute le
  Bearer lu dans le trousseau. Livrable dans un second temps.
- `verify()` cesse de lire l'environnement du daemon : helper introuvable →
  `failed` (`reason=helper_not_found`) ; pas de jeton dans le trousseau →
  `token_missing` ; sinon exécution du helper et appel MCP réel.

Options rejetées :

- **Variable d'environnement utilisateur (HKCU)** : jeton en clair lisible par
  tout processus de l'utilisateur et visible dans les dumps d'environnement,
  propagé seulement aux processus lancés après `WM_SETTINGCHANGE`, une seule
  origine, copie périmée après rotation ou révocation.
- **Proxy MCP local dans le daemon** : tout processus local pourrait utiliser le
  jeton via le port, sauf secret local supplémentaire ; découverte du port ;
  le daemon devient un point de défaillance unique.

Contrat Auth/Sync (`TECH/04_AUTH_SYNC_CONTRACT.md`) inchangé : le MCP reçoit
toujours le Bearer du jeton machine (DEC-0023/DEC-0024).

Questions ouvertes avant implémentation : lancement de `headersHelper` sous
Windows (shell utilisé, `studio-client` sur le `PATH` de l'installation Desktop
ou scope local `~/.claude.json` avec chemin absolu) ; approbation de confiance
exigée par Claude Code pour un helper dans un `.mcp.json` versionné (à signaler
dans l'UI) ; coût de lancement d'un processus Python par connexion ; choix du
SDK pour le relais OpenCode.
