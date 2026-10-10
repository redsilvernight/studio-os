# Mission Control — mesures baseline P01

Mesures du 10 octobre 2026 pour l'étape `P01-metrics` de la roadmap
`c289fb39-6486-4d6a-b395-527391124b19`, tâche `40148cc2-060e-4e8d-8a5c-37acf89f1ac9`.
Base de code : `dev` au commit `56778a17`. Les chiffres C5 ne sont pas repris comme
baseline (consigne de [baseline.md](baseline.md#L312)).

Trois jeux de mesures, chacun reproductible par sa commande :

| Jeu | Source | Commande | Sortie machine |
|---|---|---|---|
| Contexte et bruit (backend) | services réels sur PostgreSQL de test, scénario seedé | `uv run python -m scripts.mission_metrics --root . --apply` | [metrics.json](metrics.json) |
| Budget UI | Playwright sur mocks, build du dashboard | `npm run build` puis `P01_METRICS_WRITE=1 npx playwright test e2e/p01-metrics.spec.ts` (dans `dashboard/`) | [p01-metrics.json](../../dashboard/e2e/p01-metrics.json) |
| Couverture de collecte | journal `ai_work` du serveur connecté + stockage local des harness | lecture MCP `studio_get_ai_work(limit=200)` ; inventaire ci-dessous | ce document |

`--check` valide la structure de `metrics.json` sans base de données.

## Couverture de collecte

### Journal `ai_work` du serveur connecté

Échantillon : les 200 entrées les plus récentes du projet, du 2026-09-26 19:10 au
2026-10-10 06:34 UTC (252 entrées existent au total), 11 agents distincts.

| Mesure | Valeur | Lecture |
|---|---|---|
| Statuts | 192 `completed`, 4 `started`, 2 `review_requested`, 2 `approved` | — |
| Rattachées à une tâche | 193 / 200 (96,5 %) | attribution par tâche exploitable |
| Rattachées à une session | 110 / 200 (55 %) | attribution par run incomplète |
| Durée nulle (`ended_at` = `started_at`) | 182 / 192 terminées (94,8 %) | entrées journalisées en une fois à la fin |
| Durée positive | 10 / 192 (5,2 %) | seule durée mesurable aujourd'hui |
| `harness`, `provider`, `model`, `agent_profile` | **inconnu** : champs refusés par l'outil MCP connecté (`unknown fields`) | colonnes présentes dans le modèle `dev`, non exposées en lecture par ce serveur |
| Tokens, coût | **inconnu** : aucun champ dans `AIWorkModel` | jamais compté comme 0 |

Conséquence : la durée d'AIWork n'est pas une mesure de temps actif (déjà noté dans
la baseline, section G) ; elle est absente dans 95 % des cas.

### Données disponibles côté harness (poste de mesure)

| Harness | Source locale | Tokens | Coût | Modèle | Rattachement Studio OS |
|---|---|---|---|---|---|
| Claude Code 2.1.x | transcript JSONL `~/.claude/projects/*/*.jsonl`, champ `usage` par message | entrée, sortie, cache création/lecture, réflexion | **absent** : à estimer par grille tarifaire, marqué estimé | oui | aucun ; via `session_id` du hook à relier |
| OpenCode 1.18.x | SQLite `~/.local/share/opencode/opencode.db`, table `session` | entrée, sortie, réflexion, cache lecture/écriture | **présent** (`cost`) | oui (`model`) | aucun ; via id de job dispatch / worktree |
| Codex CLI 0.162 | rollout JSONL `~/.codex/sessions/AAAA/MM/JJ/*.jsonl`, événements `token_count` | cumul entrée, cache, sortie, réflexion | **absent** | à confirmer | aucun |

Lecture seule ; aucun contenu de conversation ni identifiant d'authentification n'a
été lu ou copié. Ces formats sont internes aux outils et peuvent changer : P03-collector
doit les certifier par version.

## Contexte et bruit (backend)

Mesure du 2026-10-10 12:26 UTC, `dev` `56778a17`, PostgreSQL 16.15, Alembic `0029`,
Python 3.14.7, Windows 11. Scénario seedé (graine `20261009`) : 1 projet, 2 machines et
agents, 20 tâches, 5 claims, 30 `ai_work`, 1 roadmap ; 2 passes d'échauffement puis
10 échantillons par appel (40 appels mesurés), `limit=5`, `max_chars=12000`.
Détail complet : [metrics.json](metrics.json).

| Appel | Tokens ≈ (car./4) | p50 | p95 | max |
|---|---|---|---|---|
| `start_work` avec tâche | 3 021 | 93,4 ms | 165,2 ms | 211,1 ms |
| `start_work` sans tâche | 2 405 | 71,5 ms | 80,4 ms | 85,2 ms |
| `prepare_project_context` | 2 468 | 61,5 ms | 72,7 ms | 75,1 ms |
| `sync` | 209 | 29,2 ms | 37,1 ms | 41,3 ms |

Latences en processus (services appelés directement), hors réseau, HTTP et MCP.

Bruit sur le scénario : 92 événements, dont 60 `ai_work.*` pour 30 `ai_work_id`, soit
**2,0 événements par `ai_work_id`** (paire `started`/`completed`, cf. DEC-0165 D5) et
3,07 tous types confondus. Dix `sync` sans `ack` renvoient 40 items pour 4 entités
uniques (36 répétitions) : c'est le rejeu attendu sans acquittement, et la mesure du
coût d'un client qui n'acquitte pas.

## Budget UI

Mesure du 2026-10-10 12:31 UTC, `dev` `56778a17`, Chromium Playwright 1440×900, API
simulée (stubs `p06-targets` / `ui16-stub`), build `dist/`. Définitions de
[targets.md](../ux/desktop-dashboard-v2/targets.md) ; détail :
[p01-metrics.json](../../dashboard/e2e/p01-metrics.json).

| Écran | Éléments majeurs (≤ 7) | UUID visibles (0) | Indicateurs de connexion (1) |
|---|---|---|---|
| Accueil | 6 | 0 | 1 |
| Travail | 5 | 0 | 1 |
| À valider | 3 | 0 | 1 |
| Projet | 6 | 0 | 1 |
| Roadmap | 4 | 0 | 1 |
| Fiche tâche | 5 | 0 | 1 |

Parcours S1–S4 : 1 / 1 / 0 / 2 clics pour des cibles 1 / 2 / 2 / 2.
**Seul dépassement : JS initial 74,70 kB gzip pour une cible de 60 kB** (fermeture des
imports statiques depuis `dist/index.html`, même valeur que `npm run analyze:bundle`),
suivi par la tâche existante `f39aad38`. Un dépassement est marqué `over_budget` et
ne fait pas échouer le test ; la baseline n'est réécrite qu'avec `P01_METRICS_WRITE=1`.

Le contrôle humain chronométré (C1, ≥ 90 % de réponses justes en ≤ 5 s) n'est **pas**
réalisé ici ; il est prévu aux jalons P05 et P06.

## Seuils proposés (à approuver)

Chaque gain futur se compare à ces valeurs ; un seuil n'est actif qu'après
approbation humaine (décision Studio OS).

| Métrique | Baseline | Seuil proposé | Étape qui le vérifie |
|---|---|---|---|
| Entrées `ai_work` avec durée positive | 5,2 % | ≥ 90 % des runs lancés via TaskLaunch | P03-collector |
| Entrées rattachées à une session | 55 % | ≥ 95 % | P02-protocol-proof |
| Runs avec tokens mesurés (par harness pilote) | 0 % (inconnu côté serveur) | ≥ 95 % ; inconnu affiché « inconnu » | P03-gate |
| Taille `start_work` avec tâche | ≈ 3 021 tokens | ≤ 3 021 tokens à scénario égal | P02-noise |
| Latence p95 `start_work` avec tâche | 165 ms (en processus) | ≤ 250 ms (seuil P16 existant) | P02-read-model |
| Événements par `ai_work_id` | 2,0 | ≤ 1,1 | P02-noise |
| Budget UI (éléments max, UUID, connexion) | 6 / 0 / 1 | ≤ 7 / 0 / 1 après ajout de Mission Control | P02-mission-ui |
| JS initial gzip | 74,70 kB | ≤ 60 kB (tâche `f39aad38`) ; Mission Control n'ajoute rien au chargement initial | P02-mission-ui |

## Métriques manquantes

- Coût réel par run : aucun collecteur ; Claude Code et Codex ne l'exposent pas.
- Version et SHA réellement déployés (serveur, Desktop, daemon) : inconnus, cf. baseline.
- Latence et taille mesurées sur le serveur de production : non mesurées ; seules les
  mesures sur PostgreSQL de test locale sont reproductibles.
- Contrôle humain chronométré : non réalisé.
