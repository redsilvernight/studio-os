---
id: DEC-0090
title: 'Roadmaps P10 : validation E2E finale, frontière de review par le rôle, provenance conservée et correction de l''ordre d''initialisation proposed'
status: proposed
date: '2026-09-20'
superseded_by: null
source: docs/DECISIONS.md
---

# DEC-0090 — Roadmaps P10 : validation finale et clôture

P10 est un *release gate*, pas une phase d'architecture : aucun contrat n'est modifié
(`API_CONTRACT_VERSION` et `EVENT_SCHEMA_VERSION` restent `1`), aucune migration. Elle
démontre le chantier P1→P9 de bout en bout, tranche deux ambiguïtés de contrat, corrige
le seul défaut Roadmaps révélé et clôt la documentation.

## Validation E2E

`tests/e2e/test_roadmaps_p10_e2e.py` (11 tests, Postgres réel, application HTTP réelle,
outils MCP réels, une transaction isolée) rejoue : Project → initialisation (preview,
apply, rejeu par clef et sans clef) → Roadmap (phases, dépendances, critères, liens,
progression) → hydratation (rejeu) → contexte borné → proposition d'agent (`pending`,
roadmap et contexte inchangés, file de review) → relecture humaine (diff, approbation,
événement, contexte mis à jour à l'appel suivant) → export. Variantes : `request_changes`
/ `reject` (commentaire obligatoire), base périmée, `expected_version` périmée,
permissions (`agent`, `readonly`), clef d'idempotence de proposition, initialisation par
un agent. Invariant « sans Roadmap » : projet nu, Task isolée, contexte, MCP, initialisation
sans section roadmap. Côté Dashboard, `dashboard/e2e/roadmap-p10.spec.ts` (5 tests) couvre
la file de review → onglet Roadmap, les erreurs d'API, une décision refusée, le bureau
1440 px et la mise en page A4 du PDF client. Agnosticisme : `tests/contracts/
test_roadmaps_agnosticism.py` (aucun nom de fournisseur ni champ d'identité de modèle dans
le domaine Roadmap).

## Décisions

1. **Auto-approbation — l'invariant est le rôle.** DEC-0085 (`RoadmapOrigin` : « garde-fou
   de workflow, pas une frontière de sécurité ; la frontière est le rôle »), DEC-0084 §6 et
   DEC-0089 (« `admin`/`developer` uniquement ») ne prévoient aucune séparation
   proposant/relecteur, et le modèle ne peut pas la garantir : l'identité d'agent est
   déclarée. Un jeton `developer` qui dépose une proposition sous un `agent_id` de sa
   machine peut donc la relire ; le rôle `agent` ne le peut jamais. Comportement conforme,
   verrouillé par `test_review_boundary_is_the_role_not_the_identity_of_the_proposer`. Une
   séparation stricte serait un nouveau contrat (hors P10).
2. **Provenance.** Vérifiée et testée (`test_provenance_survives_the_human_approval`) : la
   révision approuvée garde la provenance de l'auteur et gagne relecteur, date, décision,
   commentaire ; la révision résultante est la proposition ; une étape *créée* par
   l'approbation garde l'origine IA, une étape *modifiée* garde son créateur (l'édition est
   attribuée par la révision). Aucun défaut, aucun changement de code.
3. **Proposition en attente absente du contexte P6.** Ni P6 ni P8 ne l'exigent ; l'agent la
   lit dans `studio_get_roadmap.pending_proposals`. Contrat inchangé, choix documenté.
4. **Unit-of-Work d'initialisation.** Caractérisé, pas refactoré : le chemin nominal est
   rejouable et sans doublon (E2E). Le finding reste ouvert.

## Défaut corrigé

`apply_initialization` en `mode=proposed` importait la roadmap déjà soumise (`proposed`),
état gelé qui refuse tout nouveau lien (`ALLOWED_WRITES[proposed] = ∅`) : dès qu'une Task
du plan visait une étape (`roadmap_step_key`), l'apply échouait en `409 invalid_state`
*après* avoir committé projet, roadmap et Tasks, alors que le preview annonçait un plan
applicable ; le rejeu échouait pareillement. Le fake en mémoire du test unitaire ne
reproduisait pas la règle. Correctif minimal : importer en `draft`, lier, puis soumettre
(`roadmaps.submit_roadmap`, adaptateur additif du port qui réutilise la transition
`submit`), et faire d'un lien déjà présent un no-op même sur une roadmap gelée. Tests : E2E
`test_agent_initialization_is_a_proposal_a_human_validates`, unitaires
(`tests/services/test_initialization_service.py`, fake désormais fidèle à la règle).

Conséquences observables (relevées par `contract-guardian`) : la séquence d'événements
d'un apply `proposed` devient `roadmap.created`, un `roadmap.updated` par lien, puis
`roadmap.proposed` (dernier, payload inchangé) ; `roadmap.version` vaut 1 + liens + 1.
Chaque service commit seul : une panne entre les liens et la soumission laisse un
`draft`, que le rejeu du même plan soumet (le submit est un no-op hors `draft`). Test :
`test_replay_completes_the_submission_an_interrupted_apply_left_as_draft`. Le finding UoW
reste ouvert.

## Défaut de déploiement corrigé

L'image Docker du Dashboard ne se construisait pas : `dashboard/src/roadmapFixtures.ts`
(P7/P9) importe `../../contracts/fixtures/*.json`, hors du contexte `dashboard/` copié par
`docker/dashboard.Dockerfile` (`TS2307` à `npm run build`). Découvert au test de déploiement
local ; le Dockerfile copie désormais `contracts/fixtures` à ce chemin relatif.

Test de déploiement local (`docker/docker-compose.yml`, projet Compose isolé, images
construites depuis le code final, base vierge, migrations Alembic `head`, ports loopback ;
détruit après coup, la pile locale existante n'a pas été touchée) : santé API, Dashboard
servi, 26 chemins Roadmap/initialisation publiés, 42 outils MCP dont les 7 outils Roadmap
(aucun n'approuve), `studio_prepare_context` (section Roadmap, étape courante `S1`),
`studio_get_roadmap`, initialisation `draft` et `proposed` avec Task liée, rejeu sans
doublon. Le VPS public n'a pas été déployé.

## Export

Inchangé : le PDF utilisateur est la vue d'impression A4 du navigateur (`window.print()`) ;
`GET /roadmaps/{id}/export?format=pdf` reste `501 not_implemented`, contrat réservé.

## Limites assumées

- Enregistrée côté serveur (`proposed`, id `aeec66b2…`) sous le `readable_id` serveur
  `DEC-0089`, compteur non synchronisé avec les fiches (finding 5) : la fiche du dépôt
  fait foi.

- Le Dashboard est validé en E2E contre l'API simulée (`page.route`), comme les autres
  specs ; la pile réelle est couverte côté API/MCP.
- Findings post-Roadmaps inchangés (voir `docs/ROADMAPS_POST_FINDINGS.md`) : ni corrigés ni
  aggravés.
