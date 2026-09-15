---
id: DEC-0045
title: 'CC-1 : enregistrement public dAgent (POST /agents) comme identite de provenance, sans autorite'
status: active
date: '2026-09-15'
superseded_by: null
source: docs/DECISIONS.md
---

# DEC-0045 — CC-1 : enregistrement public d'Agent

L'audit UC-1 a demontre une contradiction entre le Universal Consumer
Contract (`docs/UNIVERSAL_CONSUMER_CONTRACT.md`) et le runtime : produire un
worklog est une capacite MUST, `AIWorkLog.agent_id` est obligatoire avec FK
non-nulle, mais aucune interface publique ne permettait a un consommateur
inconnu de materialiser la ligne `Agent` requise (`POST /ai-work` sans ligne
valide -> `500` par violation FK). Cette decision tranche CC-1 en appliquant
le principe 1 du contrat : l'enregistrement est public, model-agnostic, non
whiteliste, et strictement sans autorite.

## Amendement — UC-5 (2026-09-15)

DEC-0050 operationalise les champs structures de DEC-0043 amendee et amende
explicitement le point 1 ci-dessous : `Agent`/`AgentCreate` portent desormais
`agent_profile`, `harness`, `provider`, `model`, chaines ouvertes optionnelles.
L'affirmation « Aucun champ harness/provider/model/profil » du point 1 et la
consequence « Aucune migration DB (table `agents` inchangee) » sont donc
remplacees : la table `agents` gagne quatre colonnes nullables (migration
reversible `0006_agent_runtime_metadata`). Le principe de DEC-0045 reste
inchange — enregistrement public, sans autorite, `agent_kind` conserve ; aucun
de ces champs n'entre dans une decision d'autorisation ou de capacite.

### Decision

1. Nouvel endpoint additif `POST /api/v1/agents` (contrat
   `AgentCreate{display_name requis, agent_kind optionnel chaine libre}` —
   `packages/studio-contracts/src/studio_contracts/auth.py`, doc
   `TECH/02_API_CONTRACT.md`). Aucun champ harness/provider/model/profil,
   aucune capability flag, aucun enum ferme.
2. `machine_id` derive de la machine authentifiee (regle DEC-0035), jamais
   fourni par le client. L'`id` genere serveur est la seule identite
   canonique ; `display_name`/`agent_kind` sont des metadonnees, jamais des
   cles d'autorisation.
3. Idempotence par l'infrastructure existante (`Idempotency-Key`, endpoint
   `"POST /agents"`, `services/idempotency.py::run_idempotent`) — aucun
   nouveau mecanisme.
4. Autorisation par les primitives existantes (`ensure_can_write` avant le
   court-circuit d'idempotence, DEC-0036) : ecrivains OK, `readonly` ->
   `403 forbidden`. Aucun RBAC specifique, aucun droit conferé.
5. Durcissement documente, meme categorie que DEC-0025/DEC-0036 (pas un
   bump de version) : `POST /ai-work` exige un `agent_id` attache a la
   machine authentifiee, sinon `409 actor_not_owned` — la regle DEC-0035
   `actor_type=agent` appliquee au service, donc paritaire HTTP/MCP.
   Avant : ligne inexistante -> `500`, ligne etrangere -> `201` silencieux.
   Comportement inchange pour les appelants n'utilisant que leurs propres
   agents.

### Consequences

- UC-1 est satisfiable en entier sans connaissance harness/provider/model/
  profil : le chemin sans `Agent` couvre tout sauf les worklogs, et tout
  consommateur autorise peut materialiser son `Agent` publiquement.
- Aucune migration DB (table `agents` inchangee), aucun enum, aucun mock
  Bloc B a mettre a jour (aucun mock de cet endpoint n'existait).
- `studio_log_ai_work` (MCP) herite du durcissement sans modification :
  couche mince sur le meme service ; son `invalid_reference` pour agent
  inconnu devient `actor_not_owned`.

### Compatibilite avec les DEC existantes

Additif au sens des regles contracts : nouvel endpoint + nouveau champ
optionnel (`agent_kind` a defaut), ignorables par les anciens clients.
Compatible DEC-0003/0011/0012 (auth/provisioning inchanges), DEC-0023
(parite HTTP/MCP par le service), DEC-0035 (regle etendue, pas contredite),
DEC-0036 (primitives reutilisees), DEC-0041 (revue inchangee), DEC-0043
amendee (principe 1 operationalise : l'enregistrement reste disponible a
tout consommateur autorise, independant de harness/provider/model/profil).
