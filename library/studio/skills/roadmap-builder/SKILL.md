---
kind: skill
stable_key: roadmap-builder
scope: studio
description: "Construire une roadmap d'implémentation mesurable à partir d'un brief (phases, étapes, critères, dépendances, décisions) puis la proposer pour validation humaine. Ne démarre jamais l'implémentation."
---

# Roadmap Builder

Transformer un brief en roadmap validable. Proposition uniquement : aucune modification de code, fichier, configuration ou service avant accord explicite.

## 1. Cadrer sans lire tout le projet
- Extraire du brief : objectif, état mesuré, contraintes non négociables, périmètre, livrables. Une question seulement si un point bloque la structure.
- Contexte : un seul `studio_prepare_context` si le projet est suivi, sinon le README et la doc d'entrée. Exploration de plus de 3 fichiers : `reader` (rule `routing`).
- Toute contradiction entre brief et état réel va en tête, comme décision.

## 2. Principes
- Mesurer avant d'optimiser : la première phase pose baseline et instrumentation ; chaque gain annoncé a une métrique avant/après.
- Séparer mesures établies, estimations, scénarios conditionnels, métriques manquantes.
- Choix fondés sur un essai local, pas sur des fiches techniques ; dégradation visible et retour arrière pour tout changement de service.
- Une étape = un livrable vérifiable, taille S (< ½ j), M (1–2 j), L (> 2 j) ; découper toute L non optionnelle.
- Ordonner par dépendances, marquer le parallélisable ; une attente de données est une dépendance explicite.

## 3. Chaque étape
Objectif · fichiers probables · prérequis · actions · critères vérifiables · tests · métriques · risques · retour arrière · `depends_on` · effort · parallélisable · **au moins une tâche planifiée** (sans tâche, l'hydratation ne crée rien).

## 4. Livrable dans le chat
Résumé ; frontières ; phases ordonnées ; graphe de dépendances ; matrice gain/effort/risque ; trois actions immédiates ; décisions humaines (D1…) ; questions ouvertes (Q1…) ; définition de terminé ; hors périmètre. Tableaux et listes, pas de prose répétée.

## 5. Proposer (après validation)
**Projet suivi** : `studio_propose_roadmap(project_id, idempotency_key, summary, document)` avec un document `studio.roadmap/v1` :
- `context` (≤ 4000 car.) : frontières, état mesuré, D/Q, terminé, hors périmètre ;
- `phases[].steps[]` : `key` stable (`P01-xxx`), `objective`, `instructions` (≤ 8000), `acceptance_criteria` (≤ 20 × 500), `depends_on`, `metadata` {effort, parallel, risk, rollback}, `tasks: [{hydration_key: "t-<step-key>", title}]`.

Statut `proposed` : approbation et activation humaines. Hydratation sur demande seulement : `studio_preview_roadmap_hydration` puis `studio_apply_roadmap_hydration(expected_version, idempotency_key)`. Révision : `studio_propose_roadmap` avec `roadmap_id` et `base_revision_no`, document complet.

**Projet non suivi** : `docs/ROADMAP-<slug>.md` dans le dépôt après accord, même structure.

À éviter : implémenter, créer des tâches ou activer sans accord ; étapes sans tâche planifiée ; gains sans métrique ; recopier le brief au lieu de le structurer.
