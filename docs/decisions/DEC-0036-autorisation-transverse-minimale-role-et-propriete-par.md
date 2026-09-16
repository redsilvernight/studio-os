---
id: DEC-0036
title: 'Autorisation transverse minimale : role et propriete par ressource, sans nouvelle
  table'
status: active
date: '2026-09-14'
superseded_by: null
source: docs/DECISIONS.md
sync_hash: sha256:a88db6c933a8014c68750c0e0a839222e0b24af467b8ad6cdd3bdb5ecaf8c4c7
---

# DEC-0036 — Autorisation transverse minimale : role et propriete par ressource, sans nouvelle table

Lot P1 de `docs/AUDIT_REMEDIATION_CLAUDE_CODE_2026-09-14.md` ("Definir puis
appliquer une autorisation transverse minimale"), etape 7 en cours de
`docs/ROADMAP_CORRECTIONS_AUDIT.md`. Conception initiale par
`studio-architect`, implementee et verifiee dans cette session. Touche
`TECH/04_AUTH_SYNC_CONTRACT.md` (additif : nouvelle section Autorisation) et
`TECH/02_API_CONTRACT.md` (breaking documente : nouveau `403` sur des
endpoints existants, meme categorie que DEC-0025) — `contract-change` suivi,
`contract-guardian` a l'appui.

### Probleme

Le depot reconnait les roles `admin|developer|agent|readonly`, mais
`require_roles` n'etait applique qu'au provisioning
(`POST /projects|/machines|/users`). Aucune ACL sur le reste de l'API :
toute machine authentifiee pouvait lister tous les transferts, obtenir une
URL de telechargement et supprimer un transfert dont elle n'etait ni
emettrice ni destinataire ; un role `readonly` pouvait ecrire partout ; une
machine pouvait renouveler/liberer le claim d'une autre, terminer la session
d'une autre, ou patcher l'entree AI Work Ledger d'un agent qu'elle ne
possede pas.

### Decision

Modele a deux niveaux, sans nouvelle table — derive de champs deja
existants :

1. **Role transverse** : `User.role` du proprietaire de la machine
   authentifiee (`Machine.owner_user_id`), charge une fois par appel dans
   `studio_api.services.authz.Principal{machine, user, role}`
   (`load_principal`).
2. **Propriete par ressource** : le lien existant de la ressource vers une
   machine/un user (`Task.claimed_by_machine_id`,
   `ResourceClaim.claimed_by_machine_id`, `WorkSession.machine_id`,
   `AIWorkLog.agent_id` via `Agent.machine_id`, `Transfer.sender_user_id` /
   `recipient_user_id`).

Nouveau module `services/api/src/studio_api/services/authz.py` :
`ensure_can_write` (readonly jamais en ecriture), `ensure_can_provision`
(reserve a `require_roles`, non duplique ici), `ensure_machine_owned`
(task/claim/session/ai-work — proprietaire ou admin), `ensure_transfer_access`
+ `transfer_visibility_clause` (regle Transfer, seul defaut concretement
exploitable identifie par l'audit).

Regle Transfer : `sender_user_id`/`recipient_user_id` (`recipient=None` =
diffusion, ex. build/asset projet) pilotent l'acces — lecture
(liste/metadonnees/download-url) ouverte a sender/recipient/diffusion/admin,
`readonly` inclus ; ecriture (upload/initiate, upload/complete, delete)
reservee a sender/admin. `GET /transfers` filtre silencieusement au lieu de
403 sur la liste (`transfer_visibility_clause`) — jamais de 404 de
confidentialite sur un transfert precis, un 403 explicite a la place.

Application dans les fonctions de service mutantes elles-memes (`principal`
en premier argument apres `session`), jamais une decision d'autorisation
*dupliquee* ou *divergente* dans les routers HTTP ni les handlers MCP :
`services/mcp/src/studio_mcp/errors.py::run_tool` charge desormais le
`Principal` juste apres l'authentification machine et l'injecte a chaque
handler (`ToolHandler = Callable[[AsyncSession, Principal], ...]`, remplace
l'ancien `MachineModel`) — garantit la parite HTTP/MCP sans dupliquer la
logique de decision. `deps.py` ajoute `CurrentPrincipal` (charge `Principal`
a partir de `CurrentMachine`) a cote de `CurrentMachine` existant ;
heartbeat reste sur `CurrentMachine` seul (exception explicite, ecrit son
propre etat meme sous `readonly`).

Le controle de role doit s'executer avant le court-circuit d'idempotence,
pour qu'un appelant non autorise ne puisse jamais consommer ou observer la
reponse deja stockee d'un tiers via un rejeu — risque explicitement liste
par l'audit. Pour `POST /events`/`studio_emit_event`,
`resolve_event_identity` (qui appelle `ensure_can_write`) s'execute
inconditionnellement avant `create_event`, qui fait lui-meme le
court-circuit sur `event_id` : correct des la premiere version.

Pour les 6 autres creations (`POST /tasks|/claims|/sessions|/ai-work|
/decisions|/transfers`), qui passent par
`idempotency_service.run_idempotent`/`run_idempotent_dict` : la premiere
version de ce lot appelait `ensure_can_write` **a l'interieur** de la
fermeture `_create()` passee a `run_idempotent`, or cette fermeture n'est
jamais invoquee sur un rejeu qui gagne le court-circuit (`_resolve_existing`
renvoie directement `response_body` sans jamais rappeler `_create()`) — un
appelant dont le role a ete degrade *apres* l'ecriture originale (ou, plus
generalement, tout appelant presentant la meme paire `(idempotency_key,
endpoint)` avec un corps identique, `IdempotencyKeyModel` n'etant scope que
par cette paire, pas par l'appelant) pouvait donc rejouer la meme cle et
recevoir la reponse stockee d'un tiers sans jamais passer par
`ensure_can_write`. Trouve par `studio-tester` en verification independante
de ce lot, avant cloture — pas en production. Corrige en appelant
`ensure_can_write` inconditionnellement dans le routeur HTTP et le handler
MCP, avant l'appel a `run_idempotent`/`run_idempotent_dict`, exactement la
meme place (avant le court-circuit, jamais dedans) que `resolve_event_identity`
pour les events — ce n'est pas une nouvelle decision d'autorisation ecrite
dans le routeur, seulement l'appel, deplace la ou il peut effectivement
s'executer a chaque requete. La verification a l'interieur de la fonction de
service (`create_task`, etc.) reste en place en defense en profondeur pour
tout appelant direct de la couche service. Verifie par un nouveau test de
regression (`test_idempotent_replay_after_role_downgrade_is_still_forbidden`) :
ecriture initiale autorisee, degradation du role du proprietaire de la
machine, rejeu de la meme `Idempotency-Key` + corps -> `403 forbidden`,
jamais la reponse `201` mise en cache.

Enveloppe : `403 {"detail": {"error_code": "forbidden", "resource": ...,
"action": ...}}` — jamais un `404` de confidentialite (UUID v4, pas de
lookup par code humain, les listes filtrent deja).

### Consequences

- `POST /tasks`, `PATCH /tasks/{id}`, `POST /tasks/{id}/claim`,
  `POST /claims`, `POST /sessions`, `POST /ai-work`, `POST /decisions`,
  `POST /events`, `POST /transfers` : `readonly` desormais rejete (`403`),
  auparavant accepte.
- `POST /tasks/{id}/release`, `POST /claims/{id}/renew`,
  `DELETE /claims/{id}`, `PATCH /sessions/{id}/end`, `PATCH /ai-work/{id}` :
  une machine non proprietaire desormais rejetee (`403`), auparavant
  acceptee sans verification.
- `GET /transfers/{id}` et `POST /transfers/{id}/download-url` (lecture),
  `upload/initiate`, `upload/complete`, `DELETE /transfers/{id}` (ecriture) :
  un tiers (ni sender, ni recipient, ni diffusion) desormais rejete ; le
  recipient peut lire mais plus ecrire/supprimer. `GET /transfers` filtre
  desormais la liste au lieu de tout renvoyer. `TECH/02_API_CONTRACT.md`
  liste desormais `GET /transfers/{id}` et `download-url` explicitement (la
  premiere version de ce lot les omettait de l'enumeration malgre un
  comportement deja durci — trouve par `contract-guardian`, corrige dans la
  meme session).
- Aucun client conforme au contrat existant (role proprietaire de ses
  propres ressources, jamais d'acces a un transfert tiers) n'observe de
  changement — le durcissement ne mord que les usages deja hors contrat
  implicite.
- Cote Bloc B (`packages/studio-client`), aucun changement necessaire :
  `ForbiddenError`/`retry.is_retryable` traitaient deja tout `403` comme
  non-rejouable -> dead-letter direct (`.claude/rules/offline-sync.md`),
  verifie par un nouveau test plutot que suppose.
- Limite : pas d'ACL projet a granularite fine (ex. developer A ne peut pas
  etre exclu d'un projet precis) — hors perimetre de ce lot P1-2 minimal ;
  seule la regle Transfer (le defaut concretement exploitable) et le role
  transverse + propriete des 4 autres ressources sont couverts.

### Preuves

Suite complete locale : **348 passed** (316 avant ce lot + 21 nouveaux tests
API `tests/api/test_authz.py` + 10 nouveaux tests de parite MCP
`tests/mcp/test_authz_parity.py` + 1 nouveau test client
`tests/client/test_replay.py::test_readonly_forbidden_error_dead_letters_with_actionable_message`).
`ruff check .` et `ruff format --check .` verts (259 fichiers). `mypy
packages/studio-contracts/src packages/studio-client/src services/api/src
services/mcp/src` (strict) : `Success: no issues found in 97 source files`.
`git diff --check` : aucun conflit/espace en fin de ligne.

Matrice couverte (au moins 2 users x 2 machines, per lot 3) : `machine`
(developer), `other_machine` (developer distinct), `readonly_machine`,
`agent_machine`, `admin_auth_headers` — role transverse (readonly bloque
partout en ecriture, agent ecrit comme developer mais jamais de
provisioning), ownership croisee (task/claim/session/ai-work par machine
non proprietaire), transfert tiers (sender/recipient/diffusion/admin, 403
sur lecture et ecriture selon la matrice), parite HTTP/MCP (memes
assertions sur task/claim/session/ai-work/transfer via les deux
transports), revocation immediate conservee sous role developer
(`test_revoked_machine_cannot_write_even_with_developer_role`), rejeu
idempotent apres degradation de role toujours rejete
(`test_idempotent_replay_after_role_downgrade_is_still_forbidden`), aucun
octet fichier ne traverse FastAPI/MCP (deja garanti structurellement —
presigned URLs uniquement, reverifie par
`test_small_file_uploads_and_downloads_through_real_minio` existant,
inchange par ce lot).

Fichiers modifies : `services/api/src/studio_api/services/authz.py`
(nouveau), `services/api/src/studio_api/deps.py`,
`services/api/src/studio_api/services/{transfers,tasks,claims,sessions,ai_work,decisions,events}.py`,
`services/api/src/studio_api/routers/{transfers,tasks,claims,sessions,ai_work,decisions,events}.py`,
`services/mcp/src/studio_mcp/errors.py`,
`services/mcp/src/studio_mcp/tools/{transfers,tasks,claims,sessions,ai_work,decisions,events,projects,teammates}.py`,
`docs/Studio_OS_Documentation_Pack/studio_os_docs/TECH/{02_API_CONTRACT,04_AUTH_SYNC_CONTRACT}.md`.
Tests modifies/ajoutes : `tests/api/test_authz.py` (nouveau),
`tests/mcp/test_authz_parity.py` (nouveau), `tests/client/test_replay.py`,
`tests/api/conftest.py`, `tests/mcp/conftest.py` (nouvelles fixtures
`readonly_*`/`agent_*`/`other_*`).

Validation `studio-tester` et `contract-guardian` : voir rapports separes
dans la session.
