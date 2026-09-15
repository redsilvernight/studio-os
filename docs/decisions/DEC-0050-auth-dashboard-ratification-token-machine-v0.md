---
id: DEC-0050
title: 'Question ouverte n°3 (etape 8) : auth dashboard V0 ratifiee, token machine reutilise, aucune nouvelle mecanique'
status: superseded
date: '2026-09-15'
superseded_by: DEC-0056
source: docs/DECISIONS.md
---

# DEC-0050 — Question ouverte n°3 (etape 8) : auth dashboard V0 ratifiee, token machine reutilise, aucune nouvelle mecanique

> **Supersede par DEC-0056.** L'authentification humaine dashboard avec JWT
> (`POST /auth/token`, machine dashboard dediee, `User.password_hash`) et le
> deploiement du dashboard via `docker/dashboard.Dockerfile` remplacent la
> ratification V0 "token machine colle manuellement, dashboard servi
> localement". Les points de contexte historiques ci-dessous sont conserves
> pour la tracabilite.

Question ouverte n°3 de `docs/ROADMAP_STEP8_BREAKDOWN.md`, etudiee avant
implementation de la sous-etape 8.5 et de DASH-3 (meme convention que
DEC-0041 : question de conception non triviale Cloud/Core <-> client
tranchee avant le code).

### Probleme

`TECH/04_AUTH_SYNC_CONTRACT.md` ne connait qu'une seule identite HTTP :
`Authorization: Bearer <token machine>`, hash serveur, sans session
utilisateur, cookie, CSRF ni OAuth. Aucune notion d'utilisateur connecte
independante d'une machine n'existe dans le contrat — l'identite
utilisateur est toujours derivee de `Machine.owner_user_id` (DEC-0012).

Le dashboard (`dashboard/`, DASH-0 a DASH-2 deja livres) a deja fait un
choix de facto sans ADR formel : un champ dans l'en-tete ou l'humain colle
manuellement un Bearer token machine, garde en memoire JS uniquement
(`dashboard/src/auth.ts`), jamais `localStorage`/cookie/log ; envoye sur
chaque appel `/api/v1` et sur `GET /events/stream` via `fetch()` +
`ReadableStream` plutot que l'`EventSource` natif (qui ne peut pas porter
de header `Authorization`) ; `GET /healthz` reste anonyme ; **Clear**
retire le token de la session page (la revocation reelle reste
`POST /machines/{id}/revoke`, admin). Documente cote produit dans
`dashboard/README.md` ("Token usage (auth V0)"), jamais cote decisions.

`HUMAN/04_DEPLOIEMENT_OVH.md` decrit par ailleurs un conteneur
`studio-dashboard` et un routage `studio.example.com -> dashboard/API` :
aucune trace de l'un ou l'autre dans `docker/docker-compose.yml` ou
`docker/Caddyfile` reels (services declares : `caddy`, `api`, `mcp`,
`postgres`, `minio`, `minio-init`). Cette derive documentaire preexiste a
ce lot.

DASH-3 ajoute uniquement la reconnexion/reprise SSE (backoff, watchdog,
refetch) sur un transport d'authentification deja en place — aucune
nouvelle surface d'authentification n'est necessaire pour ce travail.

### Decision

1. **Ratifier l'existant tel quel, sans nouveau code d'authentification.**
   Le dashboard V0 reste un outil local/admin : Bearer machine colle
   manuellement, memoire uniquement, aucune persistance navigateur,
   `fetch()`+`ReadableStream` pour porter le header sur le flux SSE (seule
   facon de respecter `TECH/04` avec un `EventSource` natif qui ne peut pas
   transporter `Authorization`). Aucune session utilisateur, aucun cookie,
   aucun CORS ajoute.
2. **Le dashboard reste servi localement** (poste de developpement, pas un
   service expose sur le VPS) pour cette phase — coherent avec
   `IMPLEMENTATION/02_BLOCK_A_PROMPT.md` qui interdit au Bloc A de
   construire le dashboard et `03_BLOCK_B_PROMPT.md` qui l'attribue au
   Bloc B. Un dashboard servi depuis le VPS exigerait une authentification
   utilisateur entierement nouvelle (extension majeure de
   `TECH/04_AUTH_SYNC_CONTRACT.md`) — hors perimetre de l'etape 8.
3. **Faiblesse connue explicitement assumee, pas corrigee ici** : un
   Bearer permanent garde en memoire d'un onglet navigateur est une
   surface d'attaque XSS/inspection locale acceptable pour un outil
   admin/local derriere HTTPS, pas pour une exposition multi-utilisateur
   (meme frontiere de confiance que DEC-0012). Si le dashboard devait un
   jour etre expose publiquement, ce choix serait a revisiter en meme
   temps qu'une vraie authentification utilisateur (voir DEC-0051, question
   n°4, meme prerequis manquant).
4. **Derive documentaire signalee, non corrigee dans ce lot** : le
   conteneur `studio-dashboard` et le routage `studio.example.com` de
   `HUMAN/04_DEPLOIEMENT_OVH.md` ne correspondent a aucun etat reel du
   depot. A traiter dans un lot de reconciliation documentaire dedie
   (etape 10 de `ROADMAP_CORRECTIONS_AUDIT.md`), pas ici.
5. **DASH-3 peut proceder sans aucun changement d'authentification** : la
   reconnexion SSE reutilise le meme header `Authorization` deja envoye
   par `connectEventStream()`, juste rejoue apres coupure avec
   `Last-Event-ID` pour la reprise (DEC-0018).

### Consequences

- Aucun contrat (`TECH/02/03/04/05`) modifie par cette decision.
- Aucun fichier de code modifie par cet ADR seul — c'est une ratification
  documentaire d'un choix deja en production dans `dashboard/src/auth.ts`
  et `dashboard/README.md`.
- Une vraie authentification utilisateur (session, login, JWT ou
  equivalent) reste une extension future explicitement differee, pas
  abandonnee — condition prealable commune a une exposition VPS du
  dashboard et a une entite `Notification` persistee avec etat lu/non-lu
  (DEC-0051).
- Limite assumee : un token machine partage entre plusieurs onglets/postes
  d'un meme developpeur n'a pas de notion de "qui" au-dela de la machine —
  aucune tentative de derive vers un pseudo-multi-utilisateur n'est faite
  ici.

### Preuves

Aucun test ajoute (ADR de ratification, zero changement de comportement
observable). Verification : lecture directe de `dashboard/src/auth.ts`,
`dashboard/src/sse.ts`, `dashboard/README.md` (section "Token usage
(auth V0)"), `TECH/04_AUTH_SYNC_CONTRACT.md`, `docker/docker-compose.yml`,
`docker/Caddyfile`, `HUMAN/04_DEPLOIEMENT_OVH.md` — confirment l'etat
decrit ci-dessus, aucune divergence entre ce texte et le code/doc
existants au moment de l'ecriture.

Fichiers modifies : aucun (hors cet ADR). Fichiers a reconcilier plus tard
(hors perimetre) : `HUMAN/04_DEPLOIEMENT_OVH.md`.
