---
id: DEC-0046
title: 'HTTP canonical complet, MCP subset additif : surface parity non requise, enforcement
  parity requise'
status: active
date: '2026-09-15'
superseded_by: null
source: docs/DECISIONS.md
sync_hash: sha256:005718f137eb8099c80f6a5a83e627714cc5d149916c67b43cb9a3a1720ac30b
---

# DEC-0046 — HTTP canonical complet, MCP subset additif : surface parity non requise, enforcement parity requise

L'audit pre-UC-2 a etabli qu'aucun contrat ne promet une parite de surface
HTTP/MCP : les trois occurrences de « parite » (TECH/04 §159-168, TECH/02
§76-82, DEC-0045) signifient toutes l'enforcement des memes regles sur les
deux chemins, jamais une couverture 1:1. DEC-0024 §7 (Bloc B n'ecrit jamais
via MCP, rejeu exclusivement HTTP), DEC-0005 (MCP couche mince sur les
services), DEC-0027 (sous-ensemble d'outils, espaces separes) et TECH/07
(inventaire 25/29, charges non versionnees) decrivent deja un MCP partiel
par construction. Cette decision fige la regle pour UC-2 et la suite.

### Decision

1. HTTP est l'interface publique canonique et complete de Studi'OS
   (`TECH/02_API_CONTRACT.md`, base `/api/v1`).
2. MCP est une interface additive orientee agents exposant un sous-ensemble
   decouvrable des capacites (`TECH/07_MCP_CONTRACT.md`).
3. La parite de surface HTTP/MCP n'est pas requise, sauf si un contrat
   specifique l'exige explicitement.
4. La parite d'enforcement reste requise des qu'une meme operation metier
   est accessible par plusieurs transports : authz, ownership, provenance
   et validation metier vivent dans les services partages (`services/`),
   jamais dupliques entre routers HTTP et handlers MCP (DEC-0036, DEC-0005).
5. Les consommateurs MUST decouvrir les capacites par transport — OpenAPI
   pour HTTP, `tools/list` du protocole MCP pour MCP — et MUST NOT deduire
   de l'absence d'un outil MCP que la capacite sous-jacente est
   indisponible : elle signifie uniquement « non exposee via ce
   transport ». Aucun endpoint `/capabilities` ni manifeste n'est cree par
   cette decision.

### Distinction preservee : les 4 outils memoire/graphe

« Non requis pour la parite de transport » ne signifie pas « non requis
par la roadmap produit ». La necessite des 4 outils MCP memoire/graphe
differes (`studio_memory_search`, `studio_memory_read`,
`studio_graph_query`, `studio_generate_context_package`) a ete tranchee
par UC-3/DEC-0047 : les 3 premiers specifies en local-only read-only
(roadmap 8.3a), le 4eme DEFERRED avec condition (roadmap 8.3b).

### Amendement UC-3/DEC-0047 : categorie local-only (additif)

Les regles 1-5 ci-dessus regissent les *instance capabilities* (etat
partage du VPS) et restent inchangees. S'y ajoute une seconde categorie :

6. Les *local-only capabilities* (donnees volontairement confinees au
   poste, ex. Memory/Knowledge UC-3 — DEC-0047) peuvent etre exposees via
   une interface locale standard (MCP local, stdio) sans endpoint HTTP
   VPS correspondant. L'absence d'un endpoint HTTP pour une capacite
   explicitement local-only ne constitue pas une violation de la regle 1.
7. Regle miroir de decouverte : de meme que l'absence d'un outil MCP ne
   signifie pas l'indisponibilite de la capacite, l'absence d'un
   endpoint HTTP ne signifie pas l'inexistence d'une capacite local-only.
   Chaque interface/processus se decouvre par son propre mecanisme
   (`tools/list` du processus local concerné).
8. La parite d'enforcement (regle 4) est sans objet quand aucun etat
   partage n'est touche : une capacite read-only purement locale
   n'appelle ni authz serveur, ni ownership, ni validation metier
   partagee.

### Follow-ups traces, non implementes

- `studio_register_agent` : MAY, amelioration MCP optionnelle. Son absence
  n'empeche ni CC-1 CLOSED ni UC-1 DONE (`POST /api/v1/agents` est le
  chemin canonique, TECH/07 §Enregistrement d'Agent).
- `studio-client.create_agent` : follow-up d'integration/UC-7 (methode
  cliente miroir, non requise pour la parite).
- `POST /ai-work.machine_id` : gap adjacent a trancher par decision
  separee — le client HTTP fournit `machine_id` alors que `POST /agents`,
  `POST /events` et le handler MCP `studio_log_ai_work` derivent la
  machine authentifiee. Comportement futur non decide ici.

### Consequences

- Aucune modification de TECH/02-05, aucun changement runtime, aucune
  migration : clarification architecturale uniquement.
- UC-2 se construit sur OpenAPI + `tools/list`, sans manifeste
  supplementaire sauf lacune prouvee (CC-2 deja cadre ainsi).

### Compatibilite avec les DEC existantes

Precise DEC-0023/0024/0027/0005 sans les contredire ; operationalise le
principe 2 du Universal Consumer Contract (DEC-0043 amendee) pour la
decouverte ; compatible DEC-0045 (CC-1 reste le chemin canonique
d'enregistrement).
