---
title: "AIB P9 — Credential éphémère de lancement"
status: proposed
server_decision_id: 3bc0add6-01cc-45fe-afbd-545d2e5cd347
server_readable_id: DEC-0182
---

# AIB P9 — Credential éphémère de lancement

## Current

Le harnais lancé par le daemon recevait le token machine durable (entrée MCP et
`STUDIO_CLIENT_MACHINE_TOKEN`) : une fuite ou un hook de projet hostile
donnait un accès durable à toute la portée de la machine.

## Options

1. Garder le token durable et isoler seulement les hooks : rejeté, le secret reste durable.
2. Credential éphémère lié au lancement, allowlist REST/MCP, portée projet : recommandé.

## Proposition

- `POST /api/v1/task-launches/{id}/credential` (machine cible, token durable, lancement
  `accepted|preparing|running`) renvoie `TaskLaunchCredential` (`token`, `expires_at`) ;
  une réémission révoque le précédent.
- Table `launch_credentials` (migration `0027`) : hash SHA-256, `launch_id`, `machine_id`,
  `project_id`, `task_id`, `expires_at` ≤ celui du lancement, `revoked_at`.
- Valide tant que non révoqué, non expiré, lancement non terminal, machine et propriétaire
  actifs. `project_scope` réduit au projet du lancement. Hors allowlist :
  `403 launch_credential_scope`.
- Changement additif (nouvel endpoint, modèle, table, code d'erreur). Contrats mis à jour :
  TECH/02, 04, 05, 07.
- Limites : portée tâche/session non vérifiée appel par appel ; pas de `DELETE` hors
  réémission ; harnais Codex non vérifié.
