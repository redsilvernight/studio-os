# Catalogue canonique Library (Phase 2C)

Généré par `scripts/library_packages.py build` à partir de `library/packages/decisions.json`. Une décision qui ne peut pas être honorée (source absente, secret, référence personnelle dans une couche suivie) est rétrogradée `NOT_READY` avec la raison. Les versions sont celles de la rebuild : `active+1` quand la source canonique remplace une version historique.

## Synthèse

| Décision | Nombre |
|---|---:|
| CORE_PUBLIC | 38 |
| EXCLUDED_DUPLICATE | 6 |
| NOT_PUBLISHABLE | 4 |
| NOT_READY | 10 |
| PERSONAL_PRIVATE | 16 |
| PROJECT_SPECIFIC | 2 |

| Package | Entrées prêtes |
|---|---:|
| core | 38 |
| project | 2 |
| personal | 16 |

## Décisions

| Origine | Type | Clé | Version | Décision | Destination | Source | Justification |
|---|---|---|---:|---|---|---|---|
| project | model_profile | `architecture-deep` | 1 | PROJECT_SPECIFIC | project | `library/project/profiles/architecture-deep.md` | Profil de modèle des agents de revue du projet ; contenu récupéré depuis la Library. |
| project | model_profile | `coding-standard` | 1 | PROJECT_SPECIFIC | project | `library/project/profiles/coding-standard.md` | Profil de modèle des agents de revue du projet ; contenu récupéré depuis la Library. |
| studio | agent_definition | `chef-marketing` | 1 | CORE_PUBLIC | core | `library/studio/agents/chef-marketing.md` | Spécialisé mais générique : prérequis (outils, comptes) déclarés avec repli, aucune référence personnelle ; installé seulement sur demande. |
| studio | agent_definition | `devops` | 1 | CORE_PUBLIC | core | `library/studio/agents/devops.md` | Spécialisé mais générique : prérequis (outils, comptes) déclarés avec repli, aucune référence personnelle ; installé seulement sur demande. |
| studio | agent_definition | `godot-tester` | 1 | CORE_PUBLIC | core | `library/studio/agents/godot-tester.md` | Spécialisé mais générique : prérequis (outils, comptes) déclarés avec repli, aucune référence personnelle ; installé seulement sur demande. |
| studio | agent_definition | `graphiste` | 1 | CORE_PUBLIC | core | `library/studio/agents/graphiste.md` | Spécialisé mais générique : prérequis (outils, comptes) déclarés avec repli, aucune référence personnelle ; installé seulement sur demande. |
| studio | agent_definition | `monteur-video` | 1 | CORE_PUBLIC | core | `library/studio/agents/monteur-video.md` | Spécialisé mais générique : prérequis (outils, comptes) déclarés avec repli, aucune référence personnelle ; installé seulement sur demande. |
| studio | agent_definition | `reader` | 1 | CORE_PUBLIC | core | `library/studio/agents/reader.md` | Rôle stable et neutre ; outils métier déclarés dans « Prérequis » avec repli. |
| studio | agent_definition | `sound-designer` | 1 | CORE_PUBLIC | core | `library/studio/agents/sound-designer.md` | Spécialisé mais générique : prérequis (outils, comptes) déclarés avec repli, aucune référence personnelle ; installé seulement sur demande. |
| studio | agent_definition | `verifier` | 1 | CORE_PUBLIC | core | `library/studio/agents/verifier.md` | Rôle stable et neutre ; outils métier déclarés dans « Prérequis » avec repli. |
| studio | agent_definition | `worker` | 1 | CORE_PUBLIC | core | `library/studio/agents/worker.md` | Rôle stable et neutre ; outils métier déclarés dans « Prérequis » avec repli. |
| studio | hook | `git-guard` | 1 | CORE_PUBLIC | core | `library/studio/hooks/git-guard` | Script pwsh 7 court, lit la commande dans tool_input/args ; compatibilité restreinte aux runtimes dont l'événement est connu. |
| studio | hook | `session-start` | 1 | CORE_PUBLIC | core | `library/studio/hooks/session-start` | Script pwsh 7 court, lit la commande dans tool_input/args ; compatibilité restreinte aux runtimes dont l'événement est connu. |
| studio | hook | `stop-check` | 1 | CORE_PUBLIC | core | `library/studio/hooks/stop-check` | Script pwsh 7 court, lit la commande dans tool_input/args ; compatibilité restreinte aux runtimes dont l'événement est connu. |
| studio | model_profile | `single-agent` | 1 | CORE_PUBLIC | core | `library/studio/profiles/single-agent.md` | Profil sans fournisseur ni modèle nommé. |
| studio | rule | `code-minimal` | 1 | CORE_PUBLIC | core | `library/studio/rules/code-minimal.md` | Règle neutre (sans chemin, outil privé ni fournisseur) ; analyse de contenu par le contrôle de confidentialité. |
| studio | rule | `core` | 1 | CORE_PUBLIC | core | `library/studio/rules/core.md` | Règle neutre (sans chemin, outil privé ni fournisseur) ; analyse de contenu par le contrôle de confidentialité. |
| studio | rule | `git-flow` | 1 | CORE_PUBLIC | core | `library/studio/rules/git-flow.md` | Règle neutre (sans chemin, outil privé ni fournisseur) ; analyse de contenu par le contrôle de confidentialité. |
| studio | rule | `memory` | 1 | CORE_PUBLIC | core | `library/studio/rules/memory.md` | Règle neutre (sans chemin, outil privé ni fournisseur) ; analyse de contenu par le contrôle de confidentialité. |
| studio | rule | `routing` | 1 | CORE_PUBLIC | core | `library/studio/rules/routing.md` | Règle neutre (sans chemin, outil privé ni fournisseur) ; analyse de contenu par le contrôle de confidentialité. |
| studio | rule | `studio-protocol` | 3 | CORE_PUBLIC | core | `.studio/studio-protocol.md` | Remplacée par la rule canonique `.studio/studio-protocol.md` (8 points, entrées read-only/mutable) ; l'ancien texte v2 n'est plus la source. Remplace studio/rule/studio-protocol v2 (library/studio/rules/studio-protocol.md). |
| studio | rule | `studio-workflow` | 2 | CORE_PUBLIC | core | `library/studio/rules/studio-workflow.md` | Règle neutre (sans chemin, outil privé ni fournisseur) ; analyse de contenu par le contrôle de confidentialité. |
| studio | skill | `delegate` | 1 | CORE_PUBLIC | core | `library/studio/skills/delegate` | Procédure réutilisable sans dépendance personnelle ; prérequis déclarés dans le texte. |
| studio | skill | `itch-io-publish` | 1 | CORE_PUBLIC | core | `library/studio/skills/itch-io-publish` | Spécialisé mais générique : prérequis (outils, comptes) déclarés avec repli, aucune référence personnelle ; installé seulement sur demande. |
| studio | skill | `new-project` | 1 | CORE_PUBLIC | core | `library/studio/skills/new-project` | Procédure réutilisable sans dépendance personnelle ; prérequis déclarés dans le texte. |
| studio | skill | `next` | 2 | CORE_PUBLIC | core | `library/studio/skills/next` | Procédure réutilisable sans dépendance personnelle ; prérequis déclarés dans le texte. |
| studio | skill | `phase` | 2 | CORE_PUBLIC | core | `library/studio/skills/phase` | Procédure réutilisable sans dépendance personnelle ; prérequis déclarés dans le texte. |
| studio | skill | `pixel-art-direction` | 1 | CORE_PUBLIC | core | `library/studio/skills/pixel-art-direction` | Spécialisé mais générique : prérequis (outils, comptes) déclarés avec repli, aucune référence personnelle ; installé seulement sur demande. |
| studio | skill | `release` | 1 | CORE_PUBLIC | core | `library/studio/skills/release` | Procédure réutilisable sans dépendance personnelle ; prérequis déclarés dans le texte. |
| studio | skill | `review-pr` | 1 | CORE_PUBLIC | core | `library/studio/skills/review-pr` | Procédure réutilisable sans dépendance personnelle ; prérequis déclarés dans le texte. |
| studio | skill | `roadmap-builder` | 1 | CORE_PUBLIC | core | `library/studio/skills/roadmap-builder` | Procédure réutilisable sans dépendance personnelle ; prérequis déclarés dans le texte. |
| studio | skill | `sound-design` | 1 | CORE_PUBLIC | core | `library/studio/skills/sound-design` | Spécialisé mais générique : prérequis (outils, comptes) déclarés avec repli, aucune référence personnelle ; installé seulement sur demande. |
| studio | skill | `tiktok-pipeline` | 1 | CORE_PUBLIC | core | `library/studio/skills/tiktok-pipeline` | Spécialisé mais générique : prérequis (outils, comptes) déclarés avec repli, aucune référence personnelle ; installé seulement sur demande. |
| studio | skill | `triage` | 1 | CORE_PUBLIC | core | `library/studio/skills/triage` | Procédure réutilisable sans dépendance personnelle ; prérequis déclarés dans le texte. |
| studio | skill | `workstation-setup` | 1 | CORE_PUBLIC | core | `library/studio/skills/workstation-setup` | Procédure réutilisable sans dépendance personnelle ; prérequis déclarés dans le texte. |
| studio | workflow | `hotfix` | 1 | CORE_PUBLIC | core | `library/studio/workflows/hotfix.md` | Workflow documenté composé de rôles génériques. |
| studio | workflow | `new-project` | 1 | CORE_PUBLIC | core | `library/studio/workflows/new-project.md` | Workflow documenté composé de rôles génériques. |
| studio | workflow | `phase` | 1 | CORE_PUBLIC | core | `library/studio/workflows/phase.md` | Workflow documenté composé de rôles génériques. |
| studio | workflow | `release` | 1 | CORE_PUBLIC | core | `library/studio/workflows/release.md` | Workflow documenté composé de rôles génériques. |
| studio | workflow | `task` | 1 | CORE_PUBLIC | core | `library/studio/workflows/task.md` | Workflow documenté composé de rôles génériques. |
| user | agent_definition | `chef-marketing` | 1 | EXCLUDED_DUPLICATE | — | `home:…` | Doublon de la définition Core `chef-marketing` ; retirer cette copie user laisse la version Core s'appliquer (le scope user masque studio à clé égale). Remplace core/agent_definition/chef-marketing. |
| user | agent_definition | `devops` | 1 | EXCLUDED_DUPLICATE | — | `home:…` | Doublon de la définition Core `devops` ; retirer cette copie user laisse la version Core s'appliquer (le scope user masque studio à clé égale). Remplace core/agent_definition/devops. |
| user | agent_definition | `godot-tester` | 1 | EXCLUDED_DUPLICATE | — | `home:…` | Doublon de la définition Core `godot-tester` ; retirer cette copie user laisse la version Core s'appliquer (le scope user masque studio à clé égale). Remplace core/agent_definition/godot-tester. |
| user | agent_definition | `graphiste` | 1 | EXCLUDED_DUPLICATE | — | `home:…` | Doublon de la définition Core `graphiste` ; retirer cette copie user laisse la version Core s'appliquer (le scope user masque studio à clé égale). Remplace core/agent_definition/graphiste. |
| user | agent_definition | `haiku-reader-fallback` | 1 | PERSONAL_PRIVATE | personal | `home:…` | Agent de repli ou de lecture/action câblé sur mon routage (Hub, Haiku) ; surcharge personnelle. |
| user | agent_definition | `haiku-worker-fallback` | 1 | PERSONAL_PRIVATE | personal | `home:…` | Agent de repli ou de lecture/action câblé sur mon routage (Hub, Haiku) ; surcharge personnelle. |
| user | agent_definition | `monteur-video` | 1 | EXCLUDED_DUPLICATE | — | `home:…` | Doublon de la définition Core `monteur-video` ; retirer cette copie user laisse la version Core s'appliquer (le scope user masque studio à clé égale). Remplace core/agent_definition/monteur-video. |
| user | agent_definition | `reader` | 1 | PERSONAL_PRIVATE | personal | `home:…` | Agent de repli ou de lecture/action câblé sur mon routage (Hub, Haiku) ; surcharge personnelle. |
| user | agent_definition | `sound-designer` | 1 | EXCLUDED_DUPLICATE | — | `home:…` | Doublon de la définition Core `sound-designer` ; retirer cette copie user laisse la version Core s'appliquer (le scope user masque studio à clé égale). Remplace core/agent_definition/sound-designer. |
| user | agent_definition | `verifier` | 1 | PERSONAL_PRIVATE | personal | `home:…` | Agent de repli ou de lecture/action câblé sur mon routage (Hub, Haiku) ; surcharge personnelle. |
| user | agent_definition | `worker` | 1 | PERSONAL_PRIVATE | personal | `home:…` | Agent de repli ou de lecture/action câblé sur mon routage (Hub, Haiku) ; surcharge personnelle. |
| user (nouveau) | data | `claude-global-instructions` | 0 | NOT_PUBLISHABLE | — | `-` | Instructions globales Claude Code (CLAUDE.md) : fichier de configuration du poste, pas une définition Library ; couvert par les rules Personal. |
| user (nouveau) | data | `credentials-and-sessions` | 0 | NOT_PUBLISHABLE | — | `-` | Tokens, sessions, logs et dispatch jobs : secrets et données d'exécution. |
| user (nouveau) | data | `hub-index-and-graph-caches` | 0 | NOT_PUBLISHABLE | — | `-` | Index du Hub, graphe et caches Graphify : données dérivées reconstruisibles. |
| user (nouveau) | data | `vault-notes` | 0 | NOT_PUBLISHABLE | — | `-` | Notes Obsidian/AI-Memory, mémoire et profil : données privées, jamais publiées. |
| user | hook | `git-guard` | 1 | PERSONAL_PRIVATE | personal | `home:…` | Version poste du hook Core : relais vers le garde-fou OpenCode dispatch ; remplace le hook Core au scope user (DEC-0317). Hook sous consentement. |
| user (nouveau) | hook | `hub-first` | 1 | NOT_READY | — | `home:…` | Nouvel élément canonique absent du catalogue historique. Hook PreToolUse lié au Hub local et au câblage Claude Code ; à porter avec consentement à l'import. |
| user | hook | `read-guard` | 1 | NOT_READY | — | `home:…` | Script lié au câblage settings.json de Claude Code et à des chemins locaux ; événement/matcher/timeout non capturés dans une définition Library. À écrire avec consentement à la phase d'import. |
| user | hook | `session-start` | 1 | PERSONAL_PRIVATE | personal | `home:…` | Version poste du hook Core : hub local et annonce dispatch ; remplace le hook Core au scope user (DEC-0317). Hook sous consentement. |
| user | hook | `stop-check` | 1 | PERSONAL_PRIVATE | personal | `home:…` | Version poste du hook Core : rappel mémoire unique par session ; remplace le hook Core au scope user (DEC-0317). Hook sous consentement. |
| user | model_profile | `light-reader` | 1 | NOT_READY | — | `private:…` | Profil de routage lié à mon dispatcher/Hub ; exigences seules, aucun modèle ni clé. [source introuvable] |
| user | model_profile | `local-hub` | 1 | NOT_READY | — | `private:…` | Profil de routage lié à mon dispatcher/Hub ; exigences seules, aucun modèle ni clé. [source introuvable] |
| user | model_profile | `opencode-code` | 1 | NOT_READY | — | `private:…` | Profil de routage lié à mon dispatcher/Hub ; exigences seules, aucun modèle ni clé. [source introuvable] |
| user | model_profile | `opencode-debug` | 1 | NOT_READY | — | `private:…` | Profil de routage lié à mon dispatcher/Hub ; exigences seules, aucun modèle ni clé. [source introuvable] |
| user | model_profile | `opencode-design` | 1 | NOT_READY | — | `private:…` | Profil de routage lié à mon dispatcher/Hub ; exigences seules, aucun modèle ni clé. [source introuvable] |
| user | model_profile | `opencode-docs` | 1 | NOT_READY | — | `private:…` | Profil de routage lié à mon dispatcher/Hub ; exigences seules, aucun modèle ni clé. [source introuvable] |
| user | model_profile | `opencode-refactor` | 1 | NOT_READY | — | `private:…` | Profil de routage lié à mon dispatcher/Hub ; exigences seules, aucun modèle ni clé. [source introuvable] |
| user | model_profile | `opencode-tests` | 1 | NOT_READY | — | `private:…` | Profil de routage lié à mon dispatcher/Hub ; exigences seules, aucun modèle ni clé. [source introuvable] |
| user | rule | `memory` | 1 | PERSONAL_PRIVATE | personal | `home:…` | Règle personnelle (routage, mémoire, poste) ; masque la rule Core du même nom (DEC-0065). |
| user | rule | `routing` | 1 | PERSONAL_PRIVATE | personal | `home:…` | Règle personnelle (routage, mémoire, poste) ; masque la rule Core du même nom (DEC-0065). |
| user | rule | `workstation` | 1 | PERSONAL_PRIVATE | personal | `home:…` | Règle personnelle (routage, mémoire, poste) ; masque la rule Core du même nom (DEC-0065). |
| user | skill | `delegate` | 1 | PERSONAL_PRIVATE | personal | `home:…` | Procédure dépendant de mon infrastructure (dispatcher, laptop, poste) ou surcharge personnelle d'un skill Core. |
| user (nouveau) | skill | `delegate-local` | 1 | PERSONAL_PRIVATE | personal | `home:…` | Nouvel élément canonique absent du catalogue historique. Délégation via le Hub local, facultative, repli sur outils natifs. |
| user | skill | `dispatch-team` | 2 | PERSONAL_PRIVATE | personal | `home:…` | Procédure dépendant de mon infrastructure (dispatcher, laptop, poste) ou surcharge personnelle d'un skill Core. |
| user | skill | `laptop` | 1 | PERSONAL_PRIVATE | personal | `home:…` | Procédure dépendant de mon infrastructure (dispatcher, laptop, poste) ou surcharge personnelle d'un skill Core. |
| user | skill | `workstation-setup` | 1 | PERSONAL_PRIVATE | personal | `home:…` | Procédure dépendant de mon infrastructure (dispatcher, laptop, poste) ou surcharge personnelle d'un skill Core. |
