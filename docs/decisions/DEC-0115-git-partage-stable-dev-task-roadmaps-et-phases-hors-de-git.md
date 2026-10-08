---
id: DEC-0115
title: 'Git partagé : stable → dev → task, roadmaps et phases hors de Git'
status: accepted
date: '2026-09-25'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0115 — Git partagé : stable → dev → task, roadmaps et phases hors de Git

Décision proposée par l'utilisateur : simplifier le workflow Git partagé entre Codex, Claude et OpenCode. La branche par défaut master/main est stable et livrable ; dev est la branche d'intégration ; chaque tâche utilise task/<id8>-<slug> et exactement un worktree déterministe réutilisé lors des handoffs. Les roadmaps et phases restent des objets Studio OS mais ne créent plus de branches Git. Les hotfixes partent de la branche stable puis sont reportés dans dev. Première mise en œuvre : nouvelle version brouillon du skill de Bibliothèque, sans changement de code Studio OS, sans activation et sans migration/suppression de branches existantes.
