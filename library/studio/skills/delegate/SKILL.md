---
kind: skill
stable_key: delegate
scope: studio
description: "Découper en livrables vérifiables, les confier à reader/worker (ou les enchaîner soi-même sans sous-agents), puis intégrer. À charger avant lecture volumineuse, commande longue ou lot de tâches."
---

# Delegate — découper, router, intégrer

L'agent principal découpe, route et intègre ; les sous-agents exécutent. Méthode : rule `routing`. Harnais sans sous-agents : mêmes découpage et briefs, exécutés par l'agent principal un par un.

## 1. Découper
- Une tâche = un livrable vérifiable, quelques fichiers, un critère automatisable.
- Indépendantes → plusieurs `worker` en parallèle, chacun dans son worktree `task/*` ; dépendante → attendre puis intégrer avant de relancer.
- Tâche mixte (API + écran) → un `worker` par nature.
- Garder : architecture, contrats, sécurité, édition < 5 lignes, tâche sans critère, publication, clôture, verdict.

## 2. Router par nature, jamais par puissance
| Nature | Agent |
|---|---|
| lecture, résumé, sortie longue | `reader` |
| code, tests, refactor, design, docs, diagnostic | `worker` |
| vérification d'un livrable | `verifier` |
| métier (pixel art, son, vidéo, Godot, publication) | agent métier de la bibliothèque |

## 3. Brief `reader`
Consigne, périmètre exact (`chemin:a-b`), verdict attendu (≤ 200 mots + citations). Vérifier soi-même ce qui guide une décision.

## 4. Brief `worker` (≤ 10 lignes)
Objectif en une phrase ; critères (≤ 3, vérifiables) ; fichiers visés ; contrainte clé ; commande de validation. Jamais de secret. Autonome, sans appel Studio OS sauf contexte requis.

## 5. Suivre et intégrer
- Garder une part utile pendant que les `worker` tournent (contrat, glue, test d'intégration) ; répondre vite à une question ou un blocage ; jamais d'attente active.
- Échec : renvoyer l'erreur précise une fois ; deux échecs → reprendre soi-même ou redécouper.
- Fusionner les branches validées, suite complète une seule fois, puis CI ; supprimer branches et worktrees fusionnés, et ceux en lecture seule dès le verdict lu (rule `git-flow`).
