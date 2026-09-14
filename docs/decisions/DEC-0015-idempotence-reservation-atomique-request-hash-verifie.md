---
id: DEC-0015
title: 'Idempotence : reservation atomique + `request_hash` verifie'
source: docs/DECISIONS.md
sync_hash: sha256:0202338c0c80ea179c207cf33265b0878ed4360a97e9c0e519bfada28067647b
---

# DEC-0015 — Idempotence : reservation atomique + `request_hash` verifie

`run_idempotent` executait la creation metier avant de reserver la paire
(`Idempotency-Key`, endpoint) : deux requetes concurrentes reelles pouvaient
donc chacune creer leur propre ressource, seule la table d'idempotence
finissant par n'avoir qu'une ligne (etape 1 de
`docs/ROADMAP_CORRECTIONS_AUDIT.md`). Corrige par une reservation Postgres
atomique : `INSERT ... ON CONFLICT (idempotency_key, endpoint) DO NOTHING`
avec `status=pending`, executee et commit **avant** d'appeler `create()`. Le
gagnant execute la creation metier puis marque la ligne `completed` avec la
reponse ; un perdant relit la ligne (`populate_existing` pour eviter un
retour d'objet du cache d'identite SQLAlchemy) et, si elle est encore
`pending`, la poll (jusqu'a 5s, borne) jusqu'a ce qu'elle passe `completed`.
Une creation qui echoue supprime la reservation `pending` (pas de cle
bloquee, pas de reponse fantome). Ce mecanisme est un artefact PostgreSQL
partage entre processus, pas un verrou local — sur plusieurs instances API.

Trou de liveness identifie par `contract-guardian` a la revue : si le
processus proprietaire d'une reservation crashe (kill -9) entre le commit de
`_reserve` et `_complete`/`_release`, aucun code Python ne s'execute pour la
liberer — la ligne restait `pending` indefiniment et bloquait la cle a vie.
Corrige par `_reclaim_if_abandoned` : une reservation `pending` plus vieille
que `_PENDING_RECLAIM_SECONDS` (30s, tres genereux face aux creations
metier couvertes ici — de simples inserts mono-ligne) est reclamee par un
`UPDATE ... WHERE status='pending' AND created_at<cutoff RETURNING id`, dont
la clause `WHERE` sert elle-meme de garde-fou atomique (un seul retentateur
concurrent peut matcher et gagner). Un client qui retente avec backoff borne
(`.claude/rules/offline-sync.md`) finit donc par debloquer une cle abandonnee
au lieu de rester bloque indefiniment ; le seuil de 30s est choisi assez
large pour ne jamais reclamer une creation legitimement encore en cours.

`request_hash` etait stocke mais jamais verifie : rejouer une cle avec un
corps de requete different renvoyait silencieusement la premiere reponse,
quel que soit le nouveau corps. Retenu : c'est desormais une erreur client
explicite (`409 {"error_code": "idempotency_key_payload_mismatch"}`), jamais
un rejeu silencieux ni une seconde ressource — semantique alignee sur
l'usage etabli de l'en-tete `Idempotency-Key` (meme cle = meme requete
logique). Documente dans `TECH/02_API_CONTRACT.md`, revu par
`contract-guardian` (changement de comportement observable, meme si aucun
client reel n'existe encore pour en dependre).

Migration Alembic `0002` : colonne `status` (`pending`/`completed`) ajoutee
a `idempotency_keys`, `response_status`/`response_body` rendues nullable
(une ligne `pending` n'a pas encore de reponse). Reversible.

Fichiers modifies : `services/api/src/studio_api/services/idempotency.py`,
`services/api/src/studio_api/db/models/idempotency.py`,
`services/api/alembic/versions/0002_idempotency_reservation.py`. Aucun
router n'a change — les sept endpoints (`tasks`, `claims`, `decisions`,
`transfers`, `sessions`, `ai-work`, `projects`) appellent tous
`run_idempotent` de la meme facon, donc la correction s'applique
uniformement sans toucher a leur code.

Regression couverte par `tests/api/test_idempotency_concurrency.py` : dix
requetes HTTP reellement concurrentes (connexions Postgres separees,
pool pre-chauffe pour eviter que la latence de connexion masque la course)
avec la meme `Idempotency-Key` ne creent plus qu'une seule `Task` (reproduit
et confirme le doublon sur le code d'avant correction, verifie de facon
deterministe sur 3 executions avant/5 apres), rejeu avec corps different
rejete en 409, une creation echouee (slug de projet deja pris) ne laisse pas
de reservation bloquee et peut etre retentee proprement, et une reservation
`pending` artificiellement vieillie (simulant un crash) est reclamee par un
retry plutot que de bloquer la cle.

Migration `0002` `downgrade()` : une ligne `pending` n'a pas de reponse a
conserver et empeche l'`ALTER COLUMN ... SET NOT NULL` sur
`response_status`/`response_body` — `downgrade()` supprime d'abord les
lignes `status='pending'` (jamais une reponse `completed`) avant de
restaurer les contraintes `NOT NULL`.

Limite connue, non couverte par ce correctif : `request_hash` est un hash
SHA-256 du corps brut de la requete (octet-exact), pas une comparaison
semantique du JSON. Un client qui reserialise un JSON logiquement identique
avec un ordre de cles ou un formatage different lors d'un retry legitime
declencherait a tort `409 idempotency_key_payload_mismatch`. Pas encore
observable (aucun client Bloc B reel n'existe), a surveiller quand ce client
existera — hors perimetre de l'etape 1 de la roadmap (course sous
concurrence), qui porte sur l'atomicite de la creation, pas sur la
canonicalisation du payload.

Deuxieme limite connue, identifiee par `contract-guardian` a la deuxieme
revue : `_reclaim_if_abandoned` detecte une **anciennete**
(`created_at < cutoff`), pas un crash confirme — il n'existe pas de jeton de
fencing ni de renouvellement de bail. Un processus qui n'a pas crashe mais
met plus de `_PENDING_RECLAIM_SECONDS` (30s) a executer `create()`
(contention DB, pause GC, disque lent) peut se faire reclamer sa reservation
par un retry ; si ce processus original revient ensuite et appelle
`_complete`, il ecrase silencieusement la ligne `completed` deja posee par
le second — deux ressources metier auraient alors ete creees, ce que cette
etape de la roadmap vise justement a eliminer. La formulation absolue de
`TECH/02_API_CONTRACT.md` et `TECH/04_AUTH_SYNC_CONTRACT.md` a ete
assouplie en consequence (garantie bornee par le seuil de reclamation, pas
absolue en toute circonstance). Risque juge faible et proportionne a
l'etape 1 (30s est tres genereux pour de simples inserts mono-ligne, et
aucun client Bloc B reel n'existe encore pour l'exposer) — un jeton de
fencing ou un renouvellement de bail explicite serait une refonte hors
perimetre de cette etape ; a traiter si un scenario reel de creation lente
(>30s) apparait.
