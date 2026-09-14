---
id: DEC-0031
title: 'Sous-etape 6.5 (CLI minimale) : sous-commandes argparse au-dessus de `StudioApiClient`,
  cle d''idempotence generee par la CLI'
status: active
date: '2026-09-14'
superseded_by: null
source: docs/DECISIONS.md
sync_hash: sha256:f165c772ceb4813e2611be2ffac225d4830dbe78adad5bb9402b27dcd2478397
graphify_entities:
- kind: method
  node_id: packages_studio_client_src_studio_client_api_client_studioapiclient_claim_task
  path: packages/studio-client/src/studio_client/api_client.py
  project: studio-os
  relation: implements
  symbol: StudioApiClient.claim_task
- kind: method
  node_id: packages_studio_client_src_studio_client_api_client_studioapiclient_release_task
  path: packages/studio-client/src/studio_client/api_client.py
  project: studio-os
  relation: implements
  symbol: StudioApiClient.release_task
- kind: function
  node_id: packages_studio_client_src_studio_client_cli_build_parser
  path: packages/studio-client/src/studio_client/cli.py
  project: studio-os
  relation: implements
  symbol: build_parser
- kind: function
  node_id: packages_studio_client_src_studio_client_cli_main
  path: packages/studio-client/src/studio_client/cli.py
  project: studio-os
  relation: implements
  symbol: main
---

# DEC-0031 — Sous-etape 6.5 (CLI minimale) : sous-commandes argparse au-dessus de `StudioApiClient`, cle d'idempotence generee par la CLI

Etudie sans `studio-architect` (meme principe que 6.2-6.4 : consomme des
endpoints deja contractualises depuis 6.1, aucune frontiere de contrat
nouvelle).

### Probleme

`StudioApiClient` (6.1) ne portait que les methodes minimales
(`healthz`/`list_projects`/`get_project_state`/`send_heartbeat`/
`post_event`/`create_task`) ; rien ne couvrait tasks/sessions/claims en
lecture ni claim/release/renew, et aucune interface humaine/scriptable
n'existait au-dessus — chaque operation exigeait un appel HTTP manuel.

### Decision

- `api_client.py` : nouvelles methodes miroir du style deja en place —
  `list_tasks`/`get_task`/`update_task`/`claim_task`/`release_task`,
  `list_sessions`/`start_session`/`end_session`,
  `list_claims`/`create_claim`/`renew_claim`/`release_claim`.
  `Idempotency-Key` uniquement sur les trois creations
  (`create_task`/`start_session`/`create_claim`, seules a la declarer
  cote routeur, `TECH/02_API_CONTRACT.md`) ; `update_task` porte
  `If-Match-Version` ; `claim_task`/`release_task`/`renew_claim`/
  `release_claim` ne sont jamais marquees `idempotent=True` — pas de
  retry automatique la ou le serveur n'offre aucun rejeu sur, cf. le meme
  principe que DEC-0024.
- `cli.py` reecrit : sous-commandes `studio-client {projects,tasks,
  sessions,claims} <verbe>` (argparse, stdlib seul — pas de nouvelle
  dependance CLI), flag `--json` par sous-commande pour la sortie
  scriptable (sinon `str()` du modele Pydantic). La cle `Idempotency-Key`
  d'une creation est generee dans la CLI (`uuid4()` par invocation),
  jamais dans `StudioApiClient` lui-meme (DEC-0024 inchangee).
  `TaskUpdate` est construit uniquement avec les champs explicitement
  fournis (`--title`/`--description`/`--status`), jamais tous les champs
  a `None`, pour que `model_dump(exclude_unset=True)` cote client
  n'ecrase pas un champ non fourni cote serveur
  (`tasks_service.update_task` ne touche que `if task_in.X is not None`).
  `sessions start` exige `ClientConfig.machine_id` deja configure
  (erreur explicite sinon, pas de valeur inventee). `login` (6.1) reste
  interceptee avant le parsing argparse generique du reste de la CLI —
  elle n'a pas besoin d'un `ClientConfig` complet.

### Consequences

Aucun changement de contrat, aucune nouvelle dependance (argparse est
stdlib). Le point d'entree installe (`studio-client`, `pyproject.toml`)
n'etait exerce par aucun test automatise (seule la couche
`StudioApiClient` l'est, via mock/`ASGITransport`) — comble par une
verification manuelle reproductible (voir Preuves) plutot que par un
test automatise supplementaire, pour rester dans le perimetre de cette
sous-etape.

### Preuves

`packages/studio-client/src/studio_client/api_client.py`, `cli.py`.
`tests/client/test_api_client.py` (+6 tests mock : filtre `project_id`
sur `list_tasks`, `If-Match-Version` + champs non fournis exclus sur
`update_task`, chemins `claim`/`release`, propagation de
l'`Idempotency-Key` sur `start_session`/`create_claim`, `release_claim`
tolere un `204` sans corps) et `test_api_client_against_app.py` (+3
tests contre l'app reelle : cycle tache claim/release, session
start/end, claim create/renew/release). Suite `tests/client/` et suite
complete du depot : **193 passed** (Postgres 16 + MinIO reels), aucun
echec — obtenu deux fois independamment (agent principal, puis
`studio-tester`). `ruff check .`, `ruff format --check .` et
`mypy packages/studio-contracts/src packages/studio-client/src
services/api/src services/mcp/src` (strict, commande CI reelle) verts.
Revue independante `studio-tester` : aucun bug bloquant, endpoints/
verbes/headers verifies contre les routeurs reels
(`services/api/src/studio_api/routers/{tasks,sessions,claims}.py`).
Verification manuelle du point d'entree installe (`uv run --package
studio-client studio-client ...`) contre un serveur reel demarre pour
l'occasion (Postgres 16 dedie, migrations Alembic, bootstrap
`studio-admin`) : `projects list`, `tasks {create,list,claim,update,
release}`, `sessions {start,list,end}`, `claims {create,renew,release,
list}` executes reellement avec succes, plus un cas d'erreur (`tasks
show` sur un id inexistant -> `error: task not found (404)`, code de
sortie 1, aucune trace brute). Environnement de verification
demonte apres coup (conteneurs Docker supprimes, process serveur
arrete).
