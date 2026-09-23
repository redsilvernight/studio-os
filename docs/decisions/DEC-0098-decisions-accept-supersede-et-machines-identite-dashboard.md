---
id: DEC-0098
title: 'Decisions accept/supersede : transitions admin-only, et identite technique dashboard exclue des Machines'
status: active
date: '2026-09-21'
superseded_by: null
source: docs/DECISIONS.md
---

# DEC-0098 — Decisions accept/supersede et identite technique dashboard

Comble un manque reel de master (verifie sur le code, pas suppose) : `Decision`
peut naitre `proposed` (`POST /decisions`) et apparaitre dans la Review Queue
comme `decision_proposal`, mais aucun endpoint ne permettait de la resoudre.
Le commentaire meme de `services/review_queue.py` le documentait avant ce
correctif : *"no transition endpoint exists for decisions"*. **Additif** :
aucun contrat existant n'est rompu, `API_CONTRACT_VERSION` et
`EVENT_SCHEMA_VERSION` restent `1`.

Numerotation : `DEC-0091` (Desktop P0, Tauri 2) et `DEC-0092`
(CodeGraphProvider) sont deja actives sur `desktop/architecture` ; `DEC-0093`
(Desktop P1, contrats locaux) est deja active sur `desktop/contracts-core`.
La decision portait initialement `DEC-0094`, premier numero libre sur les
branches inspectees au moment de l'ecriture. La reconciliation finale avec la
branche Desktop a revele que ce numero designait deja le cycle de vie du
daemon P4 ; cette decision est donc renumerotee `DEC-0098` sans changer son
contenu ni son statut.

## Decisions ≠ Roadmaps

Deux domaines distincts, chacun avec son propre service, ses propres modeles
et sa propre semantique — jamais fusionnes :

- **Decisions** : gouvernance/architecture, cycle `proposed → accepted →
  superseded` (`superseded` terminal), une seule transition a la fois, pas de
  revisions ni de diff.
- **Roadmaps P8** (DEC-0089) : `proposal → revision → approve/request_changes/
  reject`, avec numerotation de revision, diff et contenu versionne.

La Review Queue (DEC-0049) continue d'agreger les deux (`decision_proposal` et
`roadmap_proposal` restent deux `kind` separes) sans que l'un emprunte le
service de l'autre.

## Transitions Decisions

`services/decisions.py::_transition_decision` :

- `proposed → accepted` (`POST /decisions/{id}/accept`) ;
- `proposed → superseded` et `accepted → superseded`
  (`POST /decisions/{id}/supersede`) ;
- `superseded` est terminal : aucune transition n'en sort, y compris un
  nouveau `supersede` (`409 invalid_decision_transition`).

Pas une creation : pas d'`Idempotency-Key`. Une relecture apres succes echoue
simplement au controle de statut (meme reponse `409` qu'une transition
invalide), ce qui suffit a rendre la retentative sure sans mecanisme dedie.

## Permissions

Admin-only, verifie avant toute lecture verrouillee de la ligne (le refus ne
depend jamais de l'existence de la ressource, donc ne fuite rien) :
`developer`, `agent` et `readonly` recoivent `403 forbidden` ; seul `admin`
peut resoudre. Reutilise `ensure_can_write` + le role `Role.ADMIN` (meme
primitives que `ai_work._ensure_can_resolve_review`).

## Concurrence

`SELECT ... FOR UPDATE` sur la ligne `Decision`
(`decisions.py::_lock_decision`, meme mecanisme que
`roadmap_support.lock_roadmap`) : le verrou serialise deux transitions
concurrentes sur la meme decision, donc exactement un admin reussit et les
autres recoivent `409 invalid_decision_transition`. Pas de colonne `version`
ajoutee : `Decision` n'en avait pas besoin ailleurs et le verrou de ligne
suffit a la CAS. Verifie par un test de course reelle a 10 requetes
concurrentes contre un Postgres reel (`tests/api/test_decisions_concurrency.py`),
pas seulement affirme.

## HTTP canonique

`POST /decisions/{id}/accept`, `POST /decisions/{id}/supersede` — routeur
mince (`routers/decisions.py`), toute la logique dans le service partage.

## MCP

`studio_accept_decision`, `studio_supersede_decision` — adaptateurs stricts du
meme service, aucune logique metier parallele. Mesure reelle (pas supposee) :
44 outils MCP apres ajout (42 avant), confirmee par
`tests/mcp/test_uc2b_tools_metadata.py`.

## Events / audit / SSE

Additif dans `EventType` (`studio_contracts.events`) :
`decision.accepted` (`DECISION_ACCEPTED`), `decision.superseded`
(`DECISION_SUPERSEDED`). Emis dans la meme transaction que l'ecriture du
statut, commit unique, puis publication sur le flux temps reel
(`events_service.publish_event`), memes garanties que
`roadmap_support.finish_result`. Une `Decision` globale (`project_id` nul)
n'emet pas d'evenement — l'enveloppe d'evenement exige `project_id`
(`.claude/rules/contracts.md`) — la transition reste valide, elle n'a
simplement rien a publier.

Verifie par un test de livraison reelle sur `GET /events/stream` (pas
seulement l'ecriture en base) : `tests/api/test_decisions_sse.py`, un serveur
uvicorn reel, un abonnement SSE ouvert avant la transition, l'evenement recu
en direct.

## Review Queue

`decision_proposal` reste `proposed` uniquement (une decision resolue en
sort). Reconciliee : la documentation (API/MCP/Dashboard) ne dit plus
qu'aucune action n'est disponible — elle l'est desormais, via les deux
transitions ci-dessus. Aucun nouvel agregateur : le meme
`services/review_queue.py::get_review_queue` reste la source unique.

## Dashboard

`decisionsV2.ts` expose Accepter/Remplacer pour un admin (statut proposed :
les deux ; accepted : Remplacer seul ; superseded : aucune), a la fois sur la
liste Decisions et sur les items `decision_proposal` de la Review Queue — un
seul gestionnaire de clic, deux points de montage. Le role est lu depuis le
claim `role` du JWT dashboard (`decodeJwtRole`, meme garde-fou non-autoritaire
que `decodeJwtSubject` : un indice d'affichage, jamais une decision
d'autorisation — le serveur revalide toujours le role). Pour tout role non
admin ou non authentifie, les boutons restent visibles mais desactives — la
capacite se decouvre, elle ne disparait pas silencieusement.

## Identite technique dashboard — Machines

`get_or_create_dashboard_machine` (DASH-4) cree une `Machine` `display_name
== "dashboard"` par utilisateur, comme identite d'authentification du
dashboard humain — jamais une machine/runtime utilisateur. Correctif UX pur,
cote client uniquement, aucun changement du contrat backend :
`machinesApi.ts::isDashboardIdentity(displayName)` (insensible a la
casse/aux espaces) exclut cette ligne de `buildMachineRows` — donc de la
liste Machines et de ses agregats derives (agents/sessions observes) — sans
toucher `GET /machines` ni aucun autre contrat. L'identite reste visible
partout ou `display_name`/`machineId` s'affichent directement (details
techniques, Inspector).

## Regle architecturale deploy

`deploy/* = master + adaptations de deploiement uniquement.` Aucune feature
produit (Decisions, Roadmaps, Machines, MCP, Dashboard, contrats metier,
migrations metier) ne doit jamais exister uniquement sur une branche
`deploy/*` : toute divergence hors `docker/Caddyfile` et
`docker/docker-compose.yml` (ports, endpoint S3 public) est une anomalie a
corriger, jamais une adaptation legitime.
