# DU-0 — Architecture Gate Report

Date : 2026-09-24  
Roadmap : `33da4321-b607-41d2-ba90-3144028628e2`, révision 2  
Statut du gate : **BLOCKED — validation humaine requise**

Ce lot est exclusivement architectural. Aucun endpoint, modèle, migration,
rate limiter, écran, updater, certificat, secret ou workflow de publication
n'a été implémenté.

## A. DEC-0103 — isolation projet

**Current.** L'API applique rôle global et ownership, sans ACL projet. La
membership binaire User→Project est le plus petit modèle cohérent : le rôle
dit quoi faire, la membership dit où. Les Machines héritent de leur owner et
les Agents ne portent aucune autorité propre.

**Corrections apportées au document proposé.** La co-membership est directe et
non transitive. Elle ne donne jamais accès aux Machines/Agents globaux d'un
co-membre ; une Session est filtrée uniquement par `session→task→project` et
l'activité par son `project_id` propre. La création projet+membership exige une
transaction réelle sans `commit()` interne. Le backfill reste tous Users
historiques × tous projets pour préserver l'accès existant, mais un préflight
bloquant classe comptes/bots, valide les owners, interdit les orphelins et
archive les couples créés. Sa provenance système est explicite.

**Contrats.** TECH/02, TECH/04 et TECH/07 : rupture sémantique ; TECH/05 :
additif ; TECH/03 : enveloppe inchangée. `API_CONTRACT_VERSION` passe à 2.
DEC-0036 et DEC-0063 : AMEND. DEC-0011/0012/0045/0046/0098 : KEEP. Aucune
supersession.

**Registre.** Proposition serveur canonique UUID
`19922554-bcd8-498f-9a14-7dab87916bf2` (`readable_id=DEC-0103`), **proposed**,
corps resynchronisé. Elle remplace `d31c16ea-06f1-481c-a701-7c06845dd426`
(`DEC-0097` serveur, désormais **superseded**). ADR :
`docs/decisions/DEC-0103-isolation-projet-membership-user.md`.

## B. Inscription publique

**Current.** Aucun register public ; Users et Machines sont créés par admin ;
le bootstrap initial reste hors-bande. Aucun état actif/vérifié ni token
one-shot n'existe.

**Options.** Toujours ouverte ; invitation seulement ; flag d'instance OFF par
défaut. La troisième option est recommandée.

**Recommandation.** `PUBLIC_REGISTRATION_ENABLED=false`, User `readonly`
pending, zéro membership, réponses non énumérantes, vérification/reset par
secrets hashés à usage unique et activation sans octroi de projet. Bootstrap
DEC-0011 conservé ; enrôlement machine différé à A5. Register/resend/forgot
exigent `Idempotency-Key`; verify/reset rejouent leur résultat terminal sans
seconde consommation.

**Impacts.** Routes et tables nouvelles additives ; application obligatoire de
l'état de compte breaking (API contract 2). DEC-0012/0056 AMEND ; DEC-0011
KEEP. Proposition serveur UUID `bcf92622-8b2a-48fa-bb16-bf345b867489`,
`readable_id=DEC-0109`, **proposed**, alignée sur l'ADR ; remplace
`61b0a658-…` (DEC-0104) et `a4c86edd-…` (`DEC-0098` serveur), tous deux
superseded. ADR :
`docs/decisions/DU0-A-public-registration.md`.

## C. Session, tokens et révocation

**Current.** JWT HS256 480 min en mémoire, sans version de révocation ; claims
email/rôle non réévalués. Credentials machine opaques séparés et révocables.

**Options.** JWT long ; access+refresh rotatif ; access court sans refresh et
compteur de révocation. La troisième est recommandée pour V1.

**Recommandation.** JWT 15 min, `auth_version`, `sub == owner_user_id`, état et
Machine vérifiés à chaque principal ; reset/disable/rôle/révocation globale
incrémentent le compteur. SSE revalide au plus toutes les 30 s. Aucun refresh
token V1.

**Impacts.** Anciens JWT invalidés au cutover : rupture API contract 2. TECH/02,
04, 05 et mocks des deux Blocs à modifier à l'implémentation. DEC-0012/0036/
0056 AMEND. Proposition UUID `4e509c7d-0a0c-4661-b97f-ffcbe916e5b9`,
`readable_id=DEC-0110`, **proposed**, alignée sur l'ADR ; remplace
`14905c34-…` (DEC-0105) et `b02d4215-…`, tous deux superseded. ADR :
`docs/decisions/DU0-B-session-revocation.md`.

## D. Proxy, rate limiting et anti-abus

**Current.** Limiteur mémoire par processus ; clé Bearer non validé ou premier
XFF ; aucune chaîne de confiance ni bucket auth dédié.

**Options.** Tout XFF ; aucun header proxy ; peer immédiat de confiance et
limites composées. La troisième est recommandée.

**Recommandation.** Caddy écrase les headers, CIDR de confiance explicites,
pré-auth IP+endpoint, post-auth identité validée, buckets stricts pour auth,
réponses non énumérantes, cache borné. Mémoire seulement en mono-réplique ;
store atomique partagé avant scale-out.

**Impacts.** `429`/`Retry-After` dans TECH/02 et confiance proxy dans TECH/04 ;
ces nouveaux statuts sont breaking et rattachés à API contract 2. Event
inchangé. DEC-0060 AMEND. Proposition UUID
`df4d6d3b-5682-4ee1-8460-410ebaf4c102`, `readable_id=DEC-0106`, **proposed** ;
remplace `a4b001d3-…` (`DEC-0103` serveur, superseded).
ADR : `docs/decisions/DU0-C-trusted-proxy-rate-limiting.md`.

## E. Version et compatibilité

**Current.** Version Desktop canonique et protocole local fail-closed, mais API
v1 non observable et aucune matrice N/N-1 publique.

**Options.** Version globale ; latest-only ; versions séparées et matrice.
La troisième est recommandée.

**Recommandation.** Séparer Desktop/server/API/Event/local protocol ; exposer
plus tard `GET /api/v1/meta/compatibility` public ; serveur N compatible Desktop N et N-1
selon matrice CI. API passe à 2 pour DEC-0103, Event reste 1. `403` projet est
terminal pour lectures, outbox et SSE.

**Impacts.** Metadata additif, API contract 2 breaking sous `/api/v1` (aucune
base `/api/v2`), Event neutre. DEC-0036/0056 AMEND ; DEC-0048/0060/0095/0098
KEEP. Proposition UUID `06d91e71-362b-4905-b0ef-74fd6145d56b`,
`readable_id=DEC-0107`, **proposed** ; remplace `0772dd83-…` (superseded).
ADR : `docs/decisions/DU0-D-version-compatibility.md`.

## F. Release, signature et distribution

**Current.** NSIS et minisign existent ; release CI privée sans publication,
canaux, Authenticode ni feed public.

**Options.** Minisign seul ; Authenticode seul ; double signature et promotion
sans rebuild. La troisième est recommandée.

**Recommandation.** Build taggé unique, GitHub Releases initialement,
Authenticode horodaté des exécutables/sidecars/installeur, puis signature
updater, SHA-256, SBOM/provenance. Manifests beta/stable séparés ; promotion du
même artefact. Clés distinctes en coffre CI. N/N-1 conservés. Fournisseur et
budget certificat restent un choix humain ultérieur.

**Impacts.** Manifest public additif ; Event neutre. DEC-0095 AMEND ; DEC-0098
KEEP. Champs nouveaux optionnels pour N-1. Proposition UUID
`4f298c8f-5073-4745-9e1c-ede8835d758f`, `readable_id=DEC-0108`, **proposed** ;
remplace `0e19d373-…` (superseded). ADR :
`docs/decisions/DU0-E-release-signature-distribution.md`.

## G. Contract Guardian

**Verdict final : CONFORME au niveau documentaire ; registre encore bloquant.**
Le premier passage a trouvé l'idempotence absente, une
contradiction `/api/v1`/`/api/v2`, une enveloppe d'erreur plate et la mauvaise
classification des `429`. Les ADR ont été corrigés : transport `/api/v1`
conservé avec `API_CONTRACT_VERSION=2` observable, enveloppe
`{"detail":{...}}`, idempotence/rejeu précisés, migrations réversibles et mocks
A/B obligatoires. Les corps serveur étant immuables, six propositions
corrigées (DEC-0103…0108) ont été créées et les anciennes superseded, sauf
`a4c86edd-…` (supersession à faire humainement). Seules les nouvelles UUID
sont à examiner.

Passe finale contract-guardian (après resynchronisation) : clarifications
apportées aux ADR, qui font foi sur les résumés serveur : état `pending` +
`email_verified_at` (pas `pending_verification`) ; `disabled_at` bloque sans
révoquer définitivement ; enveloppe `{"detail":{...}}` pour les erreurs à
`error_code`, `401` génériques inchangés (TECH/02 l.15) ; SSE fermé en cas
d'échec seulement ; refus MCP `forbidden` dans l'enveloppe TECH/07 ;
`409 idempotency_key_payload_mismatch` sans secret stocké. Points ouverts
pour l'humain : `403` sur UUID de projet inexistant pour un non-admin
(DEC-0103 §8) ; DU0-C pourrait AMEND DEC-0056 (429 sur `/auth/token`).

Contrats touchés : TECH/02 API, TECH/04 Auth/Sync, TECH/05 Data Model, TECH/07
MCP et, par notes de lecture/SSE seulement, TECH/03 Event. L'enveloppe Event
reste fixe ; le signal de retrait de membership reste interne. Les
mocks/fixtures des deux Blocs, OpenAPI, clients et schémas partagés seront
modifiés dans le même lot que chaque implémentation. DU-0 ne change pas les
contrats exécutés : il propose et classe les changements futurs.

Classification : isolation, invalidation des JWT existants, application des
états de compte et nouveaux `429` = **breaking/API contract 2** ; nouveaux
endpoints, champs, tables et manifestes = **additifs** tant qu'ils restent
optionnels pour les anciens clients ; Event = **neutre**. KEEP bundle :
DEC-0011/0045/0046/0048/0098. AMEND bundle : DEC-0012/0018/0035/0036/0049/
0051/0056/0060/0063/0069/0071/0080/0095. SUPERSEDE : aucune décision métier ;
les propositions serveur erronées doivent toutefois être remplacées avant
acceptation.

## H. Roadmap révision 2

**Verdict B — amendements requis avant approbation.** Le split A0 hors A3 est
correct. La roadmap reste à 4 phases et 17 étapes, mais la révision 2 ne doit
pas être approuvée en l'état.

Amendements : critères A0 sur non-transitivité et préflight/backfill ; flag
registration explicitement OFF jusqu'au gate ; A4 codable OFF après A0+A2
mais activable seulement après A0+A1+A2+A3 ; A5 après A3+A4 et inclut
l'enrôlement ; B5 dépend B2+B3+B4 ; C1 dépend A0+B2 ; C3 dépend A4+B5+B6 ;
promotion beta→stable sans rebuild.

Parallélisme final proposé : après DU-0, A0, A1, B1, B2 et B3 peuvent avancer
en parallèle ; A2 peut rejoindre après acceptation de la décision session.
B4 suit B1+B3 ; B5 suit B2+B3+B4 ; B6 suit B5 ; C1 suit A0+B2 ; C2 suit
A5+B6+C1 ; C3 suit A4+B5+B6 ; C4 clôture.

## I. Human Gate — validations exactes

Avant de clore DU-0, un administrateur humain doit :

1. accepter l'isolation projet (UUID `19922554-…`, DEC-0103) ;
2. accepter séparément A à E (UUID `bcf92622-…` DEC-0109, `4e509c7d-…`
   DEC-0110, `df4d6d3b-…`, `06d91e71-…`, `4f298c8f-…`) ; les anciennes
   propositions A/B sont déjà superseded ;
3. rejeter les propositions révision 2 (`ccf38500-…`) et révision 3
   (`7b132596-…`), puis accepter la révision 4
   (`6e458e81-e8d8-4934-8ccb-fac0c5ea0855`, base 1), identique à la
   révision 3 hormis les UUID A/B du critère DU0 ;
4. identifier chaque décision par son UUID. Seules les anciennes propositions
   serveur DEC-0097, DEC-0098 et DEC-0103 collisionnaient avec des ADR du
   dépôt ; DEC-0103…0108 n'ont aucune collision.

## J. Statut DU-0

**BLOCKED — awaiting human approval.** Les travaux d'analyse et de proposition
sont terminés. DU-0 ne doit pas passer `done`, et A0/A1/A2/B1… ne doivent pas
être démarrés ou hydratés par ce lot.

Graphify : mise à jour reportée par décision humaine (aucun envoi à Gemini
autorisé), à faire après acceptation des décisions, idéalement au démarrage
de A0. Non bloquant pour DU-0.

## K. Git

Branche au démarrage : `master` ; HEAD :
`65e81ea37fc062893049bbbff8a42464e4ba0b93`. Fichiers DU-0 créés/modifiés :
les six ADR ci-dessus, ce rapport et `docs/DU0_AUTH_PROJECT_DATA_AUDIT.md`.
Les changements préexistants hors périmètre sont préservés. Aucun commit et
aucun push n'ont été effectués. Claims de ressources et de tâches DU-0 libérés,
sessions DU-0 fermées ; tâches DU-0 laissées `blocked`, non claimées.

Note d'identifiants : collisions réelles seulement pour les anciennes
propositions serveur DEC-0097, DEC-0098 et DEC-0103 avec les ADR du dépôt du
même numéro. DEC-0099, DEC-0105 et DEC-0102 n'avaient pas de collision. Les
fichiers DU-0 portent l'UUID serveur canonique ; aucun fichier historique n'a
été écrasé.
