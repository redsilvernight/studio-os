# P1 — Essais des harnesses réels (2026-11-04)

**Résultat : Claude lancé mais bloqué à l’authentification ; Codex et OpenCode non lancés.** Aucun résultat textuel de modèle et aucun cycle MCP validé. Aucun commit, push, merge, déploiement ou appel mutable Studio OS.

## Protocole préparé

Un prompt commun, conservé dans `harness-claude-prompt.txt`, fournit `studio-task/SKILL.md` et `references/completion.md`, puis trois scénarios indépendants : audit strictement lecture seule ; signal E1 redélivré déjà traité et E2 non traité appartenant à une autre cible active ; test obligatoire réellement échoué, changement non versionné et clôture demandée. La réponse attendue est uniquement un JSON d’appels **théoriques**, interdictions et états. Aucun outil MCP ne doit être exécuté.

## Commandes et observations

Commandes d’inspection réellement exécutées via `local_run`, exit 0 sauf mention :

- `Get-Command claude,codex,opencode` ; `claude.exe --help` ; `opencode.ps1 run --help` (`harness-cli-help.log`). Codex absent du PATH.
- `C:/Users/redsi/AppData/Local/OpenAI/Codex/bin/a159911ff70742e9/codex.exe exec --help` ; `features list --ignore-user-config` : cette seconde commande échoue, option inconnue ; exit agrégé 1 (`harness-codex-help.log`).
- Même binaire : `features list -c 'mcp_servers={}'`, exit 0 (`harness-codex-features.log`). Aucun prompt modèle dans ces inspections.

**Claude** : lancement préparé par `harness-claude-trial.ps1` avec `ProcessStartInfo.ArgumentList`, dossier temporaire hors dépôt, fenêtre masquée, timeout 90 s, arrêt de l’arbre à expiration, capture stdout/stderr et métadonnées. Arguments exacts avant le prompt :

```text
--print --bare --tools "" --strict-mcp-config --mcp-config {"mcpServers":{}} --no-session-persistence --disable-slash-commands --no-chrome --setting-sources "" --output-format json
```

`--bare` documente la désactivation des hooks, plugins et découverte CLAUDE.md ; il exclut aussi OAuth/keychain. Le premier appel `local_run` du script a été **rejeté avant exécution** par l’examen automatique : transmission des deux fichiers de politique à un service Claude externe sans autorisation explicite reconnue pour ces données. Message conservé dans `harness-launch-rejection.log`.

Après autorisation explicite de l’utilisateur pour ces deux fichiers, le même essai a été relancé une fois : **processus Claude exit 1 en 2,57 s**, sans timeout ; `is_error=true`, `terminal_reason=api_error`, message « Failed to authenticate: OAuth session expired and could not be refreshed ». `duration_api_ms=0`, tokens entrée/sortie=0, coût=0 USD : aucune décision LLM. Le wrapper local_run finit à 0 car il a conservé les traces ; ce n’est pas un succès du processus enfant. Voir `harness-claude-metadata.json`, stdout/stderr et `harness-claude-run.log`. Aucun nouvel essai.

**Codex** : non lancé. Les options d’isolation du contexte existent (`--ignore-user-config --ignore-rules --ephemeral --sandbox read-only --skip-git-repo-check`, dossier temporaire, MCP vide). Cependant, aucune neutralisation globale prouvée de tous les outils, notamment `apply_patch`, n’a été établie. Lecture seule ne signifie pas absence d’outils.

**OpenCode** : non lancé. `--pure` est documenté comme désactivant les plugins externes. Les chaînes embarquées attestent les variables de configuration, mais ne prouvent pas une isolation complète des MCP/configurations héritées ni l’efficacité globale d’une permission `"*":"deny"`. Aucun dispatch utilisé.

## Limites et reprise

L’autorisation de transmission a été accordée. Authentification CLI à rétablir par l’utilisateur avant tout futur essai ; aucun modèle imposé ni identifiant modifié. Codex/OpenCode nécessitent une méthode d’isolation vérifiée. Même une future réussite JSON prouverait une décision textuelle réelle du LLM, **pas** l’exécution réelle du cycle Studio OS.
