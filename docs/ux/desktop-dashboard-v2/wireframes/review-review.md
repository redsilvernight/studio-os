# Revue — File « À valider » (P02-wf-review)

Source lue : `dashboard/src/views/decisionsV2.ts` (file `review-queue`, onglets « À examiner » / « Décisions ») et contrat `ReviewQueue*` (6 types réels). Wireframe : `review.html` (`?raw&screen=queue|detail&w=1280|1600|2560`, thèmes clair/sombre).

## Revue de l'écran actuel

- La file vit sous « Décisions » (`#/decisions`), sans entrée « À valider » : 1 clic pour `ai_work_review`, ≥ 3 pour une roadmap (file → roadmap → relecture).
- Seuls `ai_work_review` (Approuver / Demander des modifications) et `decision_proposal` (Accepter / Remplacer, admin) sont actionnables ; `roadmap_proposal` renvoie vers la roadmap, les 3 autres n'ont aucune action.
- Chaque ligne expose le type technique brut, la provenance complète (UUID d'agent, UUID projet/tâche) et des blocs égaux (commit, workflow, branches) : bruit avant contexte et impact.
- Le détail mélange résumé, diff, provenance et commentaire ; proposition et révision d'un même plan peuvent donner deux entrées distinctes.

## Reste / disparaît / se déplace

| Élément actuel | Verdict | Destination wireframe |
|---|---|---|
| 6 types de la file | reste | 7 cartes (1 par objet), libellés humains, point de couleur |
| Approuver / Demander des modifications (IA) | reste | carte travail IA, 2 actions max |
| Accepter / Remplacer (décision, admin) | reste | carte décision, mention admin |
| Lien « Examiner dans Roadmap » | reste | carte roadmap : Examiner + Ouvrir la roadmap |
| Type technique brut (`kind`) | disparaît | libellé humain + replié en Détails techniques |
| UUID / préfixe d'agent en clair | disparaît | noms humains ; identifiants repliés (C2) |
| Commit, workflow, branches en blocs égaux | se déplace | une ligne de contexte ; le reste replié |
| Compteur « N élément(s) » + onglets | se déplace | filtre Tous / À décider / Signaux + héros unique |
| Proposition vs révision en 2 entrées | disparaît | une carte « Révision 2 du Plan » regroupée |
| Items sans action, muets | se déplace | cartes honnêtes : navigation seule (≤ 2 liens) + mention « non résoluble ici » |
| Détail roadmap (résumé, diff, provenance, commentaire) | se déplace | écran Détail : Contexte, Changements, Impact, Technique repliée |

## Écarts assumés

- Conflit, build et PR gagnent des liens de navigation (Voir le fichier / build / PR, Ouvrir la tâche) : le code actuel n'offre rien ; sans sortie, le signal est mort (baseline n° 7).
- Détail P02-wf-review : révision fictive mais plausible (révision 2, base 1, +2 étapes) pour montrer scope, diff et impact ; champs = contrat réel (`scope`, `revision_no`, `base_revision_no`, `summary`, `actor_type`, `status`).
- File triée « plus récent d'abord », filtre À décider / Signaux : interprétation du contrat (`requested_at` desc, résoluble vs informatif), pas du code.

## Mapping par largeur

| Zone | 1280 (rail 72) | 1600 (barre complète) | 2560 (borné, rien n'est étiré) |
|---|---|---|---|
| File | héros + file + contexte 300 | file 760 + contexte 340 | + Historique récent 380 |
| Détail | contenu + contexte 300, propriétés en ligne | contenu 680 + propriétés 260 | + Étapes concernées 380 |
| Texte courant | ≤ 68 ch partout ; cartes à largeur bornée |

## C1 à C4 (4 lignes)

- C1 : une seule action primaire par écran (« Examiner la révision 2 », « Approuver la révision 2 »), décision en ≤ 2 clics sans changer de page.
- C2 : 0 UUID par défaut ; commit, portées et identifiants seulement dans « Détails techniques » repliés.
- C3 : 3 blocs majeurs (héros, file, contexte) + nav à 6 entrées ; point de couleur unique par carte, zéro menu par ligne.
- C4 : un seul `connection-status` (pastille sidebar), aucun autre état de santé affiché.
