# Bibliothèque studio

Définitions communes à tous les utilisateurs de Studio OS, pensées pour un poste à **un seul agent IA** (Claude Code, Codex ou OpenCode, sans autre infrastructure). Source de référence republiable dans le scope `studio`.

## Contenu
| Kind | Dossier | Clés |
|---|---|---|
| rule | `rules/` | `core`, `git-flow`, `studio-protocol`, `studio-workflow`, `routing`, `memory`, `code-minimal` |
| skill | `skills/<clé>/SKILL.md` | `next`, `phase`, `delegate`, `new-project`, `release`, `review-pr`, `triage`, `roadmap-builder`, `workstation-setup`, `pixel-art-direction`, `sound-design`, `itch-io-publish`, `tiktok-pipeline` |
| agent_definition | `agents/` | `reader`, `worker`, `verifier`, `graphiste`, `sound-designer`, `monteur-video`, `devops`, `godot-tester`, `chef-marketing` |
| model_profile | `profiles/` | `single-agent` |
| workflow | `workflows/` | `task`, `hotfix`, `phase`, `new-project`, `release` |
| hook | `hooks/` | `git-guard`, `session-start`, `stop-check` |

## Format
Markdown avec frontmatter YAML : `kind`, `stable_key`, `scope`, puis les champs du schéma du kind (`description` ou `summary`, `requirements`, `participants`, `event`…). Le corps est le texte de la rule ou du skill, l'`intended_use` d'un agent. Un hook référence ses scripts (`hooks/<clé>.ps1`) par `file`.

## Principes
- Neutre : aucun fournisseur, modèle, chemin personnel ni outil hors Studio OS, Git et `gh`. Un agent métier déclare ses outils dans `## Prérequis`, avec un repli.
- Sans sous-agents : le découpage reste, l'agent principal enchaîne les livrables.
- Hooks en PowerShell 7 (`os: any`) ; blocage = code 2 et message sur stderr ; commande lue dans `tool_input.command` ou `args.command`.

## Surcouche utilisateur
Le scope `user` masque le scope `studio` à `kind` + `stable_key` égaux (DEC-0065). Une infrastructure personnelle (mémoire externe, coprocesseur local, équipe d'agents) se décrit dans une bibliothèque `user` qui redéfinit seulement les clés à changer (`routing`, `memory`, `delegate`, hooks…), hors de ce dépôt.

## Publication
`studio_publish_definition` par fichier (scope `studio`, droit administrateur), puis activation. Après publication : `studio-client skills sync`, `studio-client hooks-library sync --consent <clé>`, `studio-client adapters check`.
