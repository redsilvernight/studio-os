---
id: DEC-0103
title: 'Isolation projet minimale : membership User→Project, rôle = quoi, membership = où'
status: accepted
date: '2026-09-24'
superseded_by: null
server_decision_id: eb2670d0-2598-4b9c-80fb-892ecced3da4
server_readable_id: DEC-0123
server_replaces: 19922554-bcd8-498f-9a14-7dab87916bf2 (DEC-0103 serveur, superseded ; citait l'ancien fichier DEC-0100) ; d31c16ea-06f1-481c-a701-7c06845dd426 (DEC-0097 serveur, superseded ; collisionnait avec l'ADR du dépôt DEC-0097)
source: docs/DU0_AUTH_PROJECT_DATA_AUDIT.md
---

# DEC-0103 — Isolation projet minimale : membership User→Project

Gate DU-0 de la roadmap « Desktop Distribution, Updates & Public Registration »
(tâche `d0e23fe3`). Préalable à toute inscription publique. Acceptée (serveur DEC-0103), non
implémentée. Classement contractuel : `contract-guardian` (2026-09-24).

## Problème

`docs/DU0_AUTH_PROJECT_DATA_AUDIT.md` prouve qu'aucune ACL projet n'existe :
toute machine authentifiée lit (et, selon son rôle, écrit) les données de tous
les projets par HTTP, SSE et MCP, `studio_prepare_context` compris. C'est
contractuel : DEC-0036 (« sans nouvelle table », limite reportée l.143-146),
DEC-0063 l.20-22, `TECH/04` l.147 et l.159. Avec une inscription publique, un
compte valide obtiendrait donc un accès automatique à tous les projets.

## Options comparées

| Option | Sécurité | BDD | Surfaces | Inscription publique | Verdict |
|---|---|---|---|---|---|
| Rôle global `none/pending` | Tout-ou-rien : dès qu'on l'active, le compte voit tout | colonne | un seul test de rôle | Ne sépare pas deux utilisateurs actifs | Rejetée |
| Ownership simple (`Project.owner_user_id`) | Un seul utilisateur par projet | colonne | simple | Impossible de partager un projet à deux | Rejetée |
| **ProjectMembership binaire** | Refus par défaut, partage explicite | 1 table | un point canonique | Compte actif avec 0 projet | **Retenue** |
| ACL projet avec niveaux par projet | Fine | table + niveaux | matrice rôle × niveau partout | Surdimensionné | Reportée (colonne additive possible plus tard) |
| Invitation/approbation seule | Pas de relation persistante à contrôler | tokens | ne filtre rien | Mécanisme d'attribution, pas d'isolation | Complément ultérieur |

## Décision

1. **Modèle.** Le `ROLE` global (`admin|developer|agent|readonly`) dit ce que
   le principal peut faire. La `MEMBERSHIP` dit où. Table
   `project_memberships(project_id, user_id, granted_by_user_id, created_at)`,
   clé primaire `(project_id, user_id)`, suppression en cascade avec le projet
   ou l'utilisateur. Pas de niveau par projet en V1. Limite assumée : un
   utilisateur a le même rôle sur tous ses projets. `granted_by_user_id` est
   nullable uniquement pour le backfill système identifié par la migration ;
   toute attribution applicative conserve l'admin qui l'a accordée.
2. **Identité porteuse : le User.**
   - Une `Machine` hérite des memberships de son propriétaire
     (`owner_user_id`, non nullable, DEC-0012). Une machine sans propriétaire
     n'existe pas.
   - Un `Agent` reste une provenance sans autorité (DEC-0045). Il opère via
     la machine qui l'a enregistré et n'a jamais de membership propre.
   - Le daemon ou l'automatisation locale utilise le token machine de son
     propriétaire, donc les mêmes droits.
   - Les chemins serveur de confiance (webhook GitHub, Producer,
     `resource.conflict`) ne passent pas par un Principal. Ils restent
     exemptés explicitement.
   - Un User de rôle `agent` (bot) suit la règle commune : il faut lui
     attribuer une membership.
3. **Admin.** Il a une portée globale et contourne le contrôle des
   memberships. Il reçoit quand même une membership quand il crée un projet,
   pour que ses accès restent cohérents s'il est rétrogradé.
4. **Compte sans accès.** L'état du compte (`pending|active|disabled`,
   `email_verified_at`, `disabled_at` ; voir la décision Inscription et l'étape A3) est
   orthogonal à l'accès projet. Un compte ACTIVE et VERIFIED avec 0 membership
   est valide.
   - Il voit seulement ses propres ressources : profil, machines, agents,
     runtimes, Library User et transferts dont il est émetteur ou
     destinataire.
   - Les données partagées sans projet (décisions globales, Library et
     bindings Studio, transferts sans projet) sont lisibles uniquement par
     l'admin ou par un User qui a au moins une membership.
5. **Création de projet.** `projects_service.create_project` est le point
   commun de `POST /projects` et de l'initialisation (HTTP et MCP). Il insère
   la membership du créateur (`principal.user`) dans la même transaction. Un
   agent crée donc au nom du propriétaire de sa machine, et le rôle `agent`
   n'a pas le droit de provisionner (inchangé). Le `commit()` interne actuel
   doit être remplacé par un flush afin que projet et membership soient
   réellement atomiques sous la transaction appelante.
6. **Attribution d'accès en V1 : option A, par l'admin seulement.**
   - `GET/PUT/DELETE /api/v1/projects/{id}/members` (additif, admin).
   - `studio-admin project grant/revoke` pour le bootstrap et les bots.
   - Écran Dashboard « Membres ».
   - Aucune auto-attribution. L'invitation reste une extension ultérieure.
7. **Collections.** Filtrage silencieux aux projets accessibles, sans compter
   les éléments invisibles.
   - `?project_id=` non accessible **ou** inexistant : `403`, pour ne pas
     créer d'oracle d'existence.
   - `GET /projects` renvoie uniquement les projets accessibles.
8. **Accès par UUID.** Une ressource dont le projet est inaccessible, qu'on
   y accède directement ou via son parent (`task`, `roadmap`, `build`,
   `session`→task, version Library→définition), reçoit
   `403 {"detail":{"error_code":"forbidden","resource":"project",
   "action":"read|write"}}`, conforme à l'enveloppe TECH/02.
   On garde la règle « pas de 404 de confidentialité » (DEC-0036, `TECH/04`),
   pour trois raisons : UUID v4, aucune recherche par slug, et des listes déjà
   filtrées. Les `404` non-oracles existants (Library User, résolution) sont
   évalués **après** le contrôle projet.
9. **SSE.**
   - `403` avant l'ouverture du flux.
   - Ajout d'un keep-alive périodique (additif). À chaque keep-alive ou
     événement, la membership est revalidée (TTL de 30 s au plus).
   - Un signal strictement interne, non persisté dans le journal Event, est
     émis à la suppression d'une membership.
   - Le flux est fermé si l'accès est retiré.
   - `GET /events` sans filtre est limité aux projets accessibles.
10. **MCP.** Mêmes gardes dans les services partagés (DEC-0046 §4). `run_tool`
    injecte déjà le `Principal`. `studio_prepare_context`,
    `studio_discover_definitions` et `studio_resolve_agent` vérifient l'accès
    au projet **avant** toute lecture. Aucun outil `_v2`. Refus MCP :
    `{error_code:"forbidden", resource:"project", ...}` dans l'enveloppe
    plate TECH/07 l.90 ; le `not_found` inter-projet actuel (TECH/07
    l.305-307) est remplacé.
11. **Composition (ET logique, jamais OU).** Transfer
    (émetteur/destinataire/diffusion/admin), Library User (propriétaire/admin,
    404), Runtime (privé à l'utilisateur) et bindings User restent inchangés,
    et s'ajoutent à l'accès projet quand la ressource a un projet.
    - Une diffusion rattachée à un projet n'est visible que des membres.
    - Un lock ou un binding Project qui pointe vers une ressource Studio suit
      l'accès au projet.
    - Une membership ne donne jamais accès aux ressources globales d'un
      co-membre. `GET /machines` et `GET /agents` deviennent self/admin
      (aujourd'hui ouverts à toute machine authentifiée, DEC-0082 : rupture
      couverte par la version 2).
    - Une session n'est visible que par son lien direct
      `session -> task -> project`. L'activité d'équipe est filtrée par le
      `project_id` propre de chaque enregistrement, jamais par le propriétaire
      d'une machine ni par une fermeture transitive de co-memberships.
    - « Co-membre » signifie uniquement deux lignes directes portant le même
      `project_id`; ce fait ne se propage à aucun autre projet ou utilisateur.
12. **Point d'autorisation canonique.**
    - `Principal` porte `project_scope`, chargé une fois par requête :
      `ALL` pour l'admin, sinon un ensemble d'identifiants.
    - Primitives : `ensure_project_access(principal, project_id, action)`,
      `project_visibility_clause(principal, column)` (sur le modèle de
      `transfer_visibility_clause`) et une résolution parent→projet.
    - Les services de lecture reçoivent le `Principal`. Aucune décision
      d'autorisation dans les routers ni dans les handlers MCP.
    - Le contrôle projet passe **avant** le court-circuit d'idempotence et la
      déduplication `event_id`.
    - Un test d'inventaire fail-closed énumère toutes les routes FastAPI et
      tous les outils MCP. La CI échoue si l'un d'eux n'est pas classé
      `project|instance|own|public`. La matrice « outsider » est générée à
      partir de ce registre.
13. **Migration.**
    - Un préflight bloquant vérifie que chaque Machine possède un owner valide,
      classe les Users historiques, signale les comptes sans machine active et
      interdit tout orphelin. Le rapport et l'ensemble exact des couples
      générés sont archivés pour rendre le backfill déterministe et auditable.
    - Le backfill donne une membership sur chaque projet existant à chaque
      User existant (tous rôles). Personne ne perd d'accès, et le Dashboard
      et le MCP continuent de fonctionner. La provenance est le système de
      migration (`granted_by_user_id = NULL`), jamais un admin choisi
      arbitrairement.
    - Après la migration, un nouvel utilisateur ou un compte public commence
      avec 0 membership. Un nouveau projet ne compte que son créateur : le
      coéquipier est ajouté explicitement.
    - La migration est réversible (le downgrade supprime la table). Aucun
      feature flag d'enforcement n'est prévu : le backfill rend l'activation
      neutre.
14. **Version.** Le changement est une rupture sémantique pour des
    consommateurs réels (CLI, Dashboard, MCP). L'exemption de DEC-0025 ne
    s'applique donc pas : `API_CONTRACT_VERSION` passe à 2, avec le préfixe
    de transport `/api/v1` conservé. La version contractuelle est exposée par
    le metadata de compatibilité et négociée fail-closed ; aucune base
    `/api/v2` parallèle n'est créée. L'enveloppe d'événement est inchangée.

## Conséquences contractuelles

- `TECH/04` (RUPTURE) : réécrire l.147, l.159, l.161-162 et l.181-189, et
  compléter l.218-228.
- `TECH/02` (RUPTURE) : l.14, l.26-29 et SSE l.547-551. Routes `members`
  additives. `GET /machines` et `GET /agents` restreints à self/admin.
  Retirer « Reads stay fully available » de l'OpenAPI.
- `TECH/05` (ADDITIF) : entité `ProjectMembership` et règles de lecture des
  `project_id` nullables.
- `TECH/07` (RUPTURE sémantique, schémas inchangés) : l.305-307, pour
  `prepare_context` et les lectures de l'audit.
- `TECH/03` (NEUTRE) : note sur les règles de lecture du polling et du SSE.
- Le lot d'implémentation met à jour simultanément contrats/schémas partagés,
  OpenAPI, fixtures et mocks des deux Blocs ; aucun drift temporaire n'est
  autorisé.

## Décisions touchées

- DEC-0036 : AMEND. Rôle, ownership, Transfer et ordre avant l'idempotence
  sont conservés. « Sans nouvelle table » et « aucune ACL projet » sont
  remplacés par cette décision.
- DEC-0063 : AMEND. Le scope Project est composé avec l'accès projet. Les
  scopes Studio (règle du point 4) et User sont inchangés.
- DEC-0035, DEC-0018, DEC-0080, DEC-0049, DEC-0051, DEC-0069, DEC-0071 :
  AMEND ponctuels (émission d'événement, SSE, contexte, review queue,
  résolution).
- DEC-0012, DEC-0045, DEC-0046, DEC-0098, DEC-0011 : KEEP.
- Aucune supersession.

## Hors périmètre

Organisations, workspaces, billing, rôles par projet, invitations.
