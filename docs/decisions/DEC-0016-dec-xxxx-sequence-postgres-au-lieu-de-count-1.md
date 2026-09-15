---
id: DEC-0016
title: '`DEC-XXXX` : sequence Postgres au lieu de `COUNT(*) + 1`'
status: active
date: '2026-09-13'
superseded_by: null
source: docs/DECISIONS.md
sync_hash: sha256:ad8876e6969731da87d357fb95d5596aca39ef9e91791a222502f32009ed40af
graphify_entities:
- kind: function
  node_id: services_api_src_studio_api_services_decisions_next_readable_id
  path: services/api/src/studio_api/services/decisions.py
  project: studio-os
  relation: fixes
  symbol: _next_readable_id
- kind: function
  node_id: services_api_src_studio_api_services_decisions_create_decision
  path: services/api/src/studio_api/services/decisions.py
  project: studio-os
  relation: concerns
  symbol: create_decision
- kind: file
  node_id: services_api_alembic_versions_0003_decisions_readable_id_sequence
  path: services/api/alembic/versions/0003_decisions_readable_id_sequence.py
  project: studio-os
  relation: concerns
  symbol: 0003_decisions_readable_id_sequence.py
- kind: file
  node_id: tests_api_test_decisions_concurrency
  path: tests/api/test_decisions_concurrency.py
  project: studio-os
  relation: verifies
  symbol: test_decisions_concurrency.py
---

# DEC-0016 — `DEC-XXXX` : sequence Postgres au lieu de `COUNT(*) + 1`

`_next_readable_id` lisait `COUNT(*)` sur `decisions` puis calculait
`count + 1` : deux creations concurrentes pouvaient lire le meme compte
avant que l'une ou l'autre n'ait commit, et obtenir le meme `readable_id`
(etape 2 de `docs/ROADMAP_CORRECTIONS_AUDIT.md`). Remplace par une sequence
Postgres dediee (`decisions_readable_id_seq`) : `nextval()` est atomique au
niveau du moteur, independant des transactions applicatives, et ne reutilise
jamais une valeur deja distribuee — y compris apres suppression d'une
decision, puisqu'une sequence n'est jamais decrementee. Le format public
`DEC-XXXX` est preserve (`f"DEC-{next_value:04d}"`).

Consequence acceptee : un `nextval()` suivi d'un rollback (ex. `create()`
echoue plus loin) laisse un trou dans la numerotation plutot que de reutiliser
la valeur — comportement standard d'une sequence (identique a une colonne
`SERIAL`), non couvert par une garantie de contiguite dans
`TECH/05_DATA_MODEL.md`. Aucun changement de contrat observable au sens de
`contract-change` : le format et l'unicite du `readable_id` sont preserves,
seule l'implementation de l'allocation change.

Migration Alembic `0003` : `CREATE SEQUENCE decisions_readable_id_seq`,
initialisee via `setval` au maximum des `readable_id` existants + 1 (0 + 1 si
la table est vide) pour ne pas entrer en collision avec des lignes deja
creees par l'ancien mecanisme. `downgrade()` supprime la sequence
(reversible ; aucune donnee des lignes `decisions` n'est touchee).

Regression couverte par `tests/api/test_decisions_concurrency.py`, sur le
meme modele que `test_idempotency_concurrency.py` (connexions Postgres
reellement separees, pool pre-chauffe) : dix creations de decision
concurrentes recoivent dix `readable_id` distincts.
