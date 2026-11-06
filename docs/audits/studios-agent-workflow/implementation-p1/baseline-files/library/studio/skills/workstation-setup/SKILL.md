---
kind: skill
stable_key: workstation-setup
scope: studio
description: "Préparer un poste pour Studio OS avec un seul harnais (Claude Code, Codex ou OpenCode) : client, connexion MCP, synchronisation de la bibliothèque, consentement des hooks. Cas : nouveau poste, /workstation-setup, hooks ou skills manquants."
---

# Workstation setup — poste à un seul harnais

Rendre un poste opérationnel avec Studio OS et un seul agent IA. Toute modification de configuration persistante est annoncée avant d'être appliquée (rule `core`).

## Prérequis
- Git et `gh` authentifié (`gh auth status`).
- PowerShell 7 (`pwsh`) sur tous les OS : les hooks de la bibliothèque studio sont écrits en `pwsh`. Absent : l'installer ou ne pas activer les hooks (repli : rules seules, les garde-fous deviennent déclaratifs).
- Python ≥ 3.11 et `studio-client` installé ; compte Studio OS avec jeton.

## 1. Connexion
1. `studio-client login --api-base-url <origine>` : jeton rangé dans le trousseau du système.
2. Déclarer le serveur MCP Studio OS dans le harnais selon la documentation d'installation de Studio OS, puis vérifier que `studio_start_work` répond.
3. Identité d'agent : `studio-client agents ensure --harness <claude-code|codex|opencode> --json` ; noter `agent_id`.

## 2. Bibliothèque
1. Lancer `studio-client-daemon` : il projette rules et agents actifs (`~/.agents/`, puis le dossier du harnais).
2. Skills : `studio-client skills sync` (`skills check` pour vérifier).
3. Hooks : `studio-client hooks-library check` liste ceux qui attendent un consentement ; relire événement et script de chacun, puis `studio-client hooks-library sync --consent <stable_key>` (répétable). Un hook non consenti ne s'exécute pas ; `--disable <stable_key>` le retire.
4. Vérifier : `git-guard` actif bloque `git push --force` dans un dépôt de test ; `session-start` affiche `project_id` dans un dépôt suivi.

## 3. Dépôts
1. Lier chaque dépôt : `studio-client workspaces register --path <dépôt> --project-id <id>`.
2. Projections de projet (`.claude/`, `.codex/`, `.opencode/`) : régénérées puis vérifiées par `studio-client adapters check` ; jamais éditées à la main.

## Diagnostic
| Symptôme | Cause probable |
|---|---|
| Hooks muets | empreinte non consentie, `pwsh` absent du `PATH` |
| `project_id` vide | dépôt non lié, worktree hors racine déclarée |
| Skills absents | `skills sync` non lancé, daemon arrêté |
| 401 | jeton expiré : relancer `studio-client login` |
