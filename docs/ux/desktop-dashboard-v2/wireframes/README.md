# Wireframes Desktop/Dashboard V2 — proposition modernisée

Wireframes de l'étape **P02-wireframes** (remplacent la première version), partant des intentions de `../mockups/` en retirant leur surcharge. Statut : **retenus par l'utilisateur** (3 octobre 2026).

Ouvrir `index.html` (autonome, sans dépendance) : sélecteurs écran (Accueil, Travail, Roadmap), largeur (1280, 1600, 2560) et thème. La ligne pointillée marque la ligne de flottaison. Rendu brut : `index.html?raw&screen=work&w=1600`.

## Principes

- **Une carte héros par écran** portant l'unique action primaire (C1).
- **Rail d'icônes à 1280 px**, barre latérale complète au-delà : la colonne contextuelle tient dès 1280.
- **Recherche en palette `Ctrl K`** dans la barre latérale, plus de barre de recherche concurrente.
- **Statut par point de couleur**, pas de badge ni de menu par ligne (C3).
- **Données du modèle réel uniquement** : `Task` n'a ni priorité, ni échéance, ni assigné humain → groupement par `status`, affichage de l'agent qui a pris la tâche ; progression = `criteria_checked/criteria_total` ; À valider = types réels de la file (travail IA, proposition de roadmap, décision…).
- **Identifiants techniques** seulement dans « Détails techniques », replié (C2). Un seul `connection-status` visible (C4).

## Adaptatif

| Écran | 1280 | 1600 | 2560 |
|---|---|---|---|
| Accueil | rail 72 · principal + contexte 300 | principal 760 + contexte 340 | 4 colonnes bornées : principal 760, Projets, Aujourd'hui, Activité (380) |
| Travail | liste 360 + fiche, propriétés en ligne | liste 400 + fiche (contenu 680 + propriétés 260) | + volet 380 : étape liée, décisions liées, même étape |
| Roadmap | principal + contexte 300 | + Décisions récentes | + colonne « Plan restant » 420 |

Aucune carte ne s'élargit avec l'écran ; le texte courant reste ≤ 68 ch.

## Écarts assumés vs mockups

- Accueil : table 3 tâches × 4 colonnes → 1 carte « Reprendre » + 2 suites ; projets en lignes, sans menus « … ».
- Travail : « Prioritaire / À poursuivre » → En cours / Bloquées / À démarrer ; propriétés en colonne latérale.
- Roadmap : 3 KPI → bandeau des 6 phases ; colonne « À retenir » (principes de design) supprimée.

## Autres écrans (P02-wf-*) — en attente de validation

Même langage et mêmes sélecteurs que `index.html` ; chaque page a sa revue « reste / disparaît / se déplace ».

| Étape | Wireframes | Revue |
|---|---|---|
| P02-wf-projects | `projects.html` | `review-projects.md` |
| P02-wf-review | `review.html` | `review-review.md` |
| P02-wf-agents | `agents.html` | `review-agents.md` |
| P02-wf-admin | `admin.html` | `review-admin.md` |
| P02-wf-tools | `tools.html` | `review-tools.md` |
