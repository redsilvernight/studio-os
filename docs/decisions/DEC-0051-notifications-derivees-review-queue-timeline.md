---
id: DEC-0051
title: 'Question ouverte n°4 (etape 8) : notifications derivees de la Review Queue,
  timeline sur les events, aucune entite Notification persistee'
status: active
date: '2026-09-15'
superseded_by: null
source: docs/DECISIONS.md
sync_hash: sha256:b267cef7fa297ca3add536dc867e25c2fa5940ee2eab795e3781cbcf686a7678
---

# DEC-0051 — Question ouverte n°4 (etape 8) : notifications derivees de la Review Queue, timeline sur les events, aucune entite Notification persistee

Question ouverte n°4 de `docs/ROADMAP_STEP8_BREAKDOWN.md`, etudiee avant
implementation de la sous-etape 8.5 (meme convention que DEC-0041 :
question de conception non triviale tranchee avant le code). Sert d'ADR de
conception pour toute la sous-etape 8.5.

### Probleme

`TECH/05_DATA_MODEL.md` liste `Notification` parmi les entites "reste a
specifier en Phase 4-6, pas encore code". `HUMAN/02_FONCTIONNALITES_FINALES.md`
attend des notifications "restreintes aux seuls evenements qui demandent
une action" (conflit, build casse, review IA, PR prete, tache bloquee,
decision/memoire a approuver, nouveau transfert) et une timeline
quotidienne par projet derivee du flux d'evenements deja reprenable par
curseur `seq` (DEC-0018).

Deux options non tranchees :
(a) entite serveur persistee — nouvelle table, endpoints, etat lu/non-lu
par utilisateur, dedup multi-machines d'une meme notification ;
(b) derivation pure du flux d'evenements existant, cote service/client,
sans nouvelle table.

L'option (a) exige une identite utilisateur qui n'existe pas : `TECH/04`
n'a qu'une authentification machine (DEC-0050 vient de le ratifier tel
quel), l'identite utilisateur n'etant qu'un champ derive
(`Machine.owner_user_id`), jamais une session adressable independamment.
Construire une table `Notification` avec etat lu/non-lu *maintenant*
reviendrait a inventer une brique d'authentification/session utilisateur
en sous-marin, au milieu d'un lot cense livrer une derivation
d'evenements — exactement le type d'entite a moitie finie que le projet
s'interdit.

Verification faite avant de trancher : un filtre naif "notifications =
events dont le type est dans une liste actionnable" serait deja casse par
construction aujourd'hui. `EventType.DECISION_PROPOSED` existe dans
`packages/studio-contracts/src/studio_contracts/events.py`, mais
`services/api/src/studio_api/services/decisions.py::create_decision`
n'appelle jamais `events_service.create_event` — aucune decision proposee
n'emet cet evenement (verifie par lecture directe du service, confirme
par grep : zero occurrence de `create_event`/`events_service` dans ce
fichier). Un endpoint "notifications" fonde sur un filtre d'`EventType`
raterait donc silencieusement toute decision proposee, sans erreur
visible — un defaut de conception, pas un defaut d'implementation future
a corriger a la marge.

### Decision

1. **Option (b) retenue : aucune entite `Notification` persistee dans ce
   lot.** "Ce qui demande une action humaine maintenant" = exactement ce
   que la sous-etape 8.4 (Review Queue, `GET /api/v1/review-queue`)
   calcule deja correctement en interrogeant l'etat reel
   (`AIWorkLog.status == review_requested`, `Decision.status == proposed`,
   evenements `resource.conflict` recents) plutot qu'un type d'evenement
   qui peut ne jamais etre emis. **"Notifications" est donc un alias de
   "Review Queue"**, pas un nouveau concept serveur.
2. **Timeline = derivation separee et complementaire**, sur le flux
   d'evenements brut (`GET /api/v1/timeline`, nouvelle sous-etape 8.5),
   regroupee par jour calendaire UTC, sans filtre "actionnable" — c'est
   l'historique, pas l'alerte. Les deux surfaces repondent a deux besoins
   differents explicitement distingues par le texte de la roadmap
   ("derivation d'une timeline... ET notifications restreintes...").
3. **Aucun nouveau `EventType`** n'est ajoute (pas de `notification.*`) :
   les notifications ne sont pas un evenement, elles sont une vue calculee
   sur des entites existantes (comme `ProjectState` l'est deja pour les
   taches/claims actifs).
4. **Aucun nouvel endpoint API ni outil MCP dedie aux notifications.**
   `TECH/02_API_CONTRACT.md` renvoie explicitement vers
   `GET /review-queue` pour "notifications". Un second outil MCP
   renvoyant les memes donnees qu'un outil existant degraderait la
   selection d'outil par l'agent (`.claude/rules/mcp-tools.md`) sans
   apporter d'information nouvelle.
5. **Seul le CLI recoit un alias** : `notifications list`, implemente
   comme un appel direct a la meme methode client que `review-queue list`
   (zero logique dupliquee) — vocabulaire humain plus naturel en ligne de
   commande, inutile pour un agent qui lit deja la description de l'outil
   MCP.
6. **Une entite `Notification` persistee (lu/non-lu, dedup multi-machines)
   reste explicitement differee**, pas abandonnee : elle n'a de sens
   qu'une fois une vraie identite/session utilisateur disponible — meme
   prerequis manquant que la question n°3 (DEC-0050). A rouvrir par une
   Decision dediee le jour ou ce prerequis existe, pas a re-decouvrir en
   sous-marin dans un lot futur.
7. **Cette decision ne resout pas la question ouverte n°9** (emission
   serveur absente pour `task.*`/`session.*`/`decision.*`/`transfer.*`) :
   la timeline de 8.5 herite directement de la meme incompletude que
   `GET /events` ("not claimed exhaustive") pour tout ce qui n'est pas du
   travail IA, du Git ou du Godot. Reste un ecart documente, probablement
   un lot transverse d'etape 9.

### Consequences

- `TECH/05_DATA_MODEL.md` : la ligne `Notification` passe de "reste a
  specifier" a "delibrement non persistee pour cette etape, derivee de
  Review Queue (8.4) + Timeline (8.5), voir DEC-0051" — mis a jour dans le
  meme lot que le code de 8.5.
- `TECH/02_API_CONTRACT.md` : nouvelle section `GET /timeline`, plus une
  note explicite "notifications = voir `GET /review-queue` (8.4)".
- `TECH/03_EVENT_CONTRACT.md` : inchange (aucun nouveau `EventType`).
- `TECH/07_MCP_CONTRACT.md` : nouvelle entree `studio_get_timeline`, plus
  un renvoi sous `studio_get_review_queue` au lieu d'un nouvel outil.
- Aucune migration, aucune nouvelle table.
- Limite assumee et documentee : une notification "manquee" pendant une
  coupure ne redevient pas visible comme notification apres coup (l'item
  Review Queue sous-jacent, lui, reste visible tant que son statut ne
  change pas — donc pas de perte reelle d'information actionnable, juste
  pas de mecanisme de "notification poussee historique").
- Le trou d'emission `decision.proposed` decouvert pendant cette etude
  n'est pas corrige ici (hors perimetre de 8.5, cf. question n°9) ; corrige
  de facto pour l'usage Review Queue puisque celle-ci n'en depend pas.

### Preuves

Verification faite pendant l'etude de conception : lecture directe de
`services/api/src/studio_api/services/decisions.py` (aucun appel a
`create_event`), grep sur `create_event|events_service` dans ce fichier
(zero resultat), lecture de
`packages/studio-contracts/src/studio_contracts/events.py` (confirmation
de la presence de `DECISION_PROPOSED` dans l'enum malgre l'absence
d'emission), lecture de `TECH/05_DATA_MODEL.md` (citation verbatim de la
ligne `Notification`), lecture de `dashboard/README.md` et DEC-0050 pour
le prerequis d'identite utilisateur partage entre les deux questions.

**Mise a jour post-implementation (meme lot, revue independante
`contract-guardian`)** : la decision ci-dessus a ete implementee tel
quelle immediatement apres cette etude, dans le meme lot que 8.4 plutot
qu'en deux temps separes — signale par `contract-guardian` comme
necessitant une clarification explicite ici plutot que de laisser le texte
au futur. Verification faite : `ruff check`, `ruff format --check`,
`mypy --strict` verts sur les 4 racines (aucune erreur nouvelle) ;
`create_app().openapi()` confirme `GET /api/v1/timeline` monte avec les
bons parametres ; `create_server()` (MCP) confirme `studio_get_timeline`
enregistre ; grep confirme qu'aucun `EventType` n'a ete ajoute ;
`TECH/05_DATA_MODEL.md` mis a jour dans le meme lot (ligne `Notification`).
**Non fait** : la suite `tests/api/test_timeline.py`,
`tests/mcp/test_timeline.py` et les ajouts `tests/client/test_cli.py`
(`timeline list`, `notifications list`) sont ecrits mais **jamais executes
contre un Postgres reel** — Docker indisponible sur la machine de
developpement au moment de ce lot (meme limite que DEC-0049). A executer
et confirmer, par `studio-tester` ou par un developpeur disposant d'un
environnement Postgres/MinIO, avant de considerer cette sous-etape close.

Fichiers ajoutes par l'implementation de 8.5 (meme lot que cette decision) :
`packages/studio-contracts/src/studio_contracts/timeline.py`,
`services/api/src/studio_api/services/timeline.py`,
`services/api/src/studio_api/routers/timeline.py`,
`services/mcp/src/studio_mcp/tools/timeline.py`,
`tests/api/test_timeline.py`, `tests/mcp/test_timeline.py`.
Fichiers modifies : `services/api/src/studio_api/main.py` (routeur + tag),
`services/mcp/src/studio_mcp/server.py` (enregistrement outil),
`packages/studio-client/src/studio_client/api_client.py` (`get_timeline`),
`packages/studio-client/src/studio_client/cli.py` (`timeline`,
`notifications`), `tests/client/test_cli.py`, `TECH/02_API_CONTRACT.md`,
`TECH/05_DATA_MODEL.md`, `TECH/07_MCP_CONTRACT.md`,
`docs/ROADMAP_STEP8_BREAKDOWN.md` (statut des sous-etapes 8.4/8.5).
