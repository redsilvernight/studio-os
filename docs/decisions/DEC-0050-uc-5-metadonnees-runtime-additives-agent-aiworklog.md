---
id: DEC-0050
title: 'UC-5 : metadonnees runtime additives agent_profile/harness/provider/model sur Agent et AIWorkLog'
status: active
date: '2026-09-15'
superseded_by: null
source: docs/DECISIONS.md
---

# DEC-0050 — UC-5 : metadonnees runtime additives

Operationalise la partie « champs structures » de DEC-0043 amendee : les
metadonnees `agent_profile`, `harness`, `provider` et `model` deviennent des
champs additifs optionnels de `Agent` et `AIWorkLog`. Amende l'affirmation
« Aucun champ harness/provider/model/profil » de DEC-0045 point 1 : ces
champs existent desormais, mais restent strictement d'observabilite.

### Decision

1. `Agent` et `AgentCreate` (`packages/studio-contracts/.../auth.py`) gagnent
   `agent_profile`, `harness`, `provider`, `model` : `str | None = None`,
   chaines ouvertes, aucune valeur rejetee, aucun enum. `agent_kind` reste en
   place (champ historique libre, coexistence explicitement autorisee par
   DEC-0043 amendee : pas de seconde source de verite, aucun des deux n'entre
   dans l'autorisation).
2. `AIWorkLog` et `AIWorkLogCreate` (`.../ai_work.py`) gagnent les memes
   quatre champs optionnels : instantane du runtime qui a produit le travail.
3. Champs ajoutes nullables sur les tables `agents` et `ai_work_logs`
   (migration reversible `0006_agent_runtime_metadata`). Aucune valeur par
   defaut, aucune contrainte, aucun index, aucun backfill.
4. Les services `create_agent` et `create_ai_work` recopient les valeurs
   fournies, sans aucune validation de valeur ni branche conditionnelle.
5. **Interdit** : lire l'un de ces champs dans `authz.py` ou dans toute
   decision d'autorisation/de capacite. Aucun `if model/provider/harness ==`
   dans la logique metier. Un profil ou un modele « privilege » ne confere
   aucun droit.
6. `PATCH /ai-work` ne les modifie pas : ce sont des metadonnees de creation,
   pas des champs mutables.
7. Surface MCP inchangee : DEC-0046 autorise un subset additif ; les outils
   MCP existants n'exposent pas ces champs (HTTP reste canonique). Aucun
   outil MCP ne les lit pour decider.

### Consequences

- Un consommateur inconnu peut declarer (ou omettre) son runtime sans aucune
  consequence d'autorisation ; les champs apparaissent a `null` s'ils sont
  omis.
- `TECH/02` (Agents, ai-work) et `TECH/05` (Agent, AIWorkLog) documentent les
  nouveaux champs dans le meme changement. Les reponses OpenAPI gardent le
  contrat decouvrable (UC-2B) : aucune reference interne n'y fuit.
- Aucune garantie serveur sur la veracite de ces chaines : elles sont
  declaratives, au meme titre que `agent_kind`.

### Preuves

- `tests/api/test_uc5_runtime_metadata.py` (5 tests) : echo des valeurs
  inconnues, defaut `null`, coexistence, non-influence sur l'autorisation
  (`readonly` reste `403`, un profil « admin » ne confere rien) et sur la
  revue DEC-0041.
- `tests/api/test_uc1_unknown_consumer.py` adapte : un consommateur qui
  n'envoie aucune metadonnee obtient `null` et l'interface complete.
- Suite complete : 473 passed, 3 skipped ; `ruff check`/`format --check`,
  `mypy` strict verts sur le perimetre modifie.

### Compatibilite

Additif au sens des regles contracts (champs optionnels ignorables par les
anciens clients). Amende DEC-0045 point 1 sans contredire son principe
(registration publique, sans autorite). Compatible DEC-0043 amendee,
DEC-0041, DEC-0046, DEC-0048. Migration reversible.
