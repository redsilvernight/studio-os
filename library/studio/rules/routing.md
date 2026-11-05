---
kind: rule
stable_key: routing
scope: studio
description: "Routage mono-IA : l'agent principal découpe et juge ; sous-agents reader/worker si le harnais en dispose, sinon exécution séquentielle bornée."
---

# Routage (une seule IA)

| Capacité | Rôle |
|---|---|
| Studio OS | État projet, tâches, claims, sessions, décisions, coordination, bibliothèque |
| Mémoire | rule `memory` |
| Sous-agent `reader` | Lectures volumineuses, sorties longues, résumés compacts avec citations |
| Sous-agent `worker` | Un livrable vérifiable par agent, isolé dans son worktree, en parallèle |
| Sous-agent `verifier` | Tests et lint proportionnés, verdict reproductible |
| Agent principal | Découpage, arbitrage, contrats, sécurité, intégration, verdict |

- Harnais sans sous-agents : l'agent principal fait lui-même `reader` / `worker`, une chose à la fois, avec les mêmes bornes (lecture ciblée, livrable vérifiable, validation citée).
- Seuils `reader` : lecture > 100 lignes ou 5 Ko, sortie de test, build ou diff longue ; exiger citations courtes ; vérifier soi-même ce qui guide une édition ou une décision ; jamais de comptage confié au lecteur.
- `worker` : brief ≤ 10 lignes, périmètre borné, critère vérifiable, validation citée ; plusieurs en parallèle s'ils ne touchent pas les mêmes fichiers.
- Reste à l'agent principal : moins de 5 lignes, jugement, architecture, contrats, sécurité, publication, clôture.
- Localiser avant de lire : recherche ciblée (`grep`, index de code s'il existe), puis lecture des seules lignes utiles.
- Confidentialité : données d'entreprise jamais vers un service externe non approuvé.
- Méthode et briefs : skill `delegate`. Domaines : skills et agents métier de la bibliothèque, chargés à la demande.
