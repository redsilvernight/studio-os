# Pertinence des décisions — P07 (sélection de `studio_prepare_context`)

- Projet : Studio OS (`2a836038-153c-41cf-879a-73bd794760b0`)
- Corpus : `tests/eval/dec_corpus.json` (159 décisions serveur, snapshot lecture seule)
- Requêtes : `tests/eval/dec_queries.json` (45 objectifs)
- Sélection : `studio_api.services.project_context._select_decisions` (limit=5, max_chars=12000)
- Baseline : `docs/DEC_RELEVANCE_BASELINE_P00.md` (P00, figée — bloc machine relu)
- Tokens : approximation `ceil(caractères / 4)` sur les corps effectivement retournés

## Commande

```
uv run python -m scripts.dec_relevance_eval --root . --check   # exit 1 si périmé
uv run python -m scripts.dec_relevance_eval --root . --apply   # (ré)écrit ce rapport
```

## Méthodologie

La logique de sélection réelle est importée depuis `services/api` et rejouée sans
base de données : la frontière de service `decisions.list_decisions` est remplacée
par le corpus versionné, si bien que le filtre `superseded`, le raccourci
`linked_to_task`, l'ordre (lien, score pondéré, `accepted`, récence, `readable_id`),
`limit` et le budget de texte sont ceux du serveur. Les requêtes n'ont pas de
`task_id` : elles mesurent le recouvrement lexical pur, seule relation disponible
pour un objectif libre. Aucun LLM, aucun aléa, aucun embedding.

## Paramètres retenus

| Réglage | Valeur | Rôle |
|---|---|---|
| `DECISION_TITLE_WEIGHT` | 3.0 | un terme trouvé dans le titre vaut ce coefficient fois son poids, dans le corps une fois (jamais les deux) |
| `DECISION_MIN_MATCHED_TERMS` | 2 | un terme-titre isolé suffit, un titre est un sujet |
| `DECISION_MIN_RELATIVE_SCORE` | 0.25 | seuil relatif : une décision ne part que si elle atteint cette fraction du meilleur score |

Le poids d'un terme est sa fréquence inverse de document sur les décisions
candidates, `ln((N + 1) / (df + 0.5))` : `statut`, `via`, `serveur` ou `studio`
apparaissent dans presque tous les corps et ne prouvent plus rien, `md5`, `hsts` ou
`heartbeat` pèsent lourd. Les deux seuils sont sans dimension — le poids suit la
taille du vault, le ratio suit l'objectif — donc aucun des deux ne dépend du corpus
ou de la requête. Une décision liée à la tâche demandée court-circuite les deux :
le lien structurel prime sur le lexique, comme en P00.

## Agrégat P00 vs P07

| Métrique | P00 | P07 | Écart |
|---|---|---|---|
| Requêtes | 45 | 45 | — |
| Réponses `decisions: []` | 0.0 % | 0.0 % | +0.0 pts |
| Précision micro | 25.7 % | 38.7 % | +13.1 pts |
| Rappel micro | 75.0 % | 72.4 % | -2.6 pts |
| Précision macro | 26.0 % | 51.4 % | +25.4 pts |
| Rappel macro | 79.6 % | 77.4 % | -2.2 pts |
| Décisions retournées | 222 | 142 | — |
| Vrais positifs | 57 | 55 | -2 |
| Tokens injectés (total) | 33927 | 20376 | -39.9 % |
| Tokens par appel (moyenne) | 753.93 | 452.80 | — |

La précision micro gagne +13.1 pts pour un rappel micro de 72.4 % et 0.0 % de réponses
vides, soit -39.9 % de tokens par rapport à P00. Objectifs de P07 atteints : précision micro ≥ 35 %,
rappel micro ≥ 70 %, réponses vides ≤ 5 %, tokens ≤ P00.

## Détail par requête

| id | objectif | attendues | retournées P07 | précision P07 | rappel P00 | rappel P07 | tokens P07 |
|---|---|---|---|---|---|---|---|
| q01 | Corriger l'intégrité d'upload d'un transfert simple via Content-MD5 | DEC-0025 | DEC-0025 | 100.0 % | 100.0 % | 100.0 % | 83 |
| q02 | Reprendre un upload multipart après expiration des URLs pré-signées | DEC-0037, DEC-0033 | DEC-0037, DEC-0033, DEC-0025, DEC-0038 | 50.0 % | 100.0 % | 100.0 % | 309 |
| q03 | Ajouter un worker d'expiration des transferts et son job CLI | DEC-0020, DEC-0019 | DEC-0020 | 100.0 % | 100.0 % | 50.0 % | 73 |
| q04 | Rendre les appels réseau boto3 asynchrones via asyncio.to_thread | DEC-0026 | DEC-0026 | 100.0 % | 100.0 % | 100.0 % | 68 |
| q05 | Modifier le Git watcher pour supporter plusieurs repositories | DEC-0032 | DEC-0136, DEC-0115, DEC-0032 | 33.3 % | 100.0 % | 100.0 % | 390 |
| q06 | Trancher entre SSE et WebSocket pour les flux temps réel | DEC-0008, DEC-0018 | DEC-0008, DEC-0156, DEC-0018, DEC-0164, DEC-0157 | 40.0 % | 100.0 % | 100.0 % | 1182 |
| q07 | Mettre en place un fan-out temps réel multi-process via NOTIFY PostgreSQL | DEC-0156, DEC-0018 | DEC-0156 | 100.0 % | 50.0 % | 50.0 % | 375 |
| q08 | Ajouter une file de review pour les propositions de roadmap | DEC-0087, DEC-0049 | DEC-0087, DEC-0089, DEC-0084, DEC-0049 | 50.0 % | 50.0 % | 100.0 % | 653 |
| q09 | Créer et versionner le domaine Roadmap (cycle de vie, provenance) | DEC-0084, DEC-0085 | DEC-0084, DEC-0085 | 100.0 % | 100.0 % | 100.0 % | 555 |
| q10 | Ajouter la section roadmap au contexte borné studio_prepare_context | DEC-0086, DEC-0080 | DEC-0086, DEC-0080, DEC-0159, DEC-0085, DEC-0172 | 40.0 % | 100.0 % | 100.0 % | 1157 |
| q11 | Ajouter les filtres status et mine à la liste des tâches | DEC-0185 | DEC-0185, DEC-0161 | 50.0 % | 100.0 % | 100.0 % | 332 |
| q12 | Déprécier les outils MCP redondants de session et de claim | DEC-0186 | DEC-0186, DEC-0183 | 50.0 % | 100.0 % | 100.0 % | 487 |
| q13 | Versionner les définitions de l'AI Library par pointeur actif | DEC-0064, DEC-0065 | DEC-0064, DEC-0067, DEC-0063, DEC-0136 | 25.0 % | 50.0 % | 50.0 % | 410 |
| q14 | Configurer les choix de runtime par utilisateur (bindings User/Runtime) | DEC-0068, DEC-0070 | DEC-0068, DEC-0067, DEC-0012 | 33.3 % | 50.0 % | 50.0 % | 247 |
| q15 | Exposer la Library via une surface HTTP canonique | DEC-0071, DEC-0072 | DEC-0071, DEC-0046, DEC-0075, DEC-0057, DEC-0076 | 20.0 % | 50.0 % | 50.0 % | 372 |
| q16 | Résoudre le scope et le shadowing d'une définition Library | DEC-0065, DEC-0069 | DEC-0065, DEC-0075, DEC-0172, DEC-0074, DEC-0068 | 20.0 % | 50.0 % | 50.0 % | 626 |
| q17 | Définir les relations typées entre définitions (Library Bindings) | DEC-0067 | DEC-0067, DEC-0068 | 50.0 % | 100.0 % | 100.0 % | 162 |
| q18 | Authentifier l'humain sur le dashboard par un JWT court | DEC-0056, DEC-0142 | DEC-0110, DEC-0056, DEC-0090, DEC-0076, DEC-0061 | 20.0 % | 50.0 % | 50.0 % | 710 |
| q19 | Mettre en place un refresh token rotatif pour la session desktop | DEC-0142, DEC-0056 | DEC-0142, DEC-0182, DEC-0110, DEC-0037 | 25.0 % | 50.0 % | 50.0 % | 780 |
| q20 | Ajouter le shell desktop Tauri 2 autour du dashboard | DEC-0090, DEC-0095 | DEC-0090 | 100.0 % | 50.0 % | 50.0 % | 107 |
| q21 | Mettre en place un daemon unique supervisé côté desktop | DEC-0094, DEC-0028 | DEC-0094, DEC-0182, DEC-0142, DEC-0191 | 25.0 % | 50.0 % | 50.0 % | 569 |
| q22 | Générer les projections Claude Code et OpenCode depuis .agents | DEC-0074, DEC-0093 | DEC-0074, DEC-0172, DEC-0168, DEC-0045, DEC-0117 | 20.0 % | 50.0 % | 50.0 % | 872 |
| q23 | Robustifier le bootstrap permanent et ses cibles d'actions manuelles | DEC-0172, DEC-0181 | DEC-0172 | 100.0 % | 100.0 % | 50.0 % | 329 |
| q24 | Lancer un harness de façon non interactive avec un timeout dur | DEC-0176, DEC-0173, DEC-0177 | DEC-0176, DEC-0070 | 50.0 % | 33.3 % | 33.3 % | 199 |
| q25 | Fournir un credential éphémère de lancement lié à la tâche | DEC-0175, DEC-0173 | DEC-0182, DEC-0179, DEC-0177, DEC-0176, DEC-0175 | 20.0 % | 50.0 % | 50.0 % | 644 |
| q26 | Charger un bundle offline fusionnant .agents et la Library | DEC-0168 | DEC-0167, DEC-0168, DEC-0039, DEC-0045, DEC-0077 | 20.0 % | 100.0 % | 100.0 % | 616 |
| q27 | Ajouter le catalogue des machines actives avec statut heartbeat | DEC-0082 | DEC-0082, DEC-0028 | 50.0 % | 100.0 % | 100.0 % | 146 |
| q28 | Rendre l'autorisation transverse minimale par rôle et propriété | DEC-0036, DEC-0063 | DEC-0036 | 100.0 % | 100.0 % | 50.0 % | 71 |
| q29 | Documenter le parcours d'intégration d'un consommateur externe | DEC-0054, DEC-0055 | DEC-0054, DEC-0052, DEC-0059, DEC-0010 | 25.0 % | 50.0 % | 50.0 % | 313 |
| q30 | Définir l'identité d'agent indépendante du modèle et du harnais | DEC-0043, DEC-0053 | DEC-0128, DEC-0045, DEC-0043, DEC-0052, DEC-0070 | 20.0 % | 50.0 % | 50.0 % | 550 |
| q31 | Exposer la mémoire et le graphe locaux en lecture seule via MCP local | DEC-0047, DEC-0042 | DEC-0042, DEC-0047, DEC-0093, DEC-0156, DEC-0130 | 40.0 % | 100.0 % | 100.0 % | 920 |
| q32 | Ajouter la coordination inter-sessions en pull avec studio_sync | DEC-0157, DEC-0161 | DEC-0157, DEC-0164, DEC-0165 | 33.3 % | 50.0 % | 50.0 % | 820 |
| q33 | Rendre le claim de tâche idempotent au rejeu | DEC-0160, DEC-0159 | DEC-0160, DEC-0159, DEC-0135, DEC-0186, DEC-0165 | 40.0 % | 100.0 % | 100.0 % | 843 |
| q34 | Clôturer un travail par une séquence de handoff composite | DEC-0163, DEC-0159 | DEC-0163, DEC-0159, DEC-0016, DEC-0185, DEC-0049 | 40.0 % | 100.0 % | 100.0 % | 492 |
| q35 | Corriger la numérotation des décisions avec une séquence Postgres | DEC-0016, DEC-0088 | DEC-0016, DEC-0021 | 50.0 % | 50.0 % | 50.0 % | 139 |
| q36 | Synchroniser les IDs serveur avec les fiches ADR | DEC-0088 | DEC-0088, DEC-0191 | 50.0 % | 100.0 % | 100.0 % | 219 |
| q37 | Refondre le design system du dashboard avec un thème clair | DEC-0078, DEC-0079 | DEC-0078 | 100.0 % | 50.0 % | 50.0 % | 69 |
| q38 | Durcir les en-têtes de sécurité au edge (HSTS, nosniff) | DEC-0060 | DEC-0060 | 100.0 % | 100.0 % | 100.0 % | 86 |
| q39 | Mettre en place une politique CSP progressive sur le dashboard | DEC-0061 | DEC-0061, DEC-0182 | 50.0 % | 100.0 % | 100.0 % | 203 |
| q40 | Forcer l'endpoint S3 public pour les URLs pré-signées | DEC-0004 | DEC-0004, DEC-0033, DEC-0037, DEC-0045 | 25.0 % | 100.0 % | 100.0 % | 310 |
| q41 | Enregistrer publiquement un Agent comme identité de provenance | DEC-0045, DEC-0062 | DEC-0045, DEC-0062, DEC-0043, DEC-0084, DEC-0069 | 40.0 % | 100.0 % | 100.0 % | 593 |
| q42 | Ajouter les métadonnées runtime agent_profile, harness, provider, model | DEC-0053, DEC-0043 | DEC-0053, DEC-0043, DEC-0055, DEC-0070, DEC-0052 | 40.0 % | 100.0 % | 100.0 % | 389 |
| q43 | Enrôler le poste desktop avec une seule entrée secrète sur le pont local | DEC-0130 | DEC-0130, DEC-0117 | 50.0 % | 100.0 % | 100.0 % | 413 |
| q44 | Négocier la version client/serveur de façon additive | DEC-0127 | DEC-0127 | 100.0 % | 100.0 % | 100.0 % | 227 |
| q45 | Provisionner le premier compte via la CLI serveur studio-admin | DEC-0011 | DEC-0011, DEC-0121, DEC-0183, DEC-0141, DEC-0123 | 20.0 % | 100.0 % | 100.0 % | 1266 |

## Décisions attendues absentes en P07

| id | objectif | attendues absentes | retournées |
|---|---|---|---|
| q03 | Ajouter un worker d'expiration des transferts et son job CLI | DEC-0019 | DEC-0020 |
| q07 | Mettre en place un fan-out temps réel multi-process via NOTIFY PostgreSQL | DEC-0018 | DEC-0156 |
| q13 | Versionner les définitions de l'AI Library par pointeur actif | DEC-0065 | DEC-0064, DEC-0067, DEC-0063, DEC-0136 |
| q14 | Configurer les choix de runtime par utilisateur (bindings User/Runtime) | DEC-0070 | DEC-0068, DEC-0067, DEC-0012 |
| q15 | Exposer la Library via une surface HTTP canonique | DEC-0072 | DEC-0071, DEC-0046, DEC-0075, DEC-0057, DEC-0076 |
| q16 | Résoudre le scope et le shadowing d'une définition Library | DEC-0069 | DEC-0065, DEC-0075, DEC-0172, DEC-0074, DEC-0068 |
| q18 | Authentifier l'humain sur le dashboard par un JWT court | DEC-0142 | DEC-0110, DEC-0056, DEC-0090, DEC-0076, DEC-0061 |
| q19 | Mettre en place un refresh token rotatif pour la session desktop | DEC-0056 | DEC-0142, DEC-0182, DEC-0110, DEC-0037 |
| q20 | Ajouter le shell desktop Tauri 2 autour du dashboard | DEC-0095 | DEC-0090 |
| q21 | Mettre en place un daemon unique supervisé côté desktop | DEC-0028 | DEC-0094, DEC-0182, DEC-0142, DEC-0191 |
| q22 | Générer les projections Claude Code et OpenCode depuis .agents | DEC-0093 | DEC-0074, DEC-0172, DEC-0168, DEC-0045, DEC-0117 |
| q23 | Robustifier le bootstrap permanent et ses cibles d'actions manuelles | DEC-0181 | DEC-0172 |
| q24 | Lancer un harness de façon non interactive avec un timeout dur | DEC-0173, DEC-0177 | DEC-0176, DEC-0070 |
| q25 | Fournir un credential éphémère de lancement lié à la tâche | DEC-0173 | DEC-0182, DEC-0179, DEC-0177, DEC-0176, DEC-0175 |
| q28 | Rendre l'autorisation transverse minimale par rôle et propriété | DEC-0063 | DEC-0036 |
| q29 | Documenter le parcours d'intégration d'un consommateur externe | DEC-0055 | DEC-0054, DEC-0052, DEC-0059, DEC-0010 |
| q30 | Définir l'identité d'agent indépendante du modèle et du harnais | DEC-0053 | DEC-0128, DEC-0045, DEC-0043, DEC-0052, DEC-0070 |
| q32 | Ajouter la coordination inter-sessions en pull avec studio_sync | DEC-0161 | DEC-0157, DEC-0164, DEC-0165 |
| q35 | Corriger la numérotation des décisions avec une séquence Postgres | DEC-0088 | DEC-0016, DEC-0021 |
| q37 | Refondre le design system du dashboard avec un thème clair | DEC-0079 | DEC-0078 |

4 de ces décisions attendues ne partagent aucun terme exact avec l'objectif (DEC-0018, DEC-0173, DEC-0177, DEC-0055) : inatteignables par tout réglage lexical, elles le sont aussi en P00. Le plafond lexical du jeu de requêtes est donc 72 sur 76 attendus, et le rappel micro maximal atteignable 94.7 %.

## Métriques machine (vérifiées par `--check`)

<!-- DEC_RELEVANCE_P07_METRICS_BEGIN -->
```json
{
  "aggregate": {
    "attainable_recall": 0.9474,
    "chars_total": 81435,
    "empty_answers": 0,
    "empty_rate": 0.0,
    "expected_total": 76,
    "lexically_unreachable_total": 4,
    "macro_precision": 0.5144,
    "macro_recall": 0.7741,
    "micro_precision": 0.3873,
    "micro_recall": 0.7237,
    "queries": 45,
    "retrieved_total": 142,
    "tokens_per_call_mean": 452.8,
    "tokens_total": 20376,
    "true_positives": 55
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
  "format": "studio.eval.dec-relevance/v2",
  "per_query": [
    {
      "baseline_recall": 1.0,
      "chars": 331,
      "empty": false,
      "expected": [
        "DEC-0025"
      ],
      "id": "q01",
      "lexically_unreachable": [],
      "objective": "Corriger l'intégrité d'upload d'un transfert simple via Content-MD5",
      "precision": 1.0,
      "recall": 1.0,
      "retrieved": [
        "DEC-0025"
      ],
      "tokens": 83,
      "true_positives": 1
    },
    {
      "baseline_recall": 1.0,
      "chars": 1236,
      "empty": false,
      "expected": [
        "DEC-0037",
        "DEC-0033"
      ],
      "id": "q02",
      "lexically_unreachable": [],
      "objective": "Reprendre un upload multipart après expiration des URLs pré-signées",
      "precision": 0.5,
      "recall": 1.0,
      "retrieved": [
        "DEC-0037",
        "DEC-0033",
        "DEC-0025",
        "DEC-0038"
      ],
      "tokens": 309,
      "true_positives": 2
    },
    {
      "baseline_recall": 1.0,
      "chars": 289,
      "empty": false,
      "expected": [
        "DEC-0020",
        "DEC-0019"
      ],
      "id": "q03",
      "lexically_unreachable": [],
      "objective": "Ajouter un worker d'expiration des transferts et son job CLI",
      "precision": 1.0,
      "recall": 0.5,
      "retrieved": [
        "DEC-0020"
      ],
      "tokens": 73,
      "true_positives": 1
    },
    {
      "baseline_recall": 1.0,
      "chars": 272,
      "empty": false,
      "expected": [
        "DEC-0026"
      ],
      "id": "q04",
      "lexically_unreachable": [],
      "objective": "Rendre les appels réseau boto3 asynchrones via asyncio.to_thread",
      "precision": 1.0,
      "recall": 1.0,
      "retrieved": [
        "DEC-0026"
      ],
      "tokens": 68,
      "true_positives": 1
    },
    {
      "baseline_recall": 1.0,
      "chars": 1559,
      "empty": false,
      "expected": [
        "DEC-0032"
      ],
      "id": "q05",
      "lexically_unreachable": [],
      "objective": "Modifier le Git watcher pour supporter plusieurs repositories",
      "precision": 0.3333,
      "recall": 1.0,
      "retrieved": [
        "DEC-0136",
        "DEC-0115",
        "DEC-0032"
      ],
      "tokens": 390,
      "true_positives": 1
    },
    {
      "baseline_recall": 1.0,
      "chars": 4727,
      "empty": false,
      "expected": [
        "DEC-0008",
        "DEC-0018"
      ],
      "id": "q06",
      "lexically_unreachable": [],
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
      "baseline_recall": 0.5,
      "chars": 1500,
      "empty": false,
      "expected": [
        "DEC-0156",
        "DEC-0018"
      ],
      "id": "q07",
      "lexically_unreachable": [
        "DEC-0018"
      ],
      "objective": "Mettre en place un fan-out temps réel multi-process via NOTIFY PostgreSQL",
      "precision": 1.0,
      "recall": 0.5,
      "retrieved": [
        "DEC-0156"
      ],
      "tokens": 375,
      "true_positives": 1
    },
    {
      "baseline_recall": 0.5,
      "chars": 2609,
      "empty": false,
      "expected": [
        "DEC-0087",
        "DEC-0049"
      ],
      "id": "q08",
      "lexically_unreachable": [],
      "objective": "Ajouter une file de review pour les propositions de roadmap",
      "precision": 0.5,
      "recall": 1.0,
      "retrieved": [
        "DEC-0087",
        "DEC-0089",
        "DEC-0084",
        "DEC-0049"
      ],
      "tokens": 653,
      "true_positives": 2
    },
    {
      "baseline_recall": 1.0,
      "chars": 2218,
      "empty": false,
      "expected": [
        "DEC-0084",
        "DEC-0085"
      ],
      "id": "q09",
      "lexically_unreachable": [],
      "objective": "Créer et versionner le domaine Roadmap (cycle de vie, provenance)",
      "precision": 1.0,
      "recall": 1.0,
      "retrieved": [
        "DEC-0084",
        "DEC-0085"
      ],
      "tokens": 555,
      "true_positives": 2
    },
    {
      "baseline_recall": 1.0,
      "chars": 4627,
      "empty": false,
      "expected": [
        "DEC-0086",
        "DEC-0080"
      ],
      "id": "q10",
      "lexically_unreachable": [],
      "objective": "Ajouter la section roadmap au contexte borné studio_prepare_context",
      "precision": 0.4,
      "recall": 1.0,
      "retrieved": [
        "DEC-0086",
        "DEC-0080",
        "DEC-0159",
        "DEC-0085",
        "DEC-0172"
      ],
      "tokens": 1157,
      "true_positives": 2
    },
    {
      "baseline_recall": 1.0,
      "chars": 1327,
      "empty": false,
      "expected": [
        "DEC-0185"
      ],
      "id": "q11",
      "lexically_unreachable": [],
      "objective": "Ajouter les filtres status et mine à la liste des tâches",
      "precision": 0.5,
      "recall": 1.0,
      "retrieved": [
        "DEC-0185",
        "DEC-0161"
      ],
      "tokens": 332,
      "true_positives": 1
    },
    {
      "baseline_recall": 1.0,
      "chars": 1945,
      "empty": false,
      "expected": [
        "DEC-0186"
      ],
      "id": "q12",
      "lexically_unreachable": [],
      "objective": "Déprécier les outils MCP redondants de session et de claim",
      "precision": 0.5,
      "recall": 1.0,
      "retrieved": [
        "DEC-0186",
        "DEC-0183"
      ],
      "tokens": 487,
      "true_positives": 1
    },
    {
      "baseline_recall": 0.5,
      "chars": 1640,
      "empty": false,
      "expected": [
        "DEC-0064",
        "DEC-0065"
      ],
      "id": "q13",
      "lexically_unreachable": [],
      "objective": "Versionner les définitions de l'AI Library par pointeur actif",
      "precision": 0.25,
      "recall": 0.5,
      "retrieved": [
        "DEC-0064",
        "DEC-0067",
        "DEC-0063",
        "DEC-0136"
      ],
      "tokens": 410,
      "true_positives": 1
    },
    {
      "baseline_recall": 0.5,
      "chars": 987,
      "empty": false,
      "expected": [
        "DEC-0068",
        "DEC-0070"
      ],
      "id": "q14",
      "lexically_unreachable": [],
      "objective": "Configurer les choix de runtime par utilisateur (bindings User/Runtime)",
      "precision": 0.3333,
      "recall": 0.5,
      "retrieved": [
        "DEC-0068",
        "DEC-0067",
        "DEC-0012"
      ],
      "tokens": 247,
      "true_positives": 1
    },
    {
      "baseline_recall": 0.5,
      "chars": 1485,
      "empty": false,
      "expected": [
        "DEC-0071",
        "DEC-0072"
      ],
      "id": "q15",
      "lexically_unreachable": [],
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
      "baseline_recall": 0.5,
      "chars": 2504,
      "empty": false,
      "expected": [
        "DEC-0065",
        "DEC-0069"
      ],
      "id": "q16",
      "lexically_unreachable": [],
      "objective": "Résoudre le scope et le shadowing d'une définition Library",
      "precision": 0.2,
      "recall": 0.5,
      "retrieved": [
        "DEC-0065",
        "DEC-0075",
        "DEC-0172",
        "DEC-0074",
        "DEC-0068"
      ],
      "tokens": 626,
      "true_positives": 1
    },
    {
      "baseline_recall": 1.0,
      "chars": 647,
      "empty": false,
      "expected": [
        "DEC-0067"
      ],
      "id": "q17",
      "lexically_unreachable": [],
      "objective": "Définir les relations typées entre définitions (Library Bindings)",
      "precision": 0.5,
      "recall": 1.0,
      "retrieved": [
        "DEC-0067",
        "DEC-0068"
      ],
      "tokens": 162,
      "true_positives": 1
    },
    {
      "baseline_recall": 0.5,
      "chars": 2839,
      "empty": false,
      "expected": [
        "DEC-0056",
        "DEC-0142"
      ],
      "id": "q18",
      "lexically_unreachable": [],
      "objective": "Authentifier l'humain sur le dashboard par un JWT court",
      "precision": 0.2,
      "recall": 0.5,
      "retrieved": [
        "DEC-0110",
        "DEC-0056",
        "DEC-0090",
        "DEC-0076",
        "DEC-0061"
      ],
      "tokens": 710,
      "true_positives": 1
    },
    {
      "baseline_recall": 0.5,
      "chars": 3119,
      "empty": false,
      "expected": [
        "DEC-0142",
        "DEC-0056"
      ],
      "id": "q19",
      "lexically_unreachable": [],
      "objective": "Mettre en place un refresh token rotatif pour la session desktop",
      "precision": 0.25,
      "recall": 0.5,
      "retrieved": [
        "DEC-0142",
        "DEC-0182",
        "DEC-0110",
        "DEC-0037"
      ],
      "tokens": 780,
      "true_positives": 1
    },
    {
      "baseline_recall": 0.5,
      "chars": 426,
      "empty": false,
      "expected": [
        "DEC-0090",
        "DEC-0095"
      ],
      "id": "q20",
      "lexically_unreachable": [],
      "objective": "Ajouter le shell desktop Tauri 2 autour du dashboard",
      "precision": 1.0,
      "recall": 0.5,
      "retrieved": [
        "DEC-0090"
      ],
      "tokens": 107,
      "true_positives": 1
    },
    {
      "baseline_recall": 0.5,
      "chars": 2276,
      "empty": false,
      "expected": [
        "DEC-0094",
        "DEC-0028"
      ],
      "id": "q21",
      "lexically_unreachable": [],
      "objective": "Mettre en place un daemon unique supervisé côté desktop",
      "precision": 0.25,
      "recall": 0.5,
      "retrieved": [
        "DEC-0094",
        "DEC-0182",
        "DEC-0142",
        "DEC-0191"
      ],
      "tokens": 569,
      "true_positives": 1
    },
    {
      "baseline_recall": 0.5,
      "chars": 3485,
      "empty": false,
      "expected": [
        "DEC-0074",
        "DEC-0093"
      ],
      "id": "q22",
      "lexically_unreachable": [],
      "objective": "Générer les projections Claude Code et OpenCode depuis .agents",
      "precision": 0.2,
      "recall": 0.5,
      "retrieved": [
        "DEC-0074",
        "DEC-0172",
        "DEC-0168",
        "DEC-0045",
        "DEC-0117"
      ],
      "tokens": 872,
      "true_positives": 1
    },
    {
      "baseline_recall": 1.0,
      "chars": 1314,
      "empty": false,
      "expected": [
        "DEC-0172",
        "DEC-0181"
      ],
      "id": "q23",
      "lexically_unreachable": [],
      "objective": "Robustifier le bootstrap permanent et ses cibles d'actions manuelles",
      "precision": 1.0,
      "recall": 0.5,
      "retrieved": [
        "DEC-0172"
      ],
      "tokens": 329,
      "true_positives": 1
    },
    {
      "baseline_recall": 0.3333,
      "chars": 794,
      "empty": false,
      "expected": [
        "DEC-0176",
        "DEC-0173",
        "DEC-0177"
      ],
      "id": "q24",
      "lexically_unreachable": [
        "DEC-0173",
        "DEC-0177"
      ],
      "objective": "Lancer un harness de façon non interactive avec un timeout dur",
      "precision": 0.5,
      "recall": 0.3333,
      "retrieved": [
        "DEC-0176",
        "DEC-0070"
      ],
      "tokens": 199,
      "true_positives": 1
    },
    {
      "baseline_recall": 0.5,
      "chars": 2576,
      "empty": false,
      "expected": [
        "DEC-0175",
        "DEC-0173"
      ],
      "id": "q25",
      "lexically_unreachable": [],
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
      "baseline_recall": 1.0,
      "chars": 2462,
      "empty": false,
      "expected": [
        "DEC-0168"
      ],
      "id": "q26",
      "lexically_unreachable": [],
      "objective": "Charger un bundle offline fusionnant .agents et la Library",
      "precision": 0.2,
      "recall": 1.0,
      "retrieved": [
        "DEC-0167",
        "DEC-0168",
        "DEC-0039",
        "DEC-0045",
        "DEC-0077"
      ],
      "tokens": 616,
      "true_positives": 1
    },
    {
      "baseline_recall": 1.0,
      "chars": 581,
      "empty": false,
      "expected": [
        "DEC-0082"
      ],
      "id": "q27",
      "lexically_unreachable": [],
      "objective": "Ajouter le catalogue des machines actives avec statut heartbeat",
      "precision": 0.5,
      "recall": 1.0,
      "retrieved": [
        "DEC-0082",
        "DEC-0028"
      ],
      "tokens": 146,
      "true_positives": 1
    },
    {
      "baseline_recall": 1.0,
      "chars": 283,
      "empty": false,
      "expected": [
        "DEC-0036",
        "DEC-0063"
      ],
      "id": "q28",
      "lexically_unreachable": [],
      "objective": "Rendre l'autorisation transverse minimale par rôle et propriété",
      "precision": 1.0,
      "recall": 0.5,
      "retrieved": [
        "DEC-0036"
      ],
      "tokens": 71,
      "true_positives": 1
    },
    {
      "baseline_recall": 0.5,
      "chars": 1249,
      "empty": false,
      "expected": [
        "DEC-0054",
        "DEC-0055"
      ],
      "id": "q29",
      "lexically_unreachable": [
        "DEC-0055"
      ],
      "objective": "Documenter le parcours d'intégration d'un consommateur externe",
      "precision": 0.25,
      "recall": 0.5,
      "retrieved": [
        "DEC-0054",
        "DEC-0052",
        "DEC-0059",
        "DEC-0010"
      ],
      "tokens": 313,
      "true_positives": 1
    },
    {
      "baseline_recall": 0.5,
      "chars": 2197,
      "empty": false,
      "expected": [
        "DEC-0043",
        "DEC-0053"
      ],
      "id": "q30",
      "lexically_unreachable": [],
      "objective": "Définir l'identité d'agent indépendante du modèle et du harnais",
      "precision": 0.2,
      "recall": 0.5,
      "retrieved": [
        "DEC-0128",
        "DEC-0045",
        "DEC-0043",
        "DEC-0052",
        "DEC-0070"
      ],
      "tokens": 550,
      "true_positives": 1
    },
    {
      "baseline_recall": 1.0,
      "chars": 3677,
      "empty": false,
      "expected": [
        "DEC-0047",
        "DEC-0042"
      ],
      "id": "q31",
      "lexically_unreachable": [],
      "objective": "Exposer la mémoire et le graphe locaux en lecture seule via MCP local",
      "precision": 0.4,
      "recall": 1.0,
      "retrieved": [
        "DEC-0042",
        "DEC-0047",
        "DEC-0093",
        "DEC-0156",
        "DEC-0130"
      ],
      "tokens": 920,
      "true_positives": 2
    },
    {
      "baseline_recall": 0.5,
      "chars": 3279,
      "empty": false,
      "expected": [
        "DEC-0157",
        "DEC-0161"
      ],
      "id": "q32",
      "lexically_unreachable": [],
      "objective": "Ajouter la coordination inter-sessions en pull avec studio_sync",
      "precision": 0.3333,
      "recall": 0.5,
      "retrieved": [
        "DEC-0157",
        "DEC-0164",
        "DEC-0165"
      ],
      "tokens": 820,
      "true_positives": 1
    },
    {
      "baseline_recall": 1.0,
      "chars": 3371,
      "empty": false,
      "expected": [
        "DEC-0160",
        "DEC-0159"
      ],
      "id": "q33",
      "lexically_unreachable": [],
      "objective": "Rendre le claim de tâche idempotent au rejeu",
      "precision": 0.4,
      "recall": 1.0,
      "retrieved": [
        "DEC-0160",
        "DEC-0159",
        "DEC-0135",
        "DEC-0186",
        "DEC-0165"
      ],
      "tokens": 843,
      "true_positives": 2
    },
    {
      "baseline_recall": 1.0,
      "chars": 1968,
      "empty": false,
      "expected": [
        "DEC-0163",
        "DEC-0159"
      ],
      "id": "q34",
      "lexically_unreachable": [],
      "objective": "Clôturer un travail par une séquence de handoff composite",
      "precision": 0.4,
      "recall": 1.0,
      "retrieved": [
        "DEC-0163",
        "DEC-0159",
        "DEC-0016",
        "DEC-0185",
        "DEC-0049"
      ],
      "tokens": 492,
      "true_positives": 2
    },
    {
      "baseline_recall": 0.5,
      "chars": 553,
      "empty": false,
      "expected": [
        "DEC-0016",
        "DEC-0088"
      ],
      "id": "q35",
      "lexically_unreachable": [],
      "objective": "Corriger la numérotation des décisions avec une séquence Postgres",
      "precision": 0.5,
      "recall": 0.5,
      "retrieved": [
        "DEC-0016",
        "DEC-0021"
      ],
      "tokens": 139,
      "true_positives": 1
    },
    {
      "baseline_recall": 1.0,
      "chars": 873,
      "empty": false,
      "expected": [
        "DEC-0088"
      ],
      "id": "q36",
      "lexically_unreachable": [],
      "objective": "Synchroniser les IDs serveur avec les fiches ADR",
      "precision": 0.5,
      "recall": 1.0,
      "retrieved": [
        "DEC-0088",
        "DEC-0191"
      ],
      "tokens": 219,
      "true_positives": 1
    },
    {
      "baseline_recall": 0.5,
      "chars": 275,
      "empty": false,
      "expected": [
        "DEC-0078",
        "DEC-0079"
      ],
      "id": "q37",
      "lexically_unreachable": [],
      "objective": "Refondre le design system du dashboard avec un thème clair",
      "precision": 1.0,
      "recall": 0.5,
      "retrieved": [
        "DEC-0078"
      ],
      "tokens": 69,
      "true_positives": 1
    },
    {
      "baseline_recall": 1.0,
      "chars": 343,
      "empty": false,
      "expected": [
        "DEC-0060"
      ],
      "id": "q38",
      "lexically_unreachable": [],
      "objective": "Durcir les en-têtes de sécurité au edge (HSTS, nosniff)",
      "precision": 1.0,
      "recall": 1.0,
      "retrieved": [
        "DEC-0060"
      ],
      "tokens": 86,
      "true_positives": 1
    },
    {
      "baseline_recall": 1.0,
      "chars": 809,
      "empty": false,
      "expected": [
        "DEC-0061"
      ],
      "id": "q39",
      "lexically_unreachable": [],
      "objective": "Mettre en place une politique CSP progressive sur le dashboard",
      "precision": 0.5,
      "recall": 1.0,
      "retrieved": [
        "DEC-0061",
        "DEC-0182"
      ],
      "tokens": 203,
      "true_positives": 1
    },
    {
      "baseline_recall": 1.0,
      "chars": 1239,
      "empty": false,
      "expected": [
        "DEC-0004"
      ],
      "id": "q40",
      "lexically_unreachable": [],
      "objective": "Forcer l'endpoint S3 public pour les URLs pré-signées",
      "precision": 0.25,
      "recall": 1.0,
      "retrieved": [
        "DEC-0004",
        "DEC-0033",
        "DEC-0037",
        "DEC-0045"
      ],
      "tokens": 310,
      "true_positives": 1
    },
    {
      "baseline_recall": 1.0,
      "chars": 2372,
      "empty": false,
      "expected": [
        "DEC-0045",
        "DEC-0062"
      ],
      "id": "q41",
      "lexically_unreachable": [],
      "objective": "Enregistrer publiquement un Agent comme identité de provenance",
      "precision": 0.4,
      "recall": 1.0,
      "retrieved": [
        "DEC-0045",
        "DEC-0062",
        "DEC-0043",
        "DEC-0084",
        "DEC-0069"
      ],
      "tokens": 593,
      "true_positives": 2
    },
    {
      "baseline_recall": 1.0,
      "chars": 1553,
      "empty": false,
      "expected": [
        "DEC-0053",
        "DEC-0043"
      ],
      "id": "q42",
      "lexically_unreachable": [],
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
      "baseline_recall": 1.0,
      "chars": 1649,
      "empty": false,
      "expected": [
        "DEC-0130"
      ],
      "id": "q43",
      "lexically_unreachable": [],
      "objective": "Enrôler le poste desktop avec une seule entrée secrète sur le pont local",
      "precision": 0.5,
      "recall": 1.0,
      "retrieved": [
        "DEC-0130",
        "DEC-0117"
      ],
      "tokens": 413,
      "true_positives": 1
    },
    {
      "baseline_recall": 1.0,
      "chars": 907,
      "empty": false,
      "expected": [
        "DEC-0127"
      ],
      "id": "q44",
      "lexically_unreachable": [],
      "objective": "Négocier la version client/serveur de façon additive",
      "precision": 1.0,
      "recall": 1.0,
      "retrieved": [
        "DEC-0127"
      ],
      "tokens": 227,
      "true_positives": 1
    },
    {
      "baseline_recall": 1.0,
      "chars": 5063,
      "empty": false,
      "expected": [
        "DEC-0011"
      ],
      "id": "q45",
      "lexically_unreachable": [],
      "objective": "Provisionner le premier compte via la CLI serveur studio-admin",
      "precision": 0.2,
      "recall": 1.0,
      "retrieved": [
        "DEC-0011",
        "DEC-0121",
        "DEC-0183",
        "DEC-0141",
        "DEC-0123"
      ],
      "tokens": 1266,
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
  },
  "selection_rules": {
    "min_matched_terms": 2,
    "min_relative_score": 0.25,
    "title_weight": 3.0
  }
}
```
<!-- DEC_RELEVANCE_P07_METRICS_END -->
