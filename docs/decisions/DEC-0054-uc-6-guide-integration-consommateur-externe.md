---
id: DEC-0054
title: 'UC-6 : guide dintegration dun consommateur externe, sans connaissance interne'
status: active
date: '2026-09-15'
superseded_by: null
source: docs/DECISIONS.md
---

# DEC-0054 — UC-6 : guide d'integration externe

Repond au critere d'acceptation « le parcours UC-6 est executable par un
tiers sans aide interne » et a l'ecart releve par l'audit du 2026-09-15 :
`00_README.md` n'offrait aucune page d'accueil externe et ses parcours
supposaient le contexte d'un outillage interne (desormais corrige par UC-4).

### Decision

1. Nouvelle page d'entree pour un developpeur tiers :
   `docs/Studio_OS_Documentation_Pack/studio_os_docs/INTEGRATION/00_EXTERNAL_CONSUMER_GUIDE.md`.
   Elle decrit le parcours complet de zero au premier transfert : choix du
   transport, authentification (token machine + provisioning hors-bande),
   permissions, decouverte des capacites (`/openapi.json`, `tools/list`),
   taches, events, worklogs, sync offline, temps reel (SSE), transferts
   (single-PUT et multipart, octets jamais via l'API), erreurs, memoire
   locale optionnelle, versions/evolution.
2. Le guide ne suppose aucun savoir de harness/provider/modele/profil :
   il pointe vers les contrats `TECH/02-09` et le Universal Consumer Contract
   comme sources normatives, et rappelle qu'aucun registre de produits
   supportes n'existe.
3. `00_README.md` route explicitement ce public (« Pour un consommateur
   externe »), et `README.md` y renvoie depuis la presentation du depot.
4. Le guide est valide par le test de conformance UC-7 (DEC-0055) : chaque
   etape decrite est executee par un client fictif sans connaissance interne.

### Consequences

- Un developpeur tiers dispose d'un point d'entree unique, model-agnostic,
  relie aux contrats existants plutot qu'a une copie qui pourrait diverger.
- La mediation humaine du provisioning initial (CLI serveur admin) est
  documentee comme choix de conception, pas comme couplage.
- Aucun code ni contrat modifie.

### Compatibilite

Documentation seule ; ne modifie aucun contrat versionne. Complete UC-4
(terminologie) et s'appuie sur UC-3 (memoire locale) et CC-3 (evolution MCP).
