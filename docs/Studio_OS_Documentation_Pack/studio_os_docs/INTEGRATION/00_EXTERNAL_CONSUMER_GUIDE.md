# Guide d'integration d'un consommateur externe

Public cible : un developpeur tiers qui n'a jamais entendu parler de l'outillage
interne du studio. Tout ce qui suit ne suppose aucune connaissance d'un harness,
d'un provider, d'un modele ou d'un profil d'agent : le protocole ne les connait
pas, `auth_role` + ownership sont la seule autorite (`TECH/04`,
`docs/UNIVERSAL_CONSUMER_CONTRACT.md`).

Ce guide suit le parcours de zero jusqu'au premier transfert. Les contrats de
reference sont `TECH/02` (API), `TECH/03` (events), `TECH/04` (auth/sync),
`TECH/05` (data model), `TECH/06` (storage/transferts), `TECH/07` (MCP),
`TECH/08` (offline), `TECH/09` (memoire/knowledge).

## 1. Choisir un transport

- HTTP est l'interface canonique complete : base `https://<vps>/api/v1`.
  C'est le seul transport qui expose l'integralite des operations.
- MCP (transport `streamable-http`) est un **subset additif** : memes
  autorisations, surface plus petite (`TECH/07`, DEC-0046). La parite de
  surface n'est pas requise entre les deux.
- Memoire/knowledge local reste optionnel et purement local (section 8).
- `GET /healthz` et `GET /metrics` (hors `/api/v1`) sont publics : ils servent
  a verifier l'accessibilite sans credential.

## 2. S'authentifier

Chaque requete `/api/v1` (sauf `/healthz`, `/metrics`, le login humain
`POST /auth/token` et l'ingress webhook GitHub signe `POST /github/webhook`
— HMAC `X-Hub-Signature-256`, jamais Bearer) et chaque appel MCP HTTP porte
`Authorization: Bearer <machine-token>`.

Le token est un credential de machine opaque, genere hors bande par un humain
admin via la CLI serveur `studio-admin` (le tout premier compte est cree sur le
serveur, jamais via l'API). Le token n'est affiche qu'une fois ; seul son hash
est stocke cote serveur. Il est revocable independamment.

Ensuite, un admin peut provisionner les autres comptes via l'API normale :

- `POST /api/v1/users` (role `admin|developer|agent|readonly`) ;
- `POST /api/v1/machines` → renvoie une fois `MachineCreated.credential` en
  clair, jamais recuperable ensuite.

Reponses d'echec d'authentification : `401 {"detail": "missing bearer token"}`
ou `401 {"detail": "invalid or revoked machine token"}`.

## 3. Connaitre ses permissions

La matrice est `TECH/04` §Autorisation : role transverse + ownership.

- `readonly` : lectures + heartbeat uniquement.
- `agent` : ecritures, sauf `POST /projects`, `/machines`, `/users`.
- `developer` : comme `agent`, plus la creation de projet.
- `admin` : tout, y compris provisioning et resolution de revue.

Un refus normatif est toujours
`403 {"detail": {"error_code": "forbidden", "resource": ..., "action": ...}}`.
Il n'y a pas de 404 de confidentialite (pas d'enumeration).

## 4. Decouvrir les capacites

- HTTP : le schema OpenAPI est servi par l'instance (`/openapi.json`, `/docs`).
  Un client peut generer ses routes a partir de la.
- MCP : `tools/list` est la verite de ce que ce transport expose.
- Il n'existe aucun registre de harness/provider/model « supportes » : la
  question est « quelles capacites cette instance expose-t-elle ? », jamais
  « est-ce que mon agent est reconnu ? ». Aucun profil prealable n'est exige.

## 5. Parcours minimal : tache -> event -> worklog

1. **Projet** (developer/admin) : `POST /api/v1/projects` avec
   `Idempotency-Key`. Un projet existant peut etre reutilise.
2. **Tache** : `POST /api/v1/tasks` avec `Idempotency-Key`
   (`{"project_id", "title", ...}`), puis `GET /api/v1/tasks/{id}`.
   Mutation : `PATCH /api/v1/tasks/{id}` avec l'en-tete
   `If-Match-Version: <version>` (conflit = `409 version_conflict` + version
   serveur). Prise/relachement : `POST /tasks/{id}/claim|/release`.
3. **Claims** : `POST /api/v1/claims` (`resource_path`, `resource_type`,
   `ttl_seconds`, `Idempotency-Key`). Ce sont des **soft locks** : ils
   avertissent, ne bloquent jamais Git ni l'ecriture de fichier.
4. **Events** : `POST /api/v1/events` avec un `event_id` UUID genere cote
   client (l'`event_id` est lui-meme la cle d'idempotence, pas
   `Idempotency-Key`). L'enveloppe est fixe (`TECH/03`) ; seul `payload` varie.
   Identite : `machine_id` omis = derive de la machine authentifiee, sinon
   `409 machine_id_mismatch` ; `actor_type=user|agent|system` suit `TECH/04`.
5. **Worklog** (optionnel mais MUST-capable) :
   `POST /api/v1/agents` (`display_name` requis ; `agent_kind`,
   `agent_profile`, `harness`, `provider`, `model` optionnels, chaines
   ouvertes, aucune valeur requise), puis `POST /api/v1/ai-work` avec
   `agent_id`. Le suivi de revue (`review_requested` -> `approved` /
   `changes_requested`) est `admin` uniquement (`409
   invalid_status_transition` sinon).

Aucune de ces etapes n'exige un profil d'agent : un consommateur totalement
inconnu, sans `agent_profile`, obtient exactement l'interface de son
`auth_role`.

## 6. Approfondir : sync offline, temps reel, transferts

- **Offline** (`TECH/08`) : toute operation rejouable porte un UUID stable cote
  client ; le serveur ne cree jamais de doublon au rejeu identique. File locale
  type outbox, ordre par session, backoff exponentiel borne, `dead_letter`
  visible/inspectable. Un `403` n'est jamais rejouable.
- **Temps reel** : SSE `GET /api/v1/events/stream?project=<id>` avec curseur
  `Last-Event-ID`/`since_seq` ; rattrapage par polling `GET /events?since=`.
- **Transferts** (`TECH/06`) : les octets ne passent **jamais** par l'API ni
  par MCP. `POST /transfers` renvoie des metadonnees + une URL pre-signee
  MinIO/S3 ; le client envoie le fichier directement au stockage.
  - petit fichier (single-PUT) : `upload/initiate` avec `content_md5`
    (base64 RFC 1864), PUT direct avec l'en-tete `Content-MD5`, puis
    `upload/complete` avec taille + `sha256` ;
  - gros fichier (multipart) : parts de 64-128 MiB, etat des parts conserve
    localement pour reprendre, `upload/refresh-parts` sur `ListParts` serveur
    apres expiration d'URL, puis `complete`.
  - download : URL pre-signee courte, reprise par `Range`.

## 7. Gerer les erreurs

Enveloppe reelle : `{"detail": {"error_code": "...", ...}}` (ou
`{"detail": "<message>"}` pour les 401/403/404 generiques). Traiter un
`error_code` inconnu comme definitif et inspectable, jamais comme rejouable par
defaut. Catalogue courant : `forbidden`, `version_conflict`,
`idempotency_key_in_progress`, `idempotency_key_payload_mismatch`,
`actor_not_owned`, `invalid_status_transition`, `transfer_too_large`,
`quota_exceeded`, `content_md5_mismatch`, etc. (`TECH/02`, `TECH/04`).

## 8. Memoire/knowledge (optionnel, local)

Cette capacite est MAY : un consommateur fonctionne normalement sans elle. Quand
elle est configuree localement, elle est exposee en lecture seule par un
serveur MCP local (transport stdio, un processus par poste) qui n'a aucun
endpoint HTTP VPS correspondant et ne copie rien vers le VPS :

- `studio_memory_search`, `studio_memory_read` (si un vault est configure) ;
- `studio_graph_query` (si un graphe est configure) ;
- `tools/list` du processus local decrit exactement les capacites configurees.

Configuration par variables d'environnement lues par le processus local :
`STUDIO_CLIENT_KNOWLEDGE_VAULT_PATH`, `STUDIO_CLIENT_KNOWLEDGE_SCOPE_ALLOW`
(liste JSON), `STUDIO_CLIENT_KNOWLEDGE_GRAPH_DIR`,
`STUDIO_CLIENT_KNOWLEDGE_SOURCE_ROOT`. Portee vide = refus total (deny-all).
Un backend configure mais indisponible degrade en reponse machine-readable
(`vault_missing`, `stale`, ...), jamais en plantage (`DEC-0042`, `DEC-0047`).

## 9. Versions et evolution

- HTTP : prefixe `/api/v1`.
- Events : `schema_version` sur l'enveloppe.
- Champ/endpoint/type d'event optionnel ignorable = additif, sur ; suppression,
  renommage, changement de required-ness ou de semantique = breaking, jamais
  silencieux (`contract-change` + `DEC-XXXX`).
- MCP : aucun numero de version par payload ; evolution par `tools/list` +
  schemas + regles additive/breaking (`TECH/07` §Evolution, DEC-0048).

## 10. Ce qu'il n'y a pas a connaitre

Il n'est pas necessaire de savoir quel harness, provider ou modele utilise un
agent, ni de declarer un profil : ces informations sont des metadonnees
d'observabilite optionnelles, sans effet sur l'autorisation ou les capacites.
Un client totalement inconnu doit donc pouvoir integrer Studio OS en suivant
ce guide seul.

## 11. Workflow d'un agent (harness-agnostique)

Le protocole minimal pour qu'un agent travaille, quel que soit son harness.
La regle permanente tient en une page (`.agents/rules/studio-protocol.md`) ;
les details vivent dans les skills (`.agents/skills/studio-*`), jamais recopies ici.

1. Installer/connecter Studio OS (sections 1-2 : transport, machine-token).
2. Generer la configuration du harness depuis la source canonique
   (`.agents/definitions/`) : `studio-client adapters export --adapter
   <claude-code|opencode|codex> --stable-key <agent> --from-canonical`.
   Ne jamais maintenir ces fichiers a la main (`adapters check` en CI).
3. Recevoir un objectif, puis appeler `studio_prepare_context` en premier —
   jamais un scan large du depot. Suivre `why` / `matched_terms`, puis
   `additional_available` / `omitted_for_budget` (progressive disclosure).
4. Travailler : `claim` la tache et les chemins, `update` avec
   `expected_version` (409 = relire, fusionner, rejouer), tracer avec AI work.
5. Persister les decisions durables (`studio_add_decision`) au lieu de garder
   leur justification uniquement dans la conversation.
6. Cloturer avec la sequence `studio-handoff` (resume DONE/STATE/CHANGED/
   TESTS/NEXT/BLOCKERS dans AI work, liberer claims, terminer la session).
7. Un autre agent/harness reprend avec un seul `studio_prepare_context` :
   tache + decisions + handoff/NEXT, sans historique de conversation.
