# Claude First — verdict

Date : 2026-11-05. **Décision : `CLAUDE_NOT_READY`.** Le workflow fondamental n'est pas démontré dans l'environnement principal. Ce verdict ne dit pas que Claude Desktop ne peut pas se connecter; il dit que l'état actif n'a pas pu être observé et que les connexions CLI testées ont échoué.

## Statut par périmètre

| Périmètre | Statut | Motif |
|---|---|---|
| Claude Desktop | `BLOCKED` | Fenêtre/compte/connecteurs/outils non inspectés; version Desktop inconnue |
| Claude Code CLI | `PARTIAL` | CLI `2.1.316` et compte authentifié; six serveurs MCP échouent et l'essai readonly ne produit pas de réponse |
| Intégration Studi'OS | `PARTIAL` | Profil server-side et adaptateur Claude Code documentés; aucune session Claude native ne confirme le chemin réel |
| Cycle MCP | `PARTIAL` | Code actuel expose profil session 29 outils; historique 63 outils et échec d'ack post-handoff; correction de contrat documentée mais non testée nativement |
| Reprise après interruption | `BLOCKED` | Aucun essai de reprise Claude Desktop/Code dans cette mission; seulement une preuve d'intégration historique sur PostgreSQL isolé |

## Risques résiduels

1. Contradiction confirmée entre la règle personnelle globale (`start_work` systématique) et le protocole projet readonly. Le patch minimal est préparé mais non appliqué, car il modifie une configuration personnelle.
2. L'état des connectors MCP Claude Desktop reste inconnu; la config locale et les logs ne suffisent pas à le déterminer.
3. L'état CLI montre un compte authentifié mais aucune connexion MCP fonctionnelle. La cause réseau/auth précise n'est pas isolée.
4. Aucun catalogue tool-list runtime n'a permis de confirmer si le profil session est appliqué au client réel.
5. Les dépendances de test isolé ne sont pas accessibles depuis cette session; aucun test d'intégration P0/P1 n'a été rejoué.

## Suite pour lever les blocages

- Obtenir l'autorisation d'appliquer le patch de `CLAUDE-IMPLEMENTATION.md` au fichier personnel global, ou demander à l'utilisateur de l'appliquer.
- Exécuter le protocole de `CLAUDE-ARCHITECTURE.md` dans Claude Desktop et conserver une capture expurgée de **Settings > Connectors**, des outils annoncés et du modèle utilisé.
- Réparer/diagnostiquer les six connexions MCP CLI sans publier leurs URLs ni credentials; utiliser un projet et une base isolés pour les essais C03–C15.
- Rejouer ensuite les scénarios natifs, notamment signal → traitement durable → ack avant handoff, puis récupération stateless post-handoff.

La mission n'est pas certifiée prête. Aucun changement de code, de configuration personnelle ou de permissions n'a été appliqué; aucun test n'est déclaré réussi dans cette mission.

## Mise à jour Round 2 — 05/11/2026

La phrase précédente décrit le checkpoint initial et son historique est conservé. Depuis, l'utilisateur a autorisé le remplacement exact de la règle personnelle `~/.claude/rules/studio-protocol.md`; application, sauvegarde et contrôle du fichier sont documentés dans [CLAUDE-PATCH-APPLICATION.md](CLAUDE-PATCH-APPLICATION.md).

| Périmètre | Statut | Preuve | Blocage restant |
|---|---|---|---|
| Patch personnel | `VALIDATED` | Remplacement unique; comparaison complète avec la sauvegarde exacte. | `studio-workflow.md` personnel reste ambigu pour readonly; aucun autre fichier personnel n’était autorisé. |
| MCP Studi’OS | `VALIDATED` | `Connected` avec configuration inchangée; un appel `studio_prepare_context` et lectures Claude Code réussis. | Cette preuve est Claude Code, pas le connecteur de conversation Desktop. |
| Autres MCP | `PARTIAL` | Quatre autres serveurs connectés; `postgres-test` échoue avec `CONNECTION_CLOSED`. | Cause aval du processus PostgreSQL MCP inconnue. |
| Claude Code CLI | `PARTIAL` | `2.1.316`, authentifié; sessions readonly appellent les outils de lecture sans mutation Studi’OS. | Un run s’arrête sur `error_max_turns`; chargement effectif des fichiers d’instructions non prouvé. |
| Claude Desktop | `BLOCKED` | App présente; config locale sans MCP local. | Fenêtre non inspectée de façon fiable; version et connecteurs distants à confirmer dans Settings → Connectors. |
| Workflow readonly | `PARTIAL` | `studio_prepare_context` puis lectures; aucun start/claim/sync/handoff/écriture Studio OS observé. | Pas de réponse finale exploitable et contradiction personnelle résiduelle. |
| Cycle complet | `BLOCKED` | Aucun scénario mutant lancé sur serveur distant. | Pas de PostgreSQL isolé; C04, C06–C11 et C15 restent non exécutés. |

**Décision globale : `CLAUDE_NOT_READY`.** Le comportement readonly est mieux étayé pour Claude Code, mais le workflow fondamental n’est pas démontré dans l’environnement principal Claude Desktop et le cycle essentiel reste bloqué.

Voir [CLAUDE-MCP-DIAGNOSTIC.md](CLAUDE-MCP-DIAGNOSTIC.md) et [CLAUDE-VALIDATION-ROUND2.md](CLAUDE-VALIDATION-ROUND2.md). Aucun code, projection Codex/OpenCode, configuration MCP personnelle, base, service de production, commit, push, merge ou déploiement n’a été modifié.
