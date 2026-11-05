---
kind: rule
stable_key: memory
scope: studio
description: "Mémoire : état projet dans Studio OS ; savoir durable dans le vault Studio OS du projet en cours (scope project), conventions communes dans le vault studio ; jamais de doublon."
---

# Mémoire

| Fait | Où |
|---|---|
| État : tâches, avancement, coordination | Studio OS (`studio_update_task`, `studio_handoff`…) |
| Décision d'architecture ou de contrat | `studio_add_decision` (pas une note) |
| Savoir durable du projet en cours : piège, recette, convention, leçon | vault Studio OS, `scope="project"`, `project_id` de la session |
| Convention commune à tous les projets du studio | vault Studio OS, `scope="studio"` |
| Préférence personnelle hors projet | mémoire native du harnais si elle existe, sinon rien |

- `project_id` : celui annoncé au démarrage (`session-start`, `studio_start_work`) ; jamais celui d'un autre projet.
- Lire avant de toucher une zone : `studio_vault_search(project_id, path=[fichiers visés])` ou `task_id`, `q` en complément ; `studio_vault_read` seulement sur les notes retenues. Jamais de chargement intégral.
- Écrire : rechercher d'abord ; note existante → réécriture (`note_id` + `expected_version`) ; sinon `studio_vault_write(scope, project_id, slug, title, summary, body, note_type, anchors, idempotency_key)`.
  - `note_type` : `lesson`, `procedure`, `convention`, `reference`, `rule` ou `note` ;
  - `anchors` : `path:<chemin relatif>` (dossier terminé par `/`) et/ou `task:<uuid>`, pour que la note remonte quand la zone est retouchée ;
  - slug en minuscules (`zone/sujet`), une note par fait.
- Une note naît `proposed` : validation, remplacement et archivage restent humains.
- Jamais dans le vault : secret (refusé), état de tâche, copie d'une décision ou de la doc du dépôt.
- Projet non suivi par Studio OS : pas de vault ; savoir durable dans la doc du dépôt, sur accord.
- Fin de tâche : un fait durable appris → une note ; sinon rien.
