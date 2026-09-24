# DEC-0101 — Enregistrement Agent exposé via MCP

Statut : proposed (serveur : DEC-0113).
Tâche : `[MCP] Exposer enregistrement agent via outil MCP` (`bb964309`).

## Contexte

`POST /api/v1/agents` enregistre une identité Agent de provenance pour la
machine authentifiée (`machine_id` dérivé du principal, DEC-0035). Le contrat
MCP déclarait l'enregistrement HTTP-only (CC-1/DEC-0045) : aucun outil
`studio_register_agent` n'existait, un consommateur purement MCP devait
matérialiser son Agent via HTTP.

## Décision

Exposer un nouvel outil `studio_register_agent`, additif (CC-3) :

- handler mince : `parse/entree -> Principal -> agents.create_agent`
  (service commun HTTP/MCP, DEC-0005), jamais de logique réimplémentée ;
- `machine_id` dérivé du principal, jamais fourni (DEC-0035) ;
- `ensure_can_write(principal, "agent")` avant le court-circuit
  d'idempotence (DEC-0036) ;
- `Idempotency-Key` sous le namespace `MCP studio_register_agent`,
  distinct de `POST /agents` (DEC-0024/DEC-0027) ;
- ne confère aucun droit (CC-1) ; `display_name` requis, métadonnées
  d'observabilité optionnelles (UC-5).

## Contrats

- `TECH/07_MCP_CONTRACT.md` : section Enregistrement d'Agent mise à jour,
  pas de bump de version (outil nouveau = additif).
- Description `studio_log_ai_work` : mention HTTP-only retirée.

## Conséquences

Tout agent MCP peut s'enregistrer sans détour HTTP. Le garde-fou
anti-impersonation reste intégral : même service, même ownership
(`actor_not_owned` côté ai-work), même autorisation.
