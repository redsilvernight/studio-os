---
id: DEC-0055
title: 'UC-7 : tests de conformance dun client inconnu (unknown-harness/provider/model,
  sans profil)'
status: active
date: '2026-09-15'
superseded_by: null
source: docs/DECISIONS.md
sync_hash: sha256:4b285bf45c661dabf5eb25a0b625fab31acf66b37a1bf2526b52379b49e9e651
---

# DEC-0055 — UC-7 : tests de conformance dun client inconnu (unknown-harness/provider/model, sans profil)

Verrouille par test le critere d'acceptation : « A previously unknown AI
agent/harness/provider/model can integrate with Studi'OS without modification
of the Studi'OS core », et « aucun identifiant de modele, provider, harness ou
profil ne sert d'entree a une decision d'autorisation ou de capacite ».
Complete les tests UC-1 (`unknown consumer`, sans ligne Agent) et UC-2B
(decouverte par OpenAPI seul) par une verticale complete.

### Decision

1. Nouveau `tests/api/test_uc7_unknown_consumer_conformance.py`. Le client
   fictif utilise uniquement les interfaces publiques, avec
   `harness=unknown-harness`, `provider=unknown-provider`,
   `model=unknown-model`, sans `agent_profile` prealable, et exerce :
   `/healthz` sans credential, detection d'absence par `404`, enregistrement
   d'Agent, heartbeat, tache (claim/release), event (rejeu idempotent sans
   doublon verifie via `GET /events`), worklog avec revue admin-only
   preservee, et transfert single-PUT via MinIO (octets jamais via l'API).
2. Un test de parite de capacites verifie que deux declarations de runtime
   differentes (dont une aux valeurs « privilegiees ») obtiennent les memes
   droits : le coeur ne branche sur aucune valeur.
3. Un test verifie que `POST /transfers` ne renvoie jamais d'octets, et que
   `upload/initiate` renvoie une URL pre-signee.
4. Les tests UC-1 et UC-5 existants restent la reference de la non-exigence
   de metadonnees ; UC-7 ne les remplace pas, il etend la couverture.

### Consequences

- Toute regression introduisant une exigence de harness/provider/modele ou un
  branchement d'autorisation sur ces valeurs fera echouer un test public.
- Le test est un vrai client (httpx brut + MinIO reel), pas un mock de la
  reference Python : il ne suppose ni `packages/studio-client` ni aucun
  harness.

### Preuves

- `tests/api/test_uc7_unknown_consumer_conformance.py` (3 tests) verts.
- Suite complete : 473 passed, 3 skipped.

### Compatibilite

Tests uniquement ; aucun contrat ni code de production modifie. S'appuie sur
UC-1 (DEC-0045), UC-5 (DEC-0053) et le Universal Consumer Contract.
