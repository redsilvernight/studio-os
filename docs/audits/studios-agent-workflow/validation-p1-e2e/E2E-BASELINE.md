# P1.5 — baseline

Date : 05/11/2026 (Europe/Paris). Lecture seule des états réels, puis essais limités aux données temporaires `p15-e2e`.

## Git et conservation

Départ : branche `dev`, HEAD `d5912008bf8847835d454d3af5083a779909754c`, index vide, trois worktrees préexistants. L’inventaire SHA-256 et les empreintes initiales sont dans `traces/baseline.json`. La vérification finale est dans `traces/preservation.json`.

Le dépôt avait déjà de nombreux changements P0/P1 : 2 328 chemins suivis et non suivis protégés avant les ajouts de cette validation. Aucun reset, commit, push, merge, déploiement ni régénération globale n’a été exécuté.

## Harnais et authentification

| Harnais | Version constatée | Authentification constatée |
|---|---|---|
| Claude Code | 2.1.316 | connecté, OAuth first-party |
| Codex CLI | 0.166.0-alpha.6 | connecté via ChatGPT |
| OpenCode | 1.18.32 | fournisseur/configuration utilisateur restés hors fixture |

Les commandes brutes sans secret sont dans `traces/native-baseline.json`. Les fichiers `.codex/config.toml`, `opencode.json`, `AGENTS.md` et `CLAUDE.md` ont leurs empreintes avant essais dans ce fichier de trace. Les essais natifs ont tourné dans des répertoires temporaires ; aucune configuration personnelle n’a été éditée.

## MCP et version

Le serveur MCP distant accessible dans la session dessert des projets réels. `/version` renvoie le dashboard ; les routes version testées n’attestent pas la version du contrat. Son API 5 est donc **inconnue**. Aucun essai mutant n’a visé ce serveur.

Le serveur local stdio charge directement les services depuis le dépôt et utilise PostgreSQL 18.6 neuf, port loopback 55441, base `studio_p15_test`, rôle dédié, schéma migré à head. Le contrat local importé annonce API 5. `MCP initialize.server_info.version` est vide. L’isolation réelle et les assertions de bout en bout priment sur une affirmation textuelle de l’agent.

## Isolation

Fixture créée dans cette base seulement : projet `P15 E2E ONLY` (`p15-e2e`), quatre agents dédiés et 24 tâches de test. Trois tâches sentinelles existaient avant toute session native : le projet et les données de production sont distincts. Secrets machine et mot de passe restent hors des traces ; les journaux bruts expurgent leurs valeurs.

L’instance PostgreSQL temporaire et ses données restent dans `.worktrees/p15-runtime-20261104` pour reprise ; aucun conteneur ou volume préexistant n’a été arrêté ni supprimé. Le précontrôle complet a échoué car MinIO local (127.0.0.1:55449) n’est pas disponible ; les essais sans stockage objet et les tests PostgreSQL ont continué.

## Observabilité

Les traces JSONL natives préservent l’ordre des appels, arguments, réponses MCP, outils chargés et métriques fournisseur lorsqu’elles sont exposées. OpenCode ne fournit pas de coût comparable vérifié avec abonnement : ses valeurs sont des coûts modèle estimés/affichés par le runtime, pas des factures. Codex CLI ne publie ici ni modèle effectif ni usage exploitable. Ne pas comparer ces nombres entre fournisseurs.
