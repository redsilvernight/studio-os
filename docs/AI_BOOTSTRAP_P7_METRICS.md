# AI Bootstrap P7 — Métriques d'onboarding d'un projet neuf

Tâche Studio OS `adb63761` — [AIB P7] E2E onboarding d'un projet Godot neuf et
métriques. Roadmap `Project AI Bootstrap`, phase `remote-launch`, §9 (« E2E Godot
vierge → ajout → bootstrap → Claude → reprise de tâche ; OpenCode/Codex sans
dupliquer ; mesure fichiers/tokens permanents/actions manuelles »).

La source machine fait foi : `docs/AI_BOOTSTRAP_P7_METRICS.json`
(`studio.p7.onboarding-metrics/v1`), régénérée et vérifiée par
`scripts/p7_onboarding_metrics.py` et
`tests/protocol/test_p7_onboarding_e2e.py`.

## 1. Méthode

Sur un dépôt Godot vierge et jetable (`project.godot`, `scenes/`, `scripts/`) :

1. on dépose une source projet minimale `.agents/` (une règle, un skill, une
   définition) — un projet neuf est « presque vide » en local (P4) ;
2. `bootstrap init` déclare le harness `claude-code`, `bootstrap sync` génère le
   bloc géré et les projections ;
3. on ajoute OpenCode et Codex (`init --overwrite` puis `sync`) **sans toucher
   `.agents/`** ;
4. un second `sync` doit être idempotent (0 écriture).

Le calcul est **déterministe** : mêmes sources → mêmes octets, mêmes chiffres. Le
scénario est rejoué à l'identique par le test ; `--check` échoue (exit 1) si la
baseline publiée diverge.

## 2. Résultats mesurés

### Sortie de `sync` (dépôt vierge, 3 harnesses)

| Mesure | Valeur |
|---|---|
| Fichiers produits (projections + blocs) | **9** |
| Octets produits | **4 115** |
| dont agents | 3 fichiers / 2 782 octets |
| dont règles | 1 fichier / 134 octets |
| dont skills | 3 fichiers / 792 octets |
| dont blocs gérés | 2 fichiers / 407 octets |
| Projections seules (`.claude/`, `.opencode/`, `.codex/`) | 7 fichiers / 3 708 octets |
| Fichiers écrits (1er harness, `claude-code`) | 5 |
| Fichiers écrits (ajout `opencode` + `codex`) | 4 |
| Écritures du second `sync` | **0** (idempotent) |

### Bootstrap permanent conservé dans le dépôt

| Mesure | Valeur |
|---|---|
| Total permanent | **6 fichiers / 1 526 octets** |
| Sources canoniques `.agents/` (hors manifeste) | 3 fichiers / 807 octets |
| Manifeste `.agents/bootstrap.json` | 1 fichier / 312 octets |
| Blocs gérés (`AGENTS.md`, `CLAUDE.md`) | 2 fichiers / 407 octets |
| Contexte Bibliothèque/Résolution (à la demande) | **non compté** — récupéré par `studio_prepare_context`, jamais laissé dans le dépôt |

Le bootstrap permanent tient donc en **~1,5 Ko** : c'est tout ce qui doit rester
dans le dépôt pour rendre le projet exploitable. Le contexte partagé (Bibliothèque,
Résolution, règles studio-scope) est chargé à la demande et n'occupe pas le dépôt.

### Ajout de harnesses sans recréer de sources

| Contrôle | Résultat |
|---|---|
| `.agents/` inchangé après ajout d'OpenCode/Codex | **oui** |
| `.opencode/skills/project-workflow/SKILL.md` == source canonique | **oui** |
| `.codex/skills/project-workflow/SKILL.md` == source canonique | **oui** |
| Bootstrap neutre (indépendant du harness) | **oui** |

OpenCode et Codex sont donc **ajoutés sans recréer** règles/skills/agents : la
source canonique `.agents/` reste unique, les projections sont régénérées.

## 3. Actions manuelles

Comptage des gestes humains (le reste est automatisé par le CLI/daemon).

**Onboarding (cible : ≤ 3)** — mesuré : **3**

| # | Action | Commande |
|---|---|---|
| 1 | Déclarer harnesses + identité projet | `studio-client bootstrap init --project-slug <slug> --project-name "<nom>" --harness claude-code` |
| 2 | Générer le bloc géré et les projections | `studio-client bootstrap sync` |
| 3 | Ouvrir le harness à la racine | `cd <repo> && claude` |

**Ajout d'un harness (cible : 0 édition de source)** — mesuré : **2 gestes, 0 source recréée**

| # | Action | Commande |
|---|---|---|
| 1 | Redéclarer le jeu de harnesses | `studio-client bootstrap init --overwrite --harness claude-code --harness opencode --harness codex` |
| 2 | Régénérer les projections | `studio-client bootstrap sync` |

L'enrôlement de la machine (jeton/keyring) est un prérequis au niveau machine, hors
décompte par projet. Le lancement à distance depuis le Dashboard (R4/R5) ne
supprime aucune de ces étapes : il les déplace sur la machine cible.

## 4. Reprise de tâche par un second agent

La reprise de bout en bout (agent A machine 1 → `coordination.handoff` → agent B
machine 2 → `studio_start_work` / `studio_sync`, signal reçu une seule fois, sans
doublon au rejeu) est couverte par l'E2E L4
`tests/mcp/test_agent_loop_sync_e2e.py`. P7 ajoute la garantie de continuité côté
dépôt : le bootstrap généré est **neutre** (bloc géré + projections identiques en
contenu canonique pour chaque harness), donc n'importe quel harness enregistré
reprend la tâche sans configuration supplémentaire.

## 5. Correspondance avec le gate P7

| Critère d'acceptation | Preuve |
|---|---|
| Automatisation du scénario E2E | `scripts/p7_onboarding_metrics.py` + `tests/protocol/test_p7_onboarding_e2e.py` |
| Métriques publiées | ce document + `docs/AI_BOOTSTRAP_P7_METRICS.json` (`--check`) |
| Reprise de tâche par un second agent | `tests/mcp/test_agent_loop_sync_e2e.py` ; continuité prouvée par la neutralité du bootstrap |
| OpenCode et Codex ajoutés sans recréer de sources | `harness_parity` : sources inchangées, projections == canonique |

## 6. Limites

- Le scénario ne lance pas un harness réel en CI : il vérifie le bootstrap et les
  projections (la « Claude/OpenCode/Codex » lancée est simulée par le contenu
  généré). Le lancement réel relève de R3–R5.
- Le skill `graphify` porte des fichiers `references/` non projetés (seul
  `SKILL.md` est copié) ; sans impact sur le projet vierge mesuré ici.
- Godot n'est pas requis : le dépôt est un stub `project.godot` (risque identifié
  au §9 de la roadmap).
