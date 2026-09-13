# Découpage de l'étape 4 — Périmètre Cloud/Core du Bloc A

Contexte : `docs/ROADMAP_CORRECTIONS_AUDIT.md`, étapes 1 à 3, closes par
5726f14 (DEC-0016, DEC-0017). Prochaine étape non traitée : **étape 4**
(P1/P2), volumineuse et hétérogène — elle est donc découpée ici en
sous-étapes indépendantes, chacune dimensionnée pour une session dédiée.
Ce fichier complète `docs/ROADMAP_CORRECTIONS_AUDIT.md` sans le remplacer ;
le cocher/mettre à jour au fil des clôtures (règle d'hygiène des CLAUDE.md —
ne pas dupliquer cet état ailleurs).

Périmètre cible (definition de done Bloc A) :
`docs/Studio_OS_Documentation_Pack/studio_os_docs/IMPLEMENTATION/02_BLOCK_A_PROMPT.md`.
Aucun mécanisme de realtime, quotas, retention ou backup n'existe
actuellement dans `services/api/src/studio_api/` — vérifié par lecture directe
de l'arborescence au moment de ce découpage (13 routers, aucun ne couvre ces
sujets ; pas de worker, pas de script de sauvegarde).

## Ordre recommandé et dépendances

1 → 2 et 3 (indépendantes entre elles) → 4 → 5. La 5 doit être la dernière
car elle valide l'ensemble sur une base vierge, migrations comprises.

## Sous-étape 4.1 — Realtime (transport + reprise) — CLOS

Transport SSE + curseur `seq`, decision et implementation : `docs/DECISIONS.md`
DEC-0018. `contract-guardian` (additif, mergeable) et `studio-tester`
(migration reversible verifiee en reel, idempotence/deconnexion/eviction de
file/curseur invalide verifies en reel) valides.

Ecart connu, non introduit par cette sous-etape : aucune autorisation par
projet/role n'existe nulle part dans l'API (`GET /events` a le meme manque
depuis toujours) — `GET /events/stream` reprend donc la meme portee
d'autorisation que l'existant plutot que d'en inventer une nouvelle pour ce
seul endpoint. Un correctif transverse (ACL par projet sur toute l'API) reste
a planifier separement si un besoin reel apparait.

### Problème
`TECH/03_EVENT_CONTRACT.md` ne tranche pas de transport realtime. Le champ
"realtime" de la définition de done du Bloc A (`02_BLOCK_A_PROMPT.md`) n'a
aucune implémentation.

### Travail attendu
1. Choisir le transport (WebSocket vs SSE vs polling long) par une entrée
   `docs/DECISIONS.md` (DEC-00XX) — critères : compatibilité offline/replay
   du Bloc B, simplicité côté Caddy/reverse-proxy, coût d'implémentation.
2. Définir le modèle de reprise après coupure (curseur/offset sur `events`,
   pas de perte, pas de doublon à la reconnexion).
3. Ajouter l'endpoint/canal realtime dans `services/api/src/studio_api/routers/`.
4. Si le comportement observable du contrat Event change (format de flux,
   nouveaux champs), dispatcher le skill `contract-change` puis
   `contract-guardian` avant merge.
5. Tests : connexion, coupure/reconnexion sans doublon, autorisation par
   projet/rôle.

### Critères d'acceptation
- Deux clients simulés reçoivent les mêmes événements en temps quasi réel.
- Une reconnexion après coupure ne recrée ni ne perd d'événement.
- `contract-guardian` validé si le contrat Event a changé.

## Sous-étape 4.2 — Quotas, limites de taille et vue de consommation (transferts) — CLOS

Quota par projet (DEC-0019), sans fenêtre temporelle : `docs/DECISIONS.md`
DEC-0019. `contract-guardian` (additif) et `studio-tester` (quota dépassé,
limite de taille, consultation de consommation vérifiés en réel contre
Postgres) à valider avant clôture définitive.

### Problème
`routers/transfers.py` gère la création de transferts mais aucune limite de
taille ni quota par projet/machine, ni vue de consommation.

### Travail attendu
1. Définir la politique (limite par transfert, quota par projet ou par
   machine, fenêtre de calcul) — trancher par DEC-XXXX si absent des docs.
2. Appliquer la limite à la création de transfert (rejet explicite si
   dépassement, cf. scénario "quota dépassé" de
   `TECH/10_TEST_ACCEPTANCE.md`).
3. Exposer une vue de consommation (endpoint ou champ existant enrichi).
4. Tests : dépassement de quota, limite de taille, consultation de la
   consommation.

### Critères d'acceptation
- Un transfert dépassant la limite est rejeté avec une erreur explicite,
  pas un échec silencieux côté stockage.
- La consommation reportée correspond aux transferts réels en base.

## Sous-étape 4.3 — Worker d'expiration/nettoyage des transferts

### Problème
Aucune politique de rétention n'est appliquée aux transferts expirés
(invariant projet : "aucun transfert non expiré n'est supprimé sans
politique explicite" — donc les transferts *expirés*, eux, doivent l'être
selon une règle documentée, actuellement absente).

### Travail attendu
1. Documenter la politique de rétention/expiration (durée, déclenchement,
   suppression MinIO + ligne DB) par DEC-XXXX si non déjà tranché.
2. Implémenter le worker (tâche planifiée ou job explicite déclenché par
   l'API — trancher le mécanisme, pas de dépendance à un scheduler externe
   non documenté).
3. Couvrir le scénario "suppression et expiration" de
   `TECH/10_TEST_ACCEPTANCE.md`.
4. Tests : transfert expiré supprimé, transfert non expiré jamais touché,
   ré-exécution idempotente du worker.

### Critères d'acceptation
- Un transfert expiré est supprimé (DB + objet MinIO) après exécution du
  worker.
- Un transfert non expiré n'est jamais supprimé, y compris après plusieurs
  exécutions du worker.

## Sous-étape 4.4 — Sauvegardes Postgres/MinIO et test de restauration

### Problème
Aucune procédure de sauvegarde/restauration documentée ou automatisée
actuellement (CLAUDE.md ne mentionne que la validation ponctuelle du
docker-compose, pas de backup).

### Travail attendu
1. Documenter la procédure de sauvegarde Postgres (dump logique a minima)
   et MinIO (sync objet ou snapshot bucket).
2. Automatiser (script ou tâche planifiée) — pas de solution manuelle
   uniquement.
3. Réaliser réellement une restauration complète sur un environnement de
   test et consigner la preuve (commande, date, résultat — pas d'affirmation
   sans exécution réelle, cf. CLAUDE.md du projet).

### Critères d'acceptation
- Une restauration Postgres + MinIO démontrée sur un environnement de test,
  preuve consignée dans `docs/DECISIONS.md` ou équivalent.

## Sous-étape 4.5 — Validation Docker Compose sur base vierge

### Problème
La dernière validation réelle du compose (DEC-0014) ne couvrait pas
nécessairement l'enchaînement complet migrations + sauvegardes + worker
d'expiration une fois les sous-étapes 4.1 à 4.4 fusionnées.

### Travail attendu
1. Relancer `docker compose up` depuis une base strictement vierge.
2. Exécuter la migration Alembic manuellement (toujours pas de migration
   auto au démarrage, sauf décision contraire).
3. Vérifier l'enchaînement complet : bootstrap admin, provisioning,
   realtime, transferts avec quotas, worker d'expiration, sauvegarde.
4. Mettre à jour CLAUDE.md du projet et `docs/DECISIONS.md` avec l'état réel
   vérifié (pas de suppositions).

### Critères d'acceptation
- Un poste neuf peut suivre la séquence documentée sans étape manquante ni
  supposition non vérifiée.

## Rappels transverses (valables pour 4.1 à 4.5)

- Dispatcher `studio-tester` après chaque sous-étape terminée.
- Dispatcher `contract-guardian` pour toute sous-étape touchant un contrat
  (4.1 et potentiellement 4.2).
- Mettre à jour Graphify au point de complétion de chaque sous-étape
  (`brainstormer`, pas de mise à jour incrémentale à chaque fichier).
- Ne cocher une case de `IMPLEMENTATION/04_INTEGRATION_CHECKLIST.md` que sur
  preuve reproductible (étape 10 de l'audit).
