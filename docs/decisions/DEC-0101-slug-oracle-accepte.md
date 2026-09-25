---
id: DEC-0101
title: 'Oracle slug projet accepté : slugs non secrets, 409 conflict structuré'
status: proposed
date: '2026-09-25'
superseded_by: null
server_decision_id: 52e447d4-6af3-456f-ab91-231ba1eae8c2
server_readable_id: DEC-0118
source: task 81307c39 (résiduel 4e7351d0, registre fail-closed)
---

# DEC-0101 — Oracle d'existence de slug projet : accepté, slugs non secrets

## Problème

Un utilisateur avec un rôle de provisioning (`admin`/`developer`) mais sans
membership sur un projet apprend qu'un slug existe : `apply` d'initialisation
par slug → `409`, de même que `POST /projects` (slug unique global). Côté MCP,
l'échec remontait en `error_code` générique `error` (détail HTTP en chaîne
brute, non structurée) au lieu d'au moins `conflict`.

## Options comparées

| Option | Sécurité | Coût | Verdict |
|---|---|---|---|
| Accepter l'oracle (slug non secret) | Oracle limité aux rôles de provisioning ; aucun id fuit (pas de `pid`/task/session dans la réponse) | Fix structuré + verdicts resserrés | **Retenue** |
| Supprimer l'oracle (slugs par propriétaire/espace, réponse indistinguable) | Aucune fuite d'existence | Migration schéma (unicité globale → scopée), `object_key` construit sur `project_slug`, previews/registres à revoir | Reportée : disproportionnée pour un résiduel A0, style GitHub (noms non secrets) |

## Décision

1. Les slugs projet sont **non secrets**. L'oracle d'existence via `409` est
   accepté et documenté dans les matrices (`slug`).
2. `create_project` (point commun `POST /projects` + initialisation HTTP/MCP)
   répond `409 {"detail": {"error_code": "conflict", "message", "slug"}}` —
   jamais le générique MCP `error`, jamais d'id du monde dans la réponse.
3. La preview reste non révélante : pour un outsider, `project_id_for_slug`
   (via `list_projects` filtré) ne voit pas le projet et planifie `create`.
4. Les rôles sans provisioning (`agent`, `readonly`) restent exclus de la
   création (`ensure_can_provision` / `require_roles`) : l'oracle ne leur est
   pas accessible.

## Conséquences

- `services/api/src/studio_api/services/projects.py` : détail 409 structuré.
- `tests/api/test_access_registry.py` : verdict `slug` exige
  `error_code == "conflict"` sur l'apply, `create` sur la preview, sans fuite.
- `tests/mcp/test_access_registry.py` : verdict `slug` exige
  `error_code == "conflict"` sur l'apply.
- `tests/api/test_provisioning.py` : le doublon de slug assert le code
  `conflict`.
- Contrats : additif (nouveau `error_code` documenté), pas de bosse de version.
