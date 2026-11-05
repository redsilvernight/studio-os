# Claude First — diagnostic MCP Round 2

Date : 05/11/2026. CLI Claude Code : `2.1.316`; authentification `loggedIn=true`.

## Matrice des six serveurs distincts

Les configurations ont sept entrées : `opencode-dispatch` apparaît dans les scopes utilisateur et projet. Les valeurs d’URL, d’en-tête et de `DATABASE_URI` ne sont pas reproduites.

| Serveur | Transport / scope | Cause confirmée | Correction | Statut |
|---|---|---|---|---|
| `studio-os` | HTTP / utilisateur | Le contrôle sandboxé échouait en résolution DNS (`ENOTFOUND`). Avec le même fichier de configuration dans un processus autorisé au réseau, la connexion a abouti; Claude Code a ensuite appelé `studio_prepare_context` et les outils de lecture. | Aucune configuration changée; aucune substitution par un serveur local. | `VALIDATED` — découverte et appel readonly depuis Claude Code dans le contexte réseau autorisé. |
| `obsidian-memory` | HTTP / utilisateur | Échec `EACCES` dans le contrôle sandboxé; `Connected` au contrôle réseau autorisé. | Aucune. | `VALIDATED` — connexion MCP. |
| `local-ai-hub` | HTTP / utilisateur | Échec `EACCES` dans le contrôle sandboxé; `Connected` au contrôle réseau autorisé. | Aucune. | `VALIDATED` — connexion MCP. |
| `context7` | HTTP / projet | Échec DNS `ENOTFOUND` dans le contrôle sandboxé; `Connected` au contrôle réseau autorisé. | Aucune. | `VALIDATED` — connexion MCP. |
| `opencode-dispatch` | stdio / utilisateur et projet (même serveur) | `CONNECTION_CLOSED` dans le contrôle sandboxé; la commande locale existe et la connexion devient `Connected` dans le contexte réseau autorisé. | Aucune. | `VALIDATED` — connexion MCP. |
| `postgres-test` | stdio / projet | `CONNECTION_CLOSED` dans les deux contextes. `uvx` est disponible et la configuration transmet une valeur non vide pour `DATABASE_URI`; le processus se ferme avant le handshake. Cause aval non établie (serveur, base, TLS ou autre). | Aucune; aucun essai métier sur la base distante. | `FAILED` — outil MCP non découvert. |

## Interprétation

Les cinq erreurs initiales ne désignent pas cinq pannes de serveurs : elles disparaissent avec le même client et les mêmes configurations lorsque l’isolation réseau de l’exécution est levée. Cela confirme une limite du contexte sandboxé de ce contrôle. Le serveur `postgres-test` reste le seul échec reproductible. Son URI configuré n’a pas été affiché ni testé directement.

La base isolée requise pour C04 et les scénarios de cycle est indisponible dans ce poste : `STUDIO_TEST_DATABASE_URL` absent, Docker CLI présent mais daemon inaccessible; l’accès au gestionnaire de services Windows est refusé. Aucun test n’a été dirigé vers une base distante.
