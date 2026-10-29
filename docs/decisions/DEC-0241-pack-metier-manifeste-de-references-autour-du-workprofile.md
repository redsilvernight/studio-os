---
id: DEC-0241
title: 'Pack métier : manifeste de références autour du WorkProfile existant'
status: accepted
date: '2026-10-25'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0241 — Pack métier : manifeste de références autour du WorkProfile existant

Proposition locale pour la demande d'adaptation. Réutiliser WorkProfile (DEC-0198), pas model_profile et pas un nouveau LibraryKind. Un manifeste studio.work-profile-pack/v1 contient le WorkProfile, une base studio UUID/version et les adaptations UUID/version explicitement déclarées ; aucun texte de bibliothèque, contenu métier, commande ou autorisation supplémentaire. Un import de fichier signifie validation et preview en lecture seule : les références doivent déjà exister et être visibles, la composition effective du resolver commun doit correspondre exactement, les permissions restent intersectées avec MachinePolicy et le résultat non autoritaire. Aucun import ne publie ni n'active de définition. Formats inconnus ou références incompatibles refusés explicitement. Publication future hors périmètre de cette unité.
