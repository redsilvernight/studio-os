# Baseline de pertinence des décisions — P00 (roadmap vault serveur)

> **Baseline figée.** La sélection des décisions a evolved en P07 (pondération IDF,
> seuil relatif) : ce rapport n'est plus reproductible par
> `uv run python -m scripts.dec_relevance_eval`, qui écrit désormais
> `docs/DEC_RELEVANCE_P07.md`. Le bloc machine ci-dessous reste lu comme référence
> de comparaison.

- Projet : Studio OS (`2a836038-153c-41cf-879a-73bd794760b0`)
- Corpus : `tests/eval/dec_corpus.json` (159 décisions serveur, snapshot lecture seule)
- Requêtes : `tests/eval/dec_queries.json` (45 objectifs)
- Sélection : `studio_api.services.project_context._select_decisions` (limit=5, max_chars=12000)
- Tokens : approximation `ceil(caractères / 4)` sur les corps effectivement retournés

## Méthodologie

La logique de sélection réelle est importée depuis `services/api` et rejouée sans
base de données : la frontière de service `decisions.list_decisions` est remplacée
par le corpus versionné, si bien que le filtre `superseded`, l'ordre
(`linked_to_task`, score, `accepted`, récence, `readable_id`), `limit` et le budget
de texte sont ceux du serveur. Les requêtes n'ont pas de `task_id` : elles mesurent
le recouvrement lexical pur, seule relation disponible pour un objectif libre.

## Agrégat

| Métrique | Valeur |
|---|---|
| Requêtes | 45 |
| Réponses `decisions: []` | 0 (0.0 %) |
| Précision micro | 25.7 % |
| Rappel micro | 75.0 % |
| Précision macro | 26.0 % |
| Rappel macro | 79.6 % |
| Décisions retournées | 222 (attendues : 76, vrais positifs : 57) |
| Caractères injectés (total) | 135643 |
| Tokens injectés (total) | 33927 |
| Tokens par appel (moyenne) | 753.93 |

## Détail par requête

| id | objectif | retournées | attendues | précision | rappel | tokens |
|---|---|---|---|---|---|---|
| q01 | Corriger l'intégrité d'upload d'un transfert simple via Content-MD5 | DEC-0025, DEC-0073, DEC-0071, DEC-0047, DEC-0026 | DEC-0025 | 20.0 % | 100.0 % | 366 |
| q02 | Reprendre un upload multipart après expiration des URLs pré-signées | DEC-0037, DEC-0033, DEC-0134, DEC-0038, DEC-0025 | DEC-0037, DEC-0033 | 40.0 % | 100.0 % | 452 |
| q03 | Ajouter un worker d'expiration des transferts et son job CLI | DEC-0020, DEC-0037, DEC-0031, DEC-0019, DEC-0011 | DEC-0020, DEC-0019 | 40.0 % | 100.0 % | 375 |
| q04 | Rendre les appels réseau boto3 asynchrones via asyncio.to_thread | DEC-0026, DEC-0184, DEC-0073, DEC-0071, DEC-0047 | DEC-0026 | 20.0 % | 100.0 % | 593 |
| q05 | Modifier le Git watcher pour supporter plusieurs repositories | DEC-0136, DEC-0115, DEC-0032, DEC-0181, DEC-0164 | DEC-0032 | 20.0 % | 100.0 % | 782 |
| q06 | Trancher entre SSE et WebSocket pour les flux temps réel | DEC-0008, DEC-0156, DEC-0018, DEC-0164, DEC-0157 | DEC-0008, DEC-0018 | 40.0 % | 100.0 % | 1182 |
| q07 | Mettre en place un fan-out temps réel multi-process via NOTIFY PostgreSQL | DEC-0156, DEC-0164, DEC-0134, DEC-0038, DEC-0182 | DEC-0156, DEC-0018 | 20.0 % | 50.0 % | 985 |
| q08 | Ajouter une file de review pour les propositions de roadmap | DEC-0087, DEC-0089, DEC-0084, DEC-0125, DEC-0086 | DEC-0087, DEC-0049 | 20.0 % | 50.0 % | 1064 |
| q09 | Créer et versionner le domaine Roadmap (cycle de vie, provenance) | DEC-0084, DEC-0085, DEC-0141, DEC-0125, DEC-0120 | DEC-0084, DEC-0085 | 40.0 % | 100.0 % | 1232 |
| q10 | Ajouter la section roadmap au contexte borné studio_prepare_context | DEC-0086, DEC-0080, DEC-0159, DEC-0085, DEC-0157 | DEC-0086, DEC-0080 | 40.0 % | 100.0 % | 1204 |
| q11 | Ajouter les filtres status et mine à la liste des tâches | DEC-0185, DEC-0161, DEC-0082, DEC-0086, DEC-0177 | DEC-0185 | 20.0 % | 100.0 % | 848 |
| q12 | Déprécier les outils MCP redondants de session et de claim | DEC-0186, DEC-0183, DEC-0135, DEC-0072, DEC-0047 | DEC-0186 | 20.0 % | 100.0 % | 810 |
| q13 | Versionner les définitions de l'AI Library par pointeur actif | DEC-0064, DEC-0067, DEC-0063, DEC-0168, DEC-0136 | DEC-0064, DEC-0065 | 20.0 % | 50.0 % | 585 |
| q14 | Configurer les choix de runtime par utilisateur (bindings User/Runtime) | DEC-0068, DEC-0012, DEC-0067, DEC-0095, DEC-0168 | DEC-0068, DEC-0070 | 20.0 % | 50.0 % | 588 |
| q15 | Exposer la Library via une surface HTTP canonique | DEC-0071, DEC-0046, DEC-0075, DEC-0057, DEC-0076 | DEC-0071, DEC-0072 | 20.0 % | 50.0 % | 372 |
| q16 | Résoudre le scope et le shadowing d'une définition Library | DEC-0065, DEC-0075, DEC-0068, DEC-0172, DEC-0168 | DEC-0065, DEC-0069 | 20.0 % | 50.0 % | 731 |
| q17 | Définir les relations typées entre définitions (Library Bindings) | DEC-0067, DEC-0068, DEC-0063, DEC-0168, DEC-0077 | DEC-0067 | 20.0 % | 100.0 % | 491 |
| q18 | Authentifier l'humain sur le dashboard par un JWT court | DEC-0056, DEC-0110, DEC-0090, DEC-0076, DEC-0061 | DEC-0056, DEC-0142 | 20.0 % | 50.0 % | 710 |
| q19 | Mettre en place un refresh token rotatif pour la session desktop | DEC-0142, DEC-0182, DEC-0130, DEC-0117, DEC-0110 | DEC-0142, DEC-0056 | 20.0 % | 50.0 % | 1114 |
| q20 | Ajouter le shell desktop Tauri 2 autour du dashboard | DEC-0090, DEC-0094, DEC-0093, DEC-0162, DEC-0142 | DEC-0090, DEC-0095 | 20.0 % | 50.0 % | 845 |
| q21 | Mettre en place un daemon unique supervisé côté desktop | DEC-0094, DEC-0142, DEC-0182, DEC-0130, DEC-0090 | DEC-0094, DEC-0028 | 20.0 % | 50.0 % | 769 |
| q22 | Générer les projections Claude Code et OpenCode depuis .agents | DEC-0074, DEC-0172, DEC-0168, DEC-0117, DEC-0115 | DEC-0074, DEC-0093 | 20.0 % | 50.0 % | 954 |
| q23 | Robustifier le bootstrap permanent et ses cibles d'actions manuelles | DEC-0172, DEC-0181, DEC-0183, DEC-0167, DEC-0165 | DEC-0172, DEC-0181 | 40.0 % | 100.0 % | 1173 |
| q24 | Lancer un harness de façon non interactive avec un timeout dur | DEC-0176, DEC-0070, DEC-0129, DEC-0124, DEC-0095 | DEC-0176, DEC-0173, DEC-0177 | 20.0 % | 33.3 % | 599 |
| q25 | Fournir un credential éphémère de lancement lié à la tâche | DEC-0182, DEC-0179, DEC-0177, DEC-0176, DEC-0175 | DEC-0175, DEC-0173 | 20.0 % | 50.0 % | 644 |
| q26 | Charger un bundle offline fusionnant .agents et la Library | DEC-0168, DEC-0167, DEC-0077, DEC-0075, DEC-0073 | DEC-0168 | 20.0 % | 100.0 % | 609 |
| q27 | Ajouter le catalogue des machines actives avec statut heartbeat | DEC-0082, DEC-0040, DEC-0028, DEC-0157, DEC-0130 | DEC-0082 | 20.0 % | 100.0 % | 798 |
| q28 | Rendre l'autorisation transverse minimale par rôle et propriété | DEC-0036, DEC-0123, DEC-0089, DEC-0079, DEC-0063 | DEC-0036, DEC-0063 | 40.0 % | 100.0 % | 732 |
| q29 | Documenter le parcours d'intégration d'un consommateur externe | DEC-0054, DEC-0059, DEC-0052, DEC-0010, DEC-0071 | DEC-0054, DEC-0055 | 20.0 % | 50.0 % | 376 |
| q30 | Définir l'identité d'agent indépendante du modèle et du harnais | DEC-0045, DEC-0043, DEC-0070, DEC-0052, DEC-0161 | DEC-0043, DEC-0053 | 20.0 % | 50.0 % | 556 |
| q31 | Exposer la mémoire et le graphe locaux en lecture seule via MCP local | DEC-0047, DEC-0042, DEC-0093, DEC-0073, DEC-0156 | DEC-0047, DEC-0042 | 40.0 % | 100.0 % | 797 |
| q32 | Ajouter la coordination inter-sessions en pull avec studio_sync | DEC-0157, DEC-0164, DEC-0165, DEC-0085, DEC-0159 | DEC-0157, DEC-0161 | 20.0 % | 50.0 % | 1237 |
| q33 | Rendre le claim de tâche idempotent au rejeu | DEC-0160, DEC-0186, DEC-0159, DEC-0135, DEC-0182 | DEC-0160, DEC-0159 | 40.0 % | 100.0 % | 790 |
| q34 | Clôturer un travail par une séquence de handoff composite | DEC-0163, DEC-0185, DEC-0159, DEC-0049, DEC-0016 | DEC-0163, DEC-0159 | 40.0 % | 100.0 % | 492 |
| q35 | Corriger la numérotation des décisions avec une séquence Postgres | DEC-0016, DEC-0021, DEC-0164, DEC-0110, DEC-0109 | DEC-0016, DEC-0088 | 20.0 % | 50.0 % | 1168 |
| q36 | Synchroniser les IDs serveur avec les fiches ADR | DEC-0088, DEC-0191, DEC-0127, DEC-0114, DEC-0110 | DEC-0088 | 20.0 % | 100.0 % | 953 |
| q37 | Refondre le design system du dashboard avec un thème clair | DEC-0078, DEC-0090, DEC-0076, DEC-0061, DEC-0056 | DEC-0078, DEC-0079 | 20.0 % | 50.0 % | 404 |
| q38 | Durcir les en-têtes de sécurité au edge (HSTS, nosniff) | DEC-0060, DEC-0156 | DEC-0060 | 50.0 % | 100.0 % | 461 |
| q39 | Mettre en place une politique CSP progressive sur le dashboard | DEC-0061, DEC-0182, DEC-0090, DEC-0076, DEC-0056 | DEC-0061 | 20.0 % | 100.0 % | 448 |
| q40 | Forcer l'endpoint S3 public pour les URLs pré-signées | DEC-0004, DEC-0037, DEC-0033, DEC-0045, DEC-0128 | DEC-0004 | 20.0 % | 100.0 % | 522 |
| q41 | Enregistrer publiquement un Agent comme identité de provenance | DEC-0045, DEC-0062, DEC-0043, DEC-0084, DEC-0161 | DEC-0045, DEC-0062 | 40.0 % | 100.0 % | 735 |
| q42 | Ajouter les métadonnées runtime agent_profile, harness, provider, model | DEC-0053, DEC-0043, DEC-0055, DEC-0070, DEC-0052 | DEC-0053, DEC-0043 | 40.0 % | 100.0 % | 389 |
| q43 | Enrôler le poste desktop avec une seule entrée secrète sur le pont local | DEC-0130, DEC-0117, DEC-0093, DEC-0083, DEC-0047 | DEC-0130 | 20.0 % | 100.0 % | 818 |
| q44 | Négocier la version client/serveur de façon additive | DEC-0127, DEC-0134, DEC-0114, DEC-0110, DEC-0107 | DEC-0127 | 20.0 % | 100.0 % | 1141 |
| q45 | Provisionner le premier compte via la CLI serveur studio-admin | DEC-0011, DEC-0183, DEC-0157, DEC-0121, DEC-0191 | DEC-0011 | 20.0 % | 100.0 % | 1033 |

## Métriques machine (vérifiées par `--check`)

<!-- DEC_RELEVANCE_METRICS_BEGIN -->
```json
{
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
  "corpus": {
    "decisions": 159,
    "format": "studio.eval.dec-corpus/v1",
    "path": "tests/eval/dec_corpus.json"
  },
  "format": "studio.eval.dec-relevance/v1",
  "per_query": [
    {
      "chars": 1463,
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
        "DEC-0073",
        "DEC-0071",
        "DEC-0047",
        "DEC-0026"
      ],
      "tokens": 366,
      "true_positives": 1
    },
    {
      "chars": 1806,
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
        "DEC-0033",
        "DEC-0134",
        "DEC-0038",
        "DEC-0025"
      ],
      "tokens": 452,
      "true_positives": 2
    },
    {
      "chars": 1500,
      "empty": false,
      "expected": [
        "DEC-0020",
        "DEC-0019"
      ],
      "id": "q03",
      "objective": "Ajouter un worker d'expiration des transferts et son job CLI",
      "precision": 0.4,
      "recall": 1.0,
      "retrieved": [
        "DEC-0020",
        "DEC-0037",
        "DEC-0031",
        "DEC-0019",
        "DEC-0011"
      ],
      "tokens": 375,
      "true_positives": 2
    },
    {
      "chars": 2370,
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
        "DEC-0073",
        "DEC-0071",
        "DEC-0047"
      ],
      "tokens": 593,
      "true_positives": 1
    },
    {
      "chars": 3127,
      "empty": false,
      "expected": [
        "DEC-0032"
      ],
      "id": "q05",
      "objective": "Modifier le Git watcher pour supporter plusieurs repositories",
      "precision": 0.2,
      "recall": 1.0,
      "retrieved": [
        "DEC-0136",
        "DEC-0115",
        "DEC-0032",
        "DEC-0181",
        "DEC-0164"
      ],
      "tokens": 782,
      "true_positives": 1
    },
    {
      "chars": 4727,
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
        "DEC-0164",
        "DEC-0157"
      ],
      "tokens": 1182,
      "true_positives": 2
    },
    {
      "chars": 3940,
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
        "DEC-0164",
        "DEC-0134",
        "DEC-0038",
        "DEC-0182"
      ],
      "tokens": 985,
      "true_positives": 1
    },
    {
      "chars": 4255,
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
        "DEC-0084",
        "DEC-0125",
        "DEC-0086"
      ],
      "tokens": 1064,
      "true_positives": 1
    },
    {
      "chars": 4925,
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
        "DEC-0141",
        "DEC-0125",
        "DEC-0120"
      ],
      "tokens": 1232,
      "true_positives": 2
    },
    {
      "chars": 4813,
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
        "DEC-0159",
        "DEC-0085",
        "DEC-0157"
      ],
      "tokens": 1204,
      "true_positives": 2
    },
    {
      "chars": 3391,
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
        "DEC-0082",
        "DEC-0086",
        "DEC-0177"
      ],
      "tokens": 848,
      "true_positives": 1
    },
    {
      "chars": 3239,
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
        "DEC-0072",
        "DEC-0047"
      ],
      "tokens": 810,
      "true_positives": 1
    },
    {
      "chars": 2340,
      "empty": false,
      "expected": [
        "DEC-0064",
        "DEC-0065"
      ],
      "id": "q13",
      "objective": "Versionner les définitions de l'AI Library par pointeur actif",
      "precision": 0.2,
      "recall": 0.5,
      "retrieved": [
        "DEC-0064",
        "DEC-0067",
        "DEC-0063",
        "DEC-0168",
        "DEC-0136"
      ],
      "tokens": 585,
      "true_positives": 1
    },
    {
      "chars": 2350,
      "empty": false,
      "expected": [
        "DEC-0068",
        "DEC-0070"
      ],
      "id": "q14",
      "objective": "Configurer les choix de runtime par utilisateur (bindings User/Runtime)",
      "precision": 0.2,
      "recall": 0.5,
      "retrieved": [
        "DEC-0068",
        "DEC-0012",
        "DEC-0067",
        "DEC-0095",
        "DEC-0168"
      ],
      "tokens": 588,
      "true_positives": 1
    },
    {
      "chars": 1485,
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
        "DEC-0075",
        "DEC-0057",
        "DEC-0076"
      ],
      "tokens": 372,
      "true_positives": 1
    },
    {
      "chars": 2921,
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
        "DEC-0075",
        "DEC-0068",
        "DEC-0172",
        "DEC-0168"
      ],
      "tokens": 731,
      "true_positives": 1
    },
    {
      "chars": 1961,
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
        "DEC-0063",
        "DEC-0168",
        "DEC-0077"
      ],
      "tokens": 491,
      "true_positives": 1
    },
    {
      "chars": 2839,
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
        "DEC-0090",
        "DEC-0076",
        "DEC-0061"
      ],
      "tokens": 710,
      "true_positives": 1
    },
    {
      "chars": 4456,
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
        "DEC-0130",
        "DEC-0117",
        "DEC-0110"
      ],
      "tokens": 1114,
      "true_positives": 1
    },
    {
      "chars": 3380,
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
        "DEC-0094",
        "DEC-0093",
        "DEC-0162",
        "DEC-0142"
      ],
      "tokens": 845,
      "true_positives": 1
    },
    {
      "chars": 3076,
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
        "DEC-0182",
        "DEC-0130",
        "DEC-0090"
      ],
      "tokens": 769,
      "true_positives": 1
    },
    {
      "chars": 3814,
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
        "DEC-0168",
        "DEC-0117",
        "DEC-0115"
      ],
      "tokens": 954,
      "true_positives": 1
    },
    {
      "chars": 4689,
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
        "DEC-0183",
        "DEC-0167",
        "DEC-0165"
      ],
      "tokens": 1173,
      "true_positives": 2
    },
    {
      "chars": 2396,
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
        "DEC-0070",
        "DEC-0129",
        "DEC-0124",
        "DEC-0095"
      ],
      "tokens": 599,
      "true_positives": 1
    },
    {
      "chars": 2576,
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
        "DEC-0179",
        "DEC-0177",
        "DEC-0176",
        "DEC-0175"
      ],
      "tokens": 644,
      "true_positives": 1
    },
    {
      "chars": 2436,
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
        "DEC-0077",
        "DEC-0075",
        "DEC-0073"
      ],
      "tokens": 609,
      "true_positives": 1
    },
    {
      "chars": 3191,
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
        "DEC-0040",
        "DEC-0028",
        "DEC-0157",
        "DEC-0130"
      ],
      "tokens": 798,
      "true_positives": 1
    },
    {
      "chars": 2926,
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
        "DEC-0123",
        "DEC-0089",
        "DEC-0079",
        "DEC-0063"
      ],
      "tokens": 732,
      "true_positives": 2
    },
    {
      "chars": 1504,
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
        "DEC-0059",
        "DEC-0052",
        "DEC-0010",
        "DEC-0071"
      ],
      "tokens": 376,
      "true_positives": 1
    },
    {
      "chars": 2224,
      "empty": false,
      "expected": [
        "DEC-0043",
        "DEC-0053"
      ],
      "id": "q30",
      "objective": "Définir l'identité d'agent indépendante du modèle et du harnais",
      "precision": 0.2,
      "recall": 0.5,
      "retrieved": [
        "DEC-0045",
        "DEC-0043",
        "DEC-0070",
        "DEC-0052",
        "DEC-0161"
      ],
      "tokens": 556,
      "true_positives": 1
    },
    {
      "chars": 3188,
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
        "DEC-0093",
        "DEC-0073",
        "DEC-0156"
      ],
      "tokens": 797,
      "true_positives": 2
    },
    {
      "chars": 4946,
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
        "DEC-0165",
        "DEC-0085",
        "DEC-0159"
      ],
      "tokens": 1237,
      "true_positives": 1
    },
    {
      "chars": 3158,
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
        "DEC-0186",
        "DEC-0159",
        "DEC-0135",
        "DEC-0182"
      ],
      "tokens": 790,
      "true_positives": 2
    },
    {
      "chars": 1968,
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
        "DEC-0185",
        "DEC-0159",
        "DEC-0049",
        "DEC-0016"
      ],
      "tokens": 492,
      "true_positives": 2
    },
    {
      "chars": 4669,
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
        "DEC-0021",
        "DEC-0164",
        "DEC-0110",
        "DEC-0109"
      ],
      "tokens": 1168,
      "true_positives": 1
    },
    {
      "chars": 3810,
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
        "DEC-0127",
        "DEC-0114",
        "DEC-0110"
      ],
      "tokens": 953,
      "true_positives": 1
    },
    {
      "chars": 1614,
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
        "DEC-0090",
        "DEC-0076",
        "DEC-0061",
        "DEC-0056"
      ],
      "tokens": 404,
      "true_positives": 1
    },
    {
      "chars": 1843,
      "empty": false,
      "expected": [
        "DEC-0060"
      ],
      "id": "q38",
      "objective": "Durcir les en-têtes de sécurité au edge (HSTS, nosniff)",
      "precision": 0.5,
      "recall": 1.0,
      "retrieved": [
        "DEC-0060",
        "DEC-0156"
      ],
      "tokens": 461,
      "true_positives": 1
    },
    {
      "chars": 1789,
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
        "DEC-0182",
        "DEC-0090",
        "DEC-0076",
        "DEC-0056"
      ],
      "tokens": 448,
      "true_positives": 1
    },
    {
      "chars": 2087,
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
        "DEC-0033",
        "DEC-0045",
        "DEC-0128"
      ],
      "tokens": 522,
      "true_positives": 1
    },
    {
      "chars": 2937,
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
        "DEC-0161"
      ],
      "tokens": 735,
      "true_positives": 2
    },
    {
      "chars": 1553,
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
        "DEC-0053",
        "DEC-0043",
        "DEC-0055",
        "DEC-0070",
        "DEC-0052"
      ],
      "tokens": 389,
      "true_positives": 2
    },
    {
      "chars": 3271,
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
        "DEC-0083",
        "DEC-0047"
      ],
      "tokens": 818,
      "true_positives": 1
    },
    {
      "chars": 4561,
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
        "DEC-0134",
        "DEC-0114",
        "DEC-0110",
        "DEC-0107"
      ],
      "tokens": 1141,
      "true_positives": 1
    },
    {
      "chars": 4129,
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
        "DEC-0183",
        "DEC-0157",
        "DEC-0121",
        "DEC-0191"
      ],
      "tokens": 1033,
      "true_positives": 1
    }
  ],
  "project_id": "2a836038-153c-41cf-879a-73bd794760b0",
  "queries": {
    "count": 45,
    "format": "studio.eval.dec-queries/v1",
    "limit": 5,
    "max_chars": 12000,
    "path": "tests/eval/dec_queries.json"
  }
}
```
<!-- DEC_RELEVANCE_METRICS_END -->
