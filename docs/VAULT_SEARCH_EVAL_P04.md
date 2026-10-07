# Évaluation de la recherche du vault — P04 (roadmap vault serveur)

- Projet temporaire : évaluation sur PostgreSQL (`tests/eval/dec_corpus.json` chargé en notes)
- Corpus : `tests/eval/dec_corpus.json` (159 décisions)
- Requêtes : `tests/eval/dec_queries.json` (45 objectifs)
- Recherche : `studio_api.services.vault.search_notes` (limit=5, max_chars=12000)
- Tokens : approximation `ceil(caractères / 4)` sur `titre + résumé + extrait` effectivement retournés (la recherche ne renvoie jamais le corps)

## Méthodologie

Le corpus versionné est inséré comme notes `decision` d'un projet jetable sur un
vrai PostgreSQL, puis chaque objectif est rejoué via le service de recherche réel
(classement par ancre, lien puis lexical — couverture des termes, titre ×3, `ts_rank_cd` en départage). Le service et le
classement ne sont pas modifiés en lecture ; le projet et ses notes sont supprimés
en fin d'exécution. Les requêtes n'ont pas de `task_id` : elles mesurent le
recouvrement lexical, seule relation disponible pour un objectif libre.

## Agrégat P00 vs P04

| Métrique | P00 | P04 |
|---|---|---|
| Requêtes | 45 | 45 |
| Réponses vides | 0.0 % | 0.0 % |
| Précision micro | 25.7 % | 25.8 % |
| Rappel micro | 75.0 % | 76.3 % |
| Précision macro | 26.0 % | 25.8 % |
| Rappel macro | 79.6 % | 79.6 % |
| Notes retournées | 222 | 225 |
| Vrais positifs | 57 | 58 |
| Tokens par appel (moyenne) | 753.93 | 366.09 |
| Tokens par résultat (moyenne) | — | 73.22 |

Le rappel micro P04 est de 76.3 % pour un budget de 366.09 tokens par appel, contre 75.0 % / 753.93 en P00.

## Détail par requête

| id | objectif | attendues | rappel P00 | retournées P04 | rappel P04 | tokens P04 |
|---|---|---|---|---|---|---|
| q01 | Corriger l'intégrité d'upload d'un transfert simple via Content-MD5 | DEC-0025 | 100.0 % | DEC-0025, DEC-0054, DEC-0106, DEC-0011, DEC-0020 | 100.0 % | 368 |
| q02 | Reprendre un upload multipart après expiration des URLs pré-signées | DEC-0037, DEC-0033 | 100.0 % | DEC-0037, DEC-0034, DEC-0033, DEC-0020, DEC-0025 | 100.0 % | 355 |
| q03 | Ajouter un worker d'expiration des transferts et son job CLI | DEC-0020, DEC-0019 | 100.0 % | DEC-0020, DEC-0121, DEC-0165, DEC-0031, DEC-0159 | 50.0 % | 367 |
| q04 | Rendre les appels réseau boto3 asynchrones via asyncio.to_thread | DEC-0026 | 100.0 % | DEC-0026, DEC-0184, DEC-0134, DEC-0080, DEC-0071 | 100.0 % | 372 |
| q05 | Modifier le Git watcher pour supporter plusieurs repositories | DEC-0032 | 100.0 % | DEC-0136, DEC-0115, DEC-0095, DEC-0079, DEC-0068 | 0.0 % | 322 |
| q06 | Trancher entre SSE et WebSocket pour les flux temps réel | DEC-0008, DEC-0018 | 100.0 % | DEC-0008, DEC-0156, DEC-0018, DEC-0134, DEC-0164 | 100.0 % | 333 |
| q07 | Mettre en place un fan-out temps réel multi-process via NOTIFY PostgreSQL | DEC-0156, DEC-0018 | 50.0 % | DEC-0156, DEC-0025, DEC-0134, DEC-0164, DEC-0011 | 50.0 % | 286 |
| q08 | Ajouter une file de review pour les propositions de roadmap | DEC-0087, DEC-0049 | 50.0 % | DEC-0087, DEC-0089, DEC-0088, DEC-0084, DEC-0083 | 50.0 % | 372 |
| q09 | Créer et versionner le domaine Roadmap (cycle de vie, provenance) | DEC-0084, DEC-0085 | 100.0 % | DEC-0084, DEC-0085, DEC-0120, DEC-0086, DEC-0107 | 100.0 % | 418 |
| q10 | Ajouter la section roadmap au contexte borné studio_prepare_context | DEC-0086, DEC-0080 | 100.0 % | DEC-0086, DEC-0080, DEC-0085, DEC-0159, DEC-0125 | 100.0 % | 386 |
| q11 | Ajouter les filtres status et mine à la liste des tâches | DEC-0185 | 100.0 % | DEC-0185, DEC-0161, DEC-0164, DEC-0184, DEC-0082 | 100.0 % | 377 |
| q12 | Déprécier les outils MCP redondants de session et de claim | DEC-0186 | 100.0 % | DEC-0186, DEC-0183, DEC-0135, DEC-0184, DEC-0157 | 100.0 % | 378 |
| q13 | Versionner les définitions de l'AI Library par pointeur actif | DEC-0064, DEC-0065 | 50.0 % | DEC-0064, DEC-0075, DEC-0134, DEC-0136, DEC-0065 | 100.0 % | 383 |
| q14 | Configurer les choix de runtime par utilisateur (bindings User/Runtime) | DEC-0068, DEC-0070 | 50.0 % | DEC-0068, DEC-0012, DEC-0184, DEC-0070, DEC-0123 | 100.0 % | 380 |
| q15 | Exposer la Library via une surface HTTP canonique | DEC-0071, DEC-0072 | 50.0 % | DEC-0071, DEC-0046, DEC-0057, DEC-0075, DEC-0076 | 50.0 % | 408 |
| q16 | Résoudre le scope et le shadowing d'une définition Library | DEC-0065, DEC-0069 | 50.0 % | DEC-0065, DEC-0063, DEC-0075, DEC-0067, DEC-0068 | 50.0 % | 344 |
| q17 | Définir les relations typées entre définitions (Library Bindings) | DEC-0067 | 100.0 % | DEC-0067, DEC-0068, DEC-0075, DEC-0063, DEC-0064 | 100.0 % | 385 |
| q18 | Authentifier l'humain sur le dashboard par un JWT court | DEC-0056, DEC-0142 | 50.0 % | DEC-0056, DEC-0110, DEC-0076, DEC-0035, DEC-0090 | 50.0 % | 317 |
| q19 | Mettre en place un refresh token rotatif pour la session desktop | DEC-0142, DEC-0056 | 50.0 % | DEC-0142, DEC-0182, DEC-0083, DEC-0117, DEC-0110 | 50.0 % | 367 |
| q20 | Ajouter le shell desktop Tauri 2 autour du dashboard | DEC-0090, DEC-0095 | 50.0 % | DEC-0090, DEC-0142, DEC-0076, DEC-0094, DEC-0093 | 50.0 % | 367 |
| q21 | Mettre en place un daemon unique supervisé côté desktop | DEC-0094, DEC-0028 | 50.0 % | DEC-0094, DEC-0142, DEC-0162, DEC-0125, DEC-0117 | 50.0 % | 388 |
| q22 | Générer les projections Claude Code et OpenCode depuis .agents | DEC-0074, DEC-0093 | 50.0 % | DEC-0074, DEC-0172, DEC-0123, DEC-0167, DEC-0083 | 50.0 % | 318 |
| q23 | Robustifier le bootstrap permanent et ses cibles d'actions manuelles | DEC-0172, DEC-0181 | 100.0 % | DEC-0172, DEC-0181, DEC-0157, DEC-0011, DEC-0183 | 100.0 % | 392 |
| q24 | Lancer un harness de façon non interactive avec un timeout dur | DEC-0176, DEC-0173, DEC-0177 | 33.3 % | DEC-0176, DEC-0182, DEC-0179, DEC-0175, DEC-0095 | 33.3 % | 397 |
| q25 | Fournir un credential éphémère de lancement lié à la tâche | DEC-0175, DEC-0173 | 50.0 % | DEC-0182, DEC-0035, DEC-0190, DEC-0175, DEC-0094 | 50.0 % | 369 |
| q26 | Charger un bundle offline fusionnant .agents et la Library | DEC-0168 | 100.0 % | DEC-0168, DEC-0167, DEC-0062, DEC-0067, DEC-0066 | 100.0 % | 396 |
| q27 | Ajouter le catalogue des machines actives avec statut heartbeat | DEC-0082 | 100.0 % | DEC-0082, DEC-0035, DEC-0039, DEC-0028, DEC-0003 | 100.0 % | 385 |
| q28 | Rendre l'autorisation transverse minimale par rôle et propriété | DEC-0036, DEC-0063 | 100.0 % | DEC-0036, DEC-0052, DEC-0079, DEC-0089, DEC-0063 | 100.0 % | 358 |
| q29 | Documenter le parcours d'intégration d'un consommateur externe | DEC-0054, DEC-0055 | 50.0 % | DEC-0054, DEC-0052, DEC-0025, DEC-0059, DEC-0010 | 50.0 % | 215 |
| q30 | Définir l'identité d'agent indépendante du modèle et du harnais | DEC-0043, DEC-0053 | 50.0 % | DEC-0043, DEC-0045, DEC-0053, DEC-0052, DEC-0128 | 100.0 % | 412 |
| q31 | Exposer la mémoire et le graphe locaux en lecture seule via MCP local | DEC-0047, DEC-0042 | 100.0 % | DEC-0047, DEC-0042, DEC-0130, DEC-0057, DEC-0073 | 100.0 % | 400 |
| q32 | Ajouter la coordination inter-sessions en pull avec studio_sync | DEC-0157, DEC-0161 | 50.0 % | DEC-0157, DEC-0164, DEC-0039, DEC-0165, DEC-0172 | 50.0 % | 357 |
| q33 | Rendre le claim de tâche idempotent au rejeu | DEC-0160, DEC-0159 | 100.0 % | DEC-0160, DEC-0135, DEC-0186, DEC-0159, DEC-0031 | 100.0 % | 372 |
| q34 | Clôturer un travail par une séquence de handoff composite | DEC-0163, DEC-0159 | 100.0 % | DEC-0163, DEC-0161, DEC-0159, DEC-0016, DEC-0185 | 100.0 % | 380 |
| q35 | Corriger la numérotation des décisions avec une séquence Postgres | DEC-0016, DEC-0088 | 50.0 % | DEC-0016, DEC-0108, DEC-0077, DEC-0014, DEC-0107 | 50.0 % | 315 |
| q36 | Synchroniser les IDs serveur avec les fiches ADR | DEC-0088 | 100.0 % | DEC-0088, DEC-0191, DEC-0110, DEC-0109, DEC-0123 | 100.0 % | 356 |
| q37 | Refondre le design system du dashboard avec un thème clair | DEC-0078, DEC-0079 | 50.0 % | DEC-0078, DEC-0077, DEC-0090, DEC-0056, DEC-0061 | 50.0 % | 329 |
| q38 | Durcir les en-têtes de sécurité au edge (HSTS, nosniff) | DEC-0060 | 100.0 % | DEC-0060, DEC-0184, DEC-0134, DEC-0088, DEC-0136 | 100.0 % | 364 |
| q39 | Mettre en place une politique CSP progressive sur le dashboard | DEC-0061 | 100.0 % | DEC-0061, DEC-0090, DEC-0056, DEC-0076, DEC-0182 | 100.0 % | 301 |
| q40 | Forcer l'endpoint S3 public pour les URLs pré-signées | DEC-0004 | 100.0 % | DEC-0004, DEC-0037, DEC-0025, DEC-0033, DEC-0134 | 100.0 % | 379 |
| q41 | Enregistrer publiquement un Agent comme identité de provenance | DEC-0045, DEC-0062 | 100.0 % | DEC-0045, DEC-0062, DEC-0043, DEC-0084, DEC-0141 | 100.0 % | 397 |
| q42 | Ajouter les métadonnées runtime agent_profile, harness, provider, model | DEC-0053, DEC-0043 | 100.0 % | DEC-0043, DEC-0053, DEC-0070, DEC-0055, DEC-0052 | 100.0 % | 419 |
| q43 | Enrôler le poste desktop avec une seule entrée secrète sur le pont local | DEC-0130 | 100.0 % | DEC-0130, DEC-0117, DEC-0093, DEC-0042, DEC-0190 | 100.0 % | 432 |
| q44 | Négocier la version client/serveur de façon additive | DEC-0127 | 100.0 % | DEC-0127, DEC-0107, DEC-0110, DEC-0084, DEC-0037 | 100.0 % | 397 |
| q45 | Provisionner le premier compte via la CLI serveur studio-admin | DEC-0011 | 100.0 % | DEC-0011, DEC-0121, DEC-0025, DEC-0075, DEC-0073 | 100.0 % | 361 |

## Requêtes manquées en P04

| id | objectif | attendues absentes | retournées |
|---|---|---|---|
| q03 | Ajouter un worker d'expiration des transferts et son job CLI | DEC-0019 | DEC-0020, DEC-0121, DEC-0165, DEC-0031, DEC-0159 |
| q05 | Modifier le Git watcher pour supporter plusieurs repositories | DEC-0032 | DEC-0136, DEC-0115, DEC-0095, DEC-0079, DEC-0068 |
| q07 | Mettre en place un fan-out temps réel multi-process via NOTIFY PostgreSQL | DEC-0018 | DEC-0156, DEC-0025, DEC-0134, DEC-0164, DEC-0011 |
| q08 | Ajouter une file de review pour les propositions de roadmap | DEC-0049 | DEC-0087, DEC-0089, DEC-0088, DEC-0084, DEC-0083 |
| q15 | Exposer la Library via une surface HTTP canonique | DEC-0072 | DEC-0071, DEC-0046, DEC-0057, DEC-0075, DEC-0076 |
| q16 | Résoudre le scope et le shadowing d'une définition Library | DEC-0069 | DEC-0065, DEC-0063, DEC-0075, DEC-0067, DEC-0068 |
| q18 | Authentifier l'humain sur le dashboard par un JWT court | DEC-0142 | DEC-0056, DEC-0110, DEC-0076, DEC-0035, DEC-0090 |
| q19 | Mettre en place un refresh token rotatif pour la session desktop | DEC-0056 | DEC-0142, DEC-0182, DEC-0083, DEC-0117, DEC-0110 |
| q20 | Ajouter le shell desktop Tauri 2 autour du dashboard | DEC-0095 | DEC-0090, DEC-0142, DEC-0076, DEC-0094, DEC-0093 |
| q21 | Mettre en place un daemon unique supervisé côté desktop | DEC-0028 | DEC-0094, DEC-0142, DEC-0162, DEC-0125, DEC-0117 |
| q22 | Générer les projections Claude Code et OpenCode depuis .agents | DEC-0093 | DEC-0074, DEC-0172, DEC-0123, DEC-0167, DEC-0083 |
| q24 | Lancer un harness de façon non interactive avec un timeout dur | DEC-0173, DEC-0177 | DEC-0176, DEC-0182, DEC-0179, DEC-0175, DEC-0095 |
| q25 | Fournir un credential éphémère de lancement lié à la tâche | DEC-0173 | DEC-0182, DEC-0035, DEC-0190, DEC-0175, DEC-0094 |
| q29 | Documenter le parcours d'intégration d'un consommateur externe | DEC-0055 | DEC-0054, DEC-0052, DEC-0025, DEC-0059, DEC-0010 |
| q32 | Ajouter la coordination inter-sessions en pull avec studio_sync | DEC-0161 | DEC-0157, DEC-0164, DEC-0039, DEC-0165, DEC-0172 |
| q35 | Corriger la numérotation des décisions avec une séquence Postgres | DEC-0088 | DEC-0016, DEC-0108, DEC-0077, DEC-0014, DEC-0107 |
| q37 | Refondre le design system du dashboard avec un thème clair | DEC-0079 | DEC-0078, DEC-0077, DEC-0090, DEC-0056, DEC-0061 |

## Métriques machine (vérifiées par `--check`)

<!-- VAULT_SEARCH_METRICS_BEGIN -->
```json
{
  "aggregate": {
    "chars_total": 65831,
    "empty_answers": 0,
    "empty_rate": 0.0,
    "expected_total": 76,
    "macro_precision": 0.2578,
    "macro_recall": 0.7963,
    "micro_precision": 0.2578,
    "micro_recall": 0.7632,
    "queries": 45,
    "retrieved_total": 225,
    "tokens_per_call_mean": 366.09,
    "tokens_per_result_mean": 73.22,
    "tokens_total": 16474,
    "true_positives": 58
  },
  "baseline_p00": {
    "aggregate": {
      "chars_total": 135643,
      "empty_answers": 0,
      "empty_rate": 0.0,
      "expected_total": 76,
      "macro_precision": 0.26,
      "macro_recall": 0.7963,
      "micro_precision": 0.2568,
      "micro_recall": 0.75,
      "queries": 45,
      "retrieved_total": 222,
      "tokens_per_call_mean": 753.93,
      "tokens_total": 33927,
      "true_positives": 57
    },
    "format": "studio.eval.dec-relevance/v1",
    "limit": 5,
    "max_chars": 12000,
    "source": "docs/DEC_RELEVANCE_BASELINE_P00.md"
  },
  "corpus": {
    "decisions": 159,
    "format": "studio.eval.dec-corpus/v1",
    "path": "tests/eval/dec_corpus.json"
  },
  "format": "studio.eval.vault-search/v1",
  "per_query": [
    {
      "baseline_recall": 1.0,
      "chars": 1470,
      "empty": false,
      "expected": [
        "DEC-0025"
      ],
      "id": "q01",
      "objective": "Corriger l'intégrité d'upload d'un transfert simple via Content-MD5",
      "precision": 0.2,
      "recall": 1.0,
      "retrieved": [
        "DEC-0025",
        "DEC-0054",
        "DEC-0106",
        "DEC-0011",
        "DEC-0020"
      ],
      "task_id": null,
      "tokens": 368,
      "true_positives": 1
    },
    {
      "baseline_recall": 1.0,
      "chars": 1420,
      "empty": false,
      "expected": [
        "DEC-0037",
        "DEC-0033"
      ],
      "id": "q02",
      "objective": "Reprendre un upload multipart après expiration des URLs pré-signées",
      "precision": 0.4,
      "recall": 1.0,
      "retrieved": [
        "DEC-0037",
        "DEC-0034",
        "DEC-0033",
        "DEC-0020",
        "DEC-0025"
      ],
      "task_id": null,
      "tokens": 355,
      "true_positives": 2
    },
    {
      "baseline_recall": 1.0,
      "chars": 1467,
      "empty": false,
      "expected": [
        "DEC-0020",
        "DEC-0019"
      ],
      "id": "q03",
      "objective": "Ajouter un worker d'expiration des transferts et son job CLI",
      "precision": 0.2,
      "recall": 0.5,
      "retrieved": [
        "DEC-0020",
        "DEC-0121",
        "DEC-0165",
        "DEC-0031",
        "DEC-0159"
      ],
      "task_id": null,
      "tokens": 367,
      "true_positives": 1
    },
    {
      "baseline_recall": 1.0,
      "chars": 1487,
      "empty": false,
      "expected": [
        "DEC-0026"
      ],
      "id": "q04",
      "objective": "Rendre les appels réseau boto3 asynchrones via asyncio.to_thread",
      "precision": 0.2,
      "recall": 1.0,
      "retrieved": [
        "DEC-0026",
        "DEC-0184",
        "DEC-0134",
        "DEC-0080",
        "DEC-0071"
      ],
      "task_id": null,
      "tokens": 372,
      "true_positives": 1
    },
    {
      "baseline_recall": 1.0,
      "chars": 1286,
      "empty": false,
      "expected": [
        "DEC-0032"
      ],
      "id": "q05",
      "objective": "Modifier le Git watcher pour supporter plusieurs repositories",
      "precision": 0.0,
      "recall": 0.0,
      "retrieved": [
        "DEC-0136",
        "DEC-0115",
        "DEC-0095",
        "DEC-0079",
        "DEC-0068"
      ],
      "task_id": null,
      "tokens": 322,
      "true_positives": 0
    },
    {
      "baseline_recall": 1.0,
      "chars": 1329,
      "empty": false,
      "expected": [
        "DEC-0008",
        "DEC-0018"
      ],
      "id": "q06",
      "objective": "Trancher entre SSE et WebSocket pour les flux temps réel",
      "precision": 0.4,
      "recall": 1.0,
      "retrieved": [
        "DEC-0008",
        "DEC-0156",
        "DEC-0018",
        "DEC-0134",
        "DEC-0164"
      ],
      "task_id": null,
      "tokens": 333,
      "true_positives": 2
    },
    {
      "baseline_recall": 0.5,
      "chars": 1142,
      "empty": false,
      "expected": [
        "DEC-0156",
        "DEC-0018"
      ],
      "id": "q07",
      "objective": "Mettre en place un fan-out temps réel multi-process via NOTIFY PostgreSQL",
      "precision": 0.2,
      "recall": 0.5,
      "retrieved": [
        "DEC-0156",
        "DEC-0025",
        "DEC-0134",
        "DEC-0164",
        "DEC-0011"
      ],
      "task_id": null,
      "tokens": 286,
      "true_positives": 1
    },
    {
      "baseline_recall": 0.5,
      "chars": 1487,
      "empty": false,
      "expected": [
        "DEC-0087",
        "DEC-0049"
      ],
      "id": "q08",
      "objective": "Ajouter une file de review pour les propositions de roadmap",
      "precision": 0.2,
      "recall": 0.5,
      "retrieved": [
        "DEC-0087",
        "DEC-0089",
        "DEC-0088",
        "DEC-0084",
        "DEC-0083"
      ],
      "task_id": null,
      "tokens": 372,
      "true_positives": 1
    },
    {
      "baseline_recall": 1.0,
      "chars": 1670,
      "empty": false,
      "expected": [
        "DEC-0084",
        "DEC-0085"
      ],
      "id": "q09",
      "objective": "Créer et versionner le domaine Roadmap (cycle de vie, provenance)",
      "precision": 0.4,
      "recall": 1.0,
      "retrieved": [
        "DEC-0084",
        "DEC-0085",
        "DEC-0120",
        "DEC-0086",
        "DEC-0107"
      ],
      "task_id": null,
      "tokens": 418,
      "true_positives": 2
    },
    {
      "baseline_recall": 1.0,
      "chars": 1544,
      "empty": false,
      "expected": [
        "DEC-0086",
        "DEC-0080"
      ],
      "id": "q10",
      "objective": "Ajouter la section roadmap au contexte borné studio_prepare_context",
      "precision": 0.4,
      "recall": 1.0,
      "retrieved": [
        "DEC-0086",
        "DEC-0080",
        "DEC-0085",
        "DEC-0159",
        "DEC-0125"
      ],
      "task_id": null,
      "tokens": 386,
      "true_positives": 2
    },
    {
      "baseline_recall": 1.0,
      "chars": 1505,
      "empty": false,
      "expected": [
        "DEC-0185"
      ],
      "id": "q11",
      "objective": "Ajouter les filtres status et mine à la liste des tâches",
      "precision": 0.2,
      "recall": 1.0,
      "retrieved": [
        "DEC-0185",
        "DEC-0161",
        "DEC-0164",
        "DEC-0184",
        "DEC-0082"
      ],
      "task_id": null,
      "tokens": 377,
      "true_positives": 1
    },
    {
      "baseline_recall": 1.0,
      "chars": 1511,
      "empty": false,
      "expected": [
        "DEC-0186"
      ],
      "id": "q12",
      "objective": "Déprécier les outils MCP redondants de session et de claim",
      "precision": 0.2,
      "recall": 1.0,
      "retrieved": [
        "DEC-0186",
        "DEC-0183",
        "DEC-0135",
        "DEC-0184",
        "DEC-0157"
      ],
      "task_id": null,
      "tokens": 378,
      "true_positives": 1
    },
    {
      "baseline_recall": 0.5,
      "chars": 1532,
      "empty": false,
      "expected": [
        "DEC-0064",
        "DEC-0065"
      ],
      "id": "q13",
      "objective": "Versionner les définitions de l'AI Library par pointeur actif",
      "precision": 0.4,
      "recall": 1.0,
      "retrieved": [
        "DEC-0064",
        "DEC-0075",
        "DEC-0134",
        "DEC-0136",
        "DEC-0065"
      ],
      "task_id": null,
      "tokens": 383,
      "true_positives": 2
    },
    {
      "baseline_recall": 0.5,
      "chars": 1517,
      "empty": false,
      "expected": [
        "DEC-0068",
        "DEC-0070"
      ],
      "id": "q14",
      "objective": "Configurer les choix de runtime par utilisateur (bindings User/Runtime)",
      "precision": 0.4,
      "recall": 1.0,
      "retrieved": [
        "DEC-0068",
        "DEC-0012",
        "DEC-0184",
        "DEC-0070",
        "DEC-0123"
      ],
      "task_id": null,
      "tokens": 380,
      "true_positives": 2
    },
    {
      "baseline_recall": 0.5,
      "chars": 1629,
      "empty": false,
      "expected": [
        "DEC-0071",
        "DEC-0072"
      ],
      "id": "q15",
      "objective": "Exposer la Library via une surface HTTP canonique",
      "precision": 0.2,
      "recall": 0.5,
      "retrieved": [
        "DEC-0071",
        "DEC-0046",
        "DEC-0057",
        "DEC-0075",
        "DEC-0076"
      ],
      "task_id": null,
      "tokens": 408,
      "true_positives": 1
    },
    {
      "baseline_recall": 0.5,
      "chars": 1373,
      "empty": false,
      "expected": [
        "DEC-0065",
        "DEC-0069"
      ],
      "id": "q16",
      "objective": "Résoudre le scope et le shadowing d'une définition Library",
      "precision": 0.2,
      "recall": 0.5,
      "retrieved": [
        "DEC-0065",
        "DEC-0063",
        "DEC-0075",
        "DEC-0067",
        "DEC-0068"
      ],
      "task_id": null,
      "tokens": 344,
      "true_positives": 1
    },
    {
      "baseline_recall": 1.0,
      "chars": 1539,
      "empty": false,
      "expected": [
        "DEC-0067"
      ],
      "id": "q17",
      "objective": "Définir les relations typées entre définitions (Library Bindings)",
      "precision": 0.2,
      "recall": 1.0,
      "retrieved": [
        "DEC-0067",
        "DEC-0068",
        "DEC-0075",
        "DEC-0063",
        "DEC-0064"
      ],
      "task_id": null,
      "tokens": 385,
      "true_positives": 1
    },
    {
      "baseline_recall": 0.5,
      "chars": 1268,
      "empty": false,
      "expected": [
        "DEC-0056",
        "DEC-0142"
      ],
      "id": "q18",
      "objective": "Authentifier l'humain sur le dashboard par un JWT court",
      "precision": 0.2,
      "recall": 0.5,
      "retrieved": [
        "DEC-0056",
        "DEC-0110",
        "DEC-0076",
        "DEC-0035",
        "DEC-0090"
      ],
      "task_id": null,
      "tokens": 317,
      "true_positives": 1
    },
    {
      "baseline_recall": 0.5,
      "chars": 1468,
      "empty": false,
      "expected": [
        "DEC-0142",
        "DEC-0056"
      ],
      "id": "q19",
      "objective": "Mettre en place un refresh token rotatif pour la session desktop",
      "precision": 0.2,
      "recall": 0.5,
      "retrieved": [
        "DEC-0142",
        "DEC-0182",
        "DEC-0083",
        "DEC-0117",
        "DEC-0110"
      ],
      "task_id": null,
      "tokens": 367,
      "true_positives": 1
    },
    {
      "baseline_recall": 0.5,
      "chars": 1468,
      "empty": false,
      "expected": [
        "DEC-0090",
        "DEC-0095"
      ],
      "id": "q20",
      "objective": "Ajouter le shell desktop Tauri 2 autour du dashboard",
      "precision": 0.2,
      "recall": 0.5,
      "retrieved": [
        "DEC-0090",
        "DEC-0142",
        "DEC-0076",
        "DEC-0094",
        "DEC-0093"
      ],
      "task_id": null,
      "tokens": 367,
      "true_positives": 1
    },
    {
      "baseline_recall": 0.5,
      "chars": 1551,
      "empty": false,
      "expected": [
        "DEC-0094",
        "DEC-0028"
      ],
      "id": "q21",
      "objective": "Mettre en place un daemon unique supervisé côté desktop",
      "precision": 0.2,
      "recall": 0.5,
      "retrieved": [
        "DEC-0094",
        "DEC-0142",
        "DEC-0162",
        "DEC-0125",
        "DEC-0117"
      ],
      "task_id": null,
      "tokens": 388,
      "true_positives": 1
    },
    {
      "baseline_recall": 0.5,
      "chars": 1271,
      "empty": false,
      "expected": [
        "DEC-0074",
        "DEC-0093"
      ],
      "id": "q22",
      "objective": "Générer les projections Claude Code et OpenCode depuis .agents",
      "precision": 0.2,
      "recall": 0.5,
      "retrieved": [
        "DEC-0074",
        "DEC-0172",
        "DEC-0123",
        "DEC-0167",
        "DEC-0083"
      ],
      "task_id": null,
      "tokens": 318,
      "true_positives": 1
    },
    {
      "baseline_recall": 1.0,
      "chars": 1565,
      "empty": false,
      "expected": [
        "DEC-0172",
        "DEC-0181"
      ],
      "id": "q23",
      "objective": "Robustifier le bootstrap permanent et ses cibles d'actions manuelles",
      "precision": 0.4,
      "recall": 1.0,
      "retrieved": [
        "DEC-0172",
        "DEC-0181",
        "DEC-0157",
        "DEC-0011",
        "DEC-0183"
      ],
      "task_id": null,
      "tokens": 392,
      "true_positives": 2
    },
    {
      "baseline_recall": 0.3333,
      "chars": 1586,
      "empty": false,
      "expected": [
        "DEC-0176",
        "DEC-0173",
        "DEC-0177"
      ],
      "id": "q24",
      "objective": "Lancer un harness de façon non interactive avec un timeout dur",
      "precision": 0.2,
      "recall": 0.3333,
      "retrieved": [
        "DEC-0176",
        "DEC-0182",
        "DEC-0179",
        "DEC-0175",
        "DEC-0095"
      ],
      "task_id": null,
      "tokens": 397,
      "true_positives": 1
    },
    {
      "baseline_recall": 0.5,
      "chars": 1473,
      "empty": false,
      "expected": [
        "DEC-0175",
        "DEC-0173"
      ],
      "id": "q25",
      "objective": "Fournir un credential éphémère de lancement lié à la tâche",
      "precision": 0.2,
      "recall": 0.5,
      "retrieved": [
        "DEC-0182",
        "DEC-0035",
        "DEC-0190",
        "DEC-0175",
        "DEC-0094"
      ],
      "task_id": null,
      "tokens": 369,
      "true_positives": 1
    },
    {
      "baseline_recall": 1.0,
      "chars": 1583,
      "empty": false,
      "expected": [
        "DEC-0168"
      ],
      "id": "q26",
      "objective": "Charger un bundle offline fusionnant .agents et la Library",
      "precision": 0.2,
      "recall": 1.0,
      "retrieved": [
        "DEC-0168",
        "DEC-0167",
        "DEC-0062",
        "DEC-0067",
        "DEC-0066"
      ],
      "task_id": null,
      "tokens": 396,
      "true_positives": 1
    },
    {
      "baseline_recall": 1.0,
      "chars": 1538,
      "empty": false,
      "expected": [
        "DEC-0082"
      ],
      "id": "q27",
      "objective": "Ajouter le catalogue des machines actives avec statut heartbeat",
      "precision": 0.2,
      "recall": 1.0,
      "retrieved": [
        "DEC-0082",
        "DEC-0035",
        "DEC-0039",
        "DEC-0028",
        "DEC-0003"
      ],
      "task_id": null,
      "tokens": 385,
      "true_positives": 1
    },
    {
      "baseline_recall": 1.0,
      "chars": 1429,
      "empty": false,
      "expected": [
        "DEC-0036",
        "DEC-0063"
      ],
      "id": "q28",
      "objective": "Rendre l'autorisation transverse minimale par rôle et propriété",
      "precision": 0.4,
      "recall": 1.0,
      "retrieved": [
        "DEC-0036",
        "DEC-0052",
        "DEC-0079",
        "DEC-0089",
        "DEC-0063"
      ],
      "task_id": null,
      "tokens": 358,
      "true_positives": 2
    },
    {
      "baseline_recall": 0.5,
      "chars": 860,
      "empty": false,
      "expected": [
        "DEC-0054",
        "DEC-0055"
      ],
      "id": "q29",
      "objective": "Documenter le parcours d'intégration d'un consommateur externe",
      "precision": 0.2,
      "recall": 0.5,
      "retrieved": [
        "DEC-0054",
        "DEC-0052",
        "DEC-0025",
        "DEC-0059",
        "DEC-0010"
      ],
      "task_id": null,
      "tokens": 215,
      "true_positives": 1
    },
    {
      "baseline_recall": 0.5,
      "chars": 1648,
      "empty": false,
      "expected": [
        "DEC-0043",
        "DEC-0053"
      ],
      "id": "q30",
      "objective": "Définir l'identité d'agent indépendante du modèle et du harnais",
      "precision": 0.4,
      "recall": 1.0,
      "retrieved": [
        "DEC-0043",
        "DEC-0045",
        "DEC-0053",
        "DEC-0052",
        "DEC-0128"
      ],
      "task_id": null,
      "tokens": 412,
      "true_positives": 2
    },
    {
      "baseline_recall": 1.0,
      "chars": 1598,
      "empty": false,
      "expected": [
        "DEC-0047",
        "DEC-0042"
      ],
      "id": "q31",
      "objective": "Exposer la mémoire et le graphe locaux en lecture seule via MCP local",
      "precision": 0.4,
      "recall": 1.0,
      "retrieved": [
        "DEC-0047",
        "DEC-0042",
        "DEC-0130",
        "DEC-0057",
        "DEC-0073"
      ],
      "task_id": null,
      "tokens": 400,
      "true_positives": 2
    },
    {
      "baseline_recall": 0.5,
      "chars": 1425,
      "empty": false,
      "expected": [
        "DEC-0157",
        "DEC-0161"
      ],
      "id": "q32",
      "objective": "Ajouter la coordination inter-sessions en pull avec studio_sync",
      "precision": 0.2,
      "recall": 0.5,
      "retrieved": [
        "DEC-0157",
        "DEC-0164",
        "DEC-0039",
        "DEC-0165",
        "DEC-0172"
      ],
      "task_id": null,
      "tokens": 357,
      "true_positives": 1
    },
    {
      "baseline_recall": 1.0,
      "chars": 1487,
      "empty": false,
      "expected": [
        "DEC-0160",
        "DEC-0159"
      ],
      "id": "q33",
      "objective": "Rendre le claim de tâche idempotent au rejeu",
      "precision": 0.4,
      "recall": 1.0,
      "retrieved": [
        "DEC-0160",
        "DEC-0135",
        "DEC-0186",
        "DEC-0159",
        "DEC-0031"
      ],
      "task_id": null,
      "tokens": 372,
      "true_positives": 2
    },
    {
      "baseline_recall": 1.0,
      "chars": 1519,
      "empty": false,
      "expected": [
        "DEC-0163",
        "DEC-0159"
      ],
      "id": "q34",
      "objective": "Clôturer un travail par une séquence de handoff composite",
      "precision": 0.4,
      "recall": 1.0,
      "retrieved": [
        "DEC-0163",
        "DEC-0161",
        "DEC-0159",
        "DEC-0016",
        "DEC-0185"
      ],
      "task_id": null,
      "tokens": 380,
      "true_positives": 2
    },
    {
      "baseline_recall": 0.5,
      "chars": 1257,
      "empty": false,
      "expected": [
        "DEC-0016",
        "DEC-0088"
      ],
      "id": "q35",
      "objective": "Corriger la numérotation des décisions avec une séquence Postgres",
      "precision": 0.2,
      "recall": 0.5,
      "retrieved": [
        "DEC-0016",
        "DEC-0108",
        "DEC-0077",
        "DEC-0014",
        "DEC-0107"
      ],
      "task_id": null,
      "tokens": 315,
      "true_positives": 1
    },
    {
      "baseline_recall": 1.0,
      "chars": 1422,
      "empty": false,
      "expected": [
        "DEC-0088"
      ],
      "id": "q36",
      "objective": "Synchroniser les IDs serveur avec les fiches ADR",
      "precision": 0.2,
      "recall": 1.0,
      "retrieved": [
        "DEC-0088",
        "DEC-0191",
        "DEC-0110",
        "DEC-0109",
        "DEC-0123"
      ],
      "task_id": null,
      "tokens": 356,
      "true_positives": 1
    },
    {
      "baseline_recall": 0.5,
      "chars": 1316,
      "empty": false,
      "expected": [
        "DEC-0078",
        "DEC-0079"
      ],
      "id": "q37",
      "objective": "Refondre le design system du dashboard avec un thème clair",
      "precision": 0.2,
      "recall": 0.5,
      "retrieved": [
        "DEC-0078",
        "DEC-0077",
        "DEC-0090",
        "DEC-0056",
        "DEC-0061"
      ],
      "task_id": null,
      "tokens": 329,
      "true_positives": 1
    },
    {
      "baseline_recall": 1.0,
      "chars": 1453,
      "empty": false,
      "expected": [
        "DEC-0060"
      ],
      "id": "q38",
      "objective": "Durcir les en-têtes de sécurité au edge (HSTS, nosniff)",
      "precision": 0.2,
      "recall": 1.0,
      "retrieved": [
        "DEC-0060",
        "DEC-0184",
        "DEC-0134",
        "DEC-0088",
        "DEC-0136"
      ],
      "task_id": null,
      "tokens": 364,
      "true_positives": 1
    },
    {
      "baseline_recall": 1.0,
      "chars": 1201,
      "empty": false,
      "expected": [
        "DEC-0061"
      ],
      "id": "q39",
      "objective": "Mettre en place une politique CSP progressive sur le dashboard",
      "precision": 0.2,
      "recall": 1.0,
      "retrieved": [
        "DEC-0061",
        "DEC-0090",
        "DEC-0056",
        "DEC-0076",
        "DEC-0182"
      ],
      "task_id": null,
      "tokens": 301,
      "true_positives": 1
    },
    {
      "baseline_recall": 1.0,
      "chars": 1513,
      "empty": false,
      "expected": [
        "DEC-0004"
      ],
      "id": "q40",
      "objective": "Forcer l'endpoint S3 public pour les URLs pré-signées",
      "precision": 0.2,
      "recall": 1.0,
      "retrieved": [
        "DEC-0004",
        "DEC-0037",
        "DEC-0025",
        "DEC-0033",
        "DEC-0134"
      ],
      "task_id": null,
      "tokens": 379,
      "true_positives": 1
    },
    {
      "baseline_recall": 1.0,
      "chars": 1588,
      "empty": false,
      "expected": [
        "DEC-0045",
        "DEC-0062"
      ],
      "id": "q41",
      "objective": "Enregistrer publiquement un Agent comme identité de provenance",
      "precision": 0.4,
      "recall": 1.0,
      "retrieved": [
        "DEC-0045",
        "DEC-0062",
        "DEC-0043",
        "DEC-0084",
        "DEC-0141"
      ],
      "task_id": null,
      "tokens": 397,
      "true_positives": 2
    },
    {
      "baseline_recall": 1.0,
      "chars": 1676,
      "empty": false,
      "expected": [
        "DEC-0053",
        "DEC-0043"
      ],
      "id": "q42",
      "objective": "Ajouter les métadonnées runtime agent_profile, harness, provider, model",
      "precision": 0.4,
      "recall": 1.0,
      "retrieved": [
        "DEC-0043",
        "DEC-0053",
        "DEC-0070",
        "DEC-0055",
        "DEC-0052"
      ],
      "task_id": null,
      "tokens": 419,
      "true_positives": 2
    },
    {
      "baseline_recall": 1.0,
      "chars": 1728,
      "empty": false,
      "expected": [
        "DEC-0130"
      ],
      "id": "q43",
      "objective": "Enrôler le poste desktop avec une seule entrée secrète sur le pont local",
      "precision": 0.2,
      "recall": 1.0,
      "retrieved": [
        "DEC-0130",
        "DEC-0117",
        "DEC-0093",
        "DEC-0042",
        "DEC-0190"
      ],
      "task_id": null,
      "tokens": 432,
      "true_positives": 1
    },
    {
      "baseline_recall": 1.0,
      "chars": 1588,
      "empty": false,
      "expected": [
        "DEC-0127"
      ],
      "id": "q44",
      "objective": "Négocier la version client/serveur de façon additive",
      "precision": 0.2,
      "recall": 1.0,
      "retrieved": [
        "DEC-0127",
        "DEC-0107",
        "DEC-0110",
        "DEC-0084",
        "DEC-0037"
      ],
      "task_id": null,
      "tokens": 397,
      "true_positives": 1
    },
    {
      "baseline_recall": 1.0,
      "chars": 1444,
      "empty": false,
      "expected": [
        "DEC-0011"
      ],
      "id": "q45",
      "objective": "Provisionner le premier compte via la CLI serveur studio-admin",
      "precision": 0.2,
      "recall": 1.0,
      "retrieved": [
        "DEC-0011",
        "DEC-0121",
        "DEC-0025",
        "DEC-0075",
        "DEC-0073"
      ],
      "task_id": null,
      "tokens": 361,
      "true_positives": 1
    }
  ],
  "queries": {
    "count": 45,
    "format": "studio.eval.dec-queries/v1",
    "limit": 5,
    "max_chars": 12000,
    "path": "tests/eval/dec_queries.json"
  }
}
```
<!-- VAULT_SEARCH_METRICS_END -->
