# Latence de `prepare_project_context` — P16

## Commande

```
uv run python -m scripts.context_latency_eval --root . --apply
```

## Méthodologie

- Corpus : `tests/eval/dec_corpus.json` chargé dans un projet jetable sur un vrai PostgreSQL, à la fois comme 159 décisions (table `decisions`) et comme 159 notes vault de type `decision`. Le `task_id` des décisions n'est pas reporté (aucune tâche correspondante dans le projet jetable).
- Requêtes : `tests/eval/dec_queries.json` (45 objectifs), rejouées en processus via `studio_api.services.project_context.prepare_project_context` (limit=5, max_chars=12000), avec un principal admin réel chargé par `load_principal`.
- 2 passes d'échauffement sur toutes les requêtes, puis 10 mesures par requête avec `time.perf_counter` ; une session SQLAlchemy neuve par appel, comme une requête HTTP.
- Percentiles par interpolation linéaire ; la mesure exclut le transport HTTP/MCP.
- Le projet, ses décisions, ses notes, la machine et l'utilisateur sont supprimés en fin d'exécution.

## Environnement

- OS : Windows-11-10.0.26200-SP0
- Python : 3.14.7
- PostgreSQL : 16.15

## Résultat global

| Mesures | p50 (ms) | p95 (ms) | max (ms) | moyenne (ms) |
|---|---|---|---|---|
| 450 | 90.99 | 122.27 | 183.90 | 93.73 |

## Seuil et verdict

Seuil d'acceptation : p95 global ≤ 250 ms en processus.

Verdict : **acceptable** : le p95 global respecte le seuil. (p95 = 122.27 ms)

## Détail par requête

| id | p50 (ms) | p95 (ms) | max (ms) | moyenne (ms) |
|---|---|---|---|---|
| q01 | 98.93 | 117.20 | 117.79 | 104.65 |
| q02 | 83.84 | 96.19 | 102.27 | 85.00 |
| q03 | 86.11 | 94.23 | 94.97 | 86.74 |
| q04 | 97.87 | 102.86 | 103.17 | 96.73 |
| q05 | 75.49 | 80.02 | 81.57 | 75.53 |
| q06 | 85.89 | 100.19 | 100.65 | 87.73 |
| q07 | 106.89 | 118.62 | 120.23 | 108.13 |
| q08 | 88.44 | 97.25 | 97.98 | 88.94 |
| q09 | 97.54 | 113.96 | 120.13 | 101.61 |
| q10 | 113.08 | 119.34 | 119.41 | 112.97 |
| q11 | 99.40 | 113.20 | 113.33 | 100.61 |
| q12 | 97.44 | 103.85 | 104.48 | 96.68 |
| q13 | 87.42 | 179.19 | 181.22 | 109.60 |
| q14 | 84.04 | 95.03 | 99.91 | 85.04 |
| q15 | 94.10 | 104.36 | 107.24 | 95.41 |
| q16 | 73.97 | 105.87 | 114.78 | 80.15 |
| q17 | 82.09 | 93.79 | 98.19 | 84.27 |
| q18 | 81.99 | 99.56 | 99.74 | 84.96 |
| q19 | 92.49 | 110.53 | 120.25 | 94.32 |
| q20 | 86.09 | 116.09 | 129.89 | 90.86 |
| q21 | 92.21 | 99.72 | 101.61 | 92.91 |
| q22 | 89.91 | 143.71 | 166.39 | 101.33 |
| q23 | 76.20 | 81.61 | 81.86 | 75.45 |
| q24 | 85.01 | 88.57 | 89.51 | 84.57 |
| q25 | 80.78 | 90.24 | 91.72 | 82.03 |
| q26 | 81.39 | 99.79 | 109.79 | 82.85 |
| q27 | 108.81 | 117.79 | 118.28 | 110.33 |
| q28 | 83.22 | 94.53 | 94.53 | 84.04 |
| q29 | 68.04 | 73.26 | 73.63 | 68.87 |
| q30 | 106.23 | 123.66 | 127.68 | 106.90 |
| q31 | 130.40 | 163.89 | 183.90 | 130.18 |
| q32 | 107.29 | 116.62 | 118.70 | 104.45 |
| q33 | 85.00 | 129.68 | 131.52 | 93.19 |
| q34 | 80.51 | 96.57 | 97.12 | 83.84 |
| q35 | 88.42 | 136.40 | 147.95 | 100.26 |
| q36 | 123.04 | 153.26 | 157.39 | 120.31 |
| q37 | 84.98 | 90.09 | 90.82 | 82.99 |
| q38 | 68.13 | 96.61 | 105.41 | 73.38 |
| q39 | 71.88 | 88.91 | 95.84 | 74.22 |
| q40 | 93.09 | 107.44 | 109.02 | 92.72 |
| q41 | 84.35 | 102.81 | 106.62 | 87.86 |
| q42 | 101.56 | 115.86 | 117.49 | 103.68 |
| q43 | 101.78 | 119.64 | 125.85 | 105.90 |
| q44 | 92.61 | 103.53 | 103.76 | 94.82 |
| q45 | 112.02 | 122.86 | 123.34 | 111.03 |

## Métriques machine (structure vérifiée par `--check`)

<!-- CONTEXT_LATENCY_METRICS_BEGIN -->
```json
{
  "command": "uv run python -m scripts.context_latency_eval --root . --apply",
  "environment": {
    "os": "Windows-11-10.0.26200-SP0",
    "postgresql": "16.15",
    "python": "3.14.7"
  },
  "format": "studio.eval.context-latency/v1",
  "global": {
    "max_ms": 183.9,
    "mean_ms": 93.73,
    "p50_ms": 90.99,
    "p95_ms": 122.27
  },
  "parameters": {
    "decisions": 159,
    "limit": 5,
    "max_chars": 12000,
    "samples_per_query": 10,
    "vault_notes": 159,
    "warmup_passes": 2
  },
  "per_query": [
    {
      "id": "q01",
      "max_ms": 117.79,
      "mean_ms": 104.65,
      "p50_ms": 98.93,
      "p95_ms": 117.2
    },
    {
      "id": "q02",
      "max_ms": 102.27,
      "mean_ms": 85.0,
      "p50_ms": 83.84,
      "p95_ms": 96.19
    },
    {
      "id": "q03",
      "max_ms": 94.97,
      "mean_ms": 86.74,
      "p50_ms": 86.11,
      "p95_ms": 94.23
    },
    {
      "id": "q04",
      "max_ms": 103.17,
      "mean_ms": 96.73,
      "p50_ms": 97.87,
      "p95_ms": 102.86
    },
    {
      "id": "q05",
      "max_ms": 81.57,
      "mean_ms": 75.53,
      "p50_ms": 75.49,
      "p95_ms": 80.02
    },
    {
      "id": "q06",
      "max_ms": 100.65,
      "mean_ms": 87.73,
      "p50_ms": 85.89,
      "p95_ms": 100.19
    },
    {
      "id": "q07",
      "max_ms": 120.23,
      "mean_ms": 108.13,
      "p50_ms": 106.89,
      "p95_ms": 118.62
    },
    {
      "id": "q08",
      "max_ms": 97.98,
      "mean_ms": 88.94,
      "p50_ms": 88.44,
      "p95_ms": 97.25
    },
    {
      "id": "q09",
      "max_ms": 120.13,
      "mean_ms": 101.61,
      "p50_ms": 97.54,
      "p95_ms": 113.96
    },
    {
      "id": "q10",
      "max_ms": 119.41,
      "mean_ms": 112.97,
      "p50_ms": 113.08,
      "p95_ms": 119.34
    },
    {
      "id": "q11",
      "max_ms": 113.33,
      "mean_ms": 100.61,
      "p50_ms": 99.4,
      "p95_ms": 113.2
    },
    {
      "id": "q12",
      "max_ms": 104.48,
      "mean_ms": 96.68,
      "p50_ms": 97.44,
      "p95_ms": 103.85
    },
    {
      "id": "q13",
      "max_ms": 181.22,
      "mean_ms": 109.6,
      "p50_ms": 87.42,
      "p95_ms": 179.19
    },
    {
      "id": "q14",
      "max_ms": 99.91,
      "mean_ms": 85.04,
      "p50_ms": 84.04,
      "p95_ms": 95.03
    },
    {
      "id": "q15",
      "max_ms": 107.24,
      "mean_ms": 95.41,
      "p50_ms": 94.1,
      "p95_ms": 104.36
    },
    {
      "id": "q16",
      "max_ms": 114.78,
      "mean_ms": 80.15,
      "p50_ms": 73.97,
      "p95_ms": 105.87
    },
    {
      "id": "q17",
      "max_ms": 98.19,
      "mean_ms": 84.27,
      "p50_ms": 82.09,
      "p95_ms": 93.79
    },
    {
      "id": "q18",
      "max_ms": 99.74,
      "mean_ms": 84.96,
      "p50_ms": 81.99,
      "p95_ms": 99.56
    },
    {
      "id": "q19",
      "max_ms": 120.25,
      "mean_ms": 94.32,
      "p50_ms": 92.49,
      "p95_ms": 110.53
    },
    {
      "id": "q20",
      "max_ms": 129.89,
      "mean_ms": 90.86,
      "p50_ms": 86.09,
      "p95_ms": 116.09
    },
    {
      "id": "q21",
      "max_ms": 101.61,
      "mean_ms": 92.91,
      "p50_ms": 92.21,
      "p95_ms": 99.72
    },
    {
      "id": "q22",
      "max_ms": 166.39,
      "mean_ms": 101.33,
      "p50_ms": 89.91,
      "p95_ms": 143.71
    },
    {
      "id": "q23",
      "max_ms": 81.86,
      "mean_ms": 75.45,
      "p50_ms": 76.2,
      "p95_ms": 81.61
    },
    {
      "id": "q24",
      "max_ms": 89.51,
      "mean_ms": 84.57,
      "p50_ms": 85.01,
      "p95_ms": 88.57
    },
    {
      "id": "q25",
      "max_ms": 91.72,
      "mean_ms": 82.03,
      "p50_ms": 80.78,
      "p95_ms": 90.24
    },
    {
      "id": "q26",
      "max_ms": 109.79,
      "mean_ms": 82.85,
      "p50_ms": 81.39,
      "p95_ms": 99.79
    },
    {
      "id": "q27",
      "max_ms": 118.28,
      "mean_ms": 110.33,
      "p50_ms": 108.81,
      "p95_ms": 117.79
    },
    {
      "id": "q28",
      "max_ms": 94.53,
      "mean_ms": 84.04,
      "p50_ms": 83.22,
      "p95_ms": 94.53
    },
    {
      "id": "q29",
      "max_ms": 73.63,
      "mean_ms": 68.87,
      "p50_ms": 68.04,
      "p95_ms": 73.26
    },
    {
      "id": "q30",
      "max_ms": 127.68,
      "mean_ms": 106.9,
      "p50_ms": 106.23,
      "p95_ms": 123.66
    },
    {
      "id": "q31",
      "max_ms": 183.9,
      "mean_ms": 130.18,
      "p50_ms": 130.4,
      "p95_ms": 163.89
    },
    {
      "id": "q32",
      "max_ms": 118.7,
      "mean_ms": 104.45,
      "p50_ms": 107.29,
      "p95_ms": 116.62
    },
    {
      "id": "q33",
      "max_ms": 131.52,
      "mean_ms": 93.19,
      "p50_ms": 85.0,
      "p95_ms": 129.68
    },
    {
      "id": "q34",
      "max_ms": 97.12,
      "mean_ms": 83.84,
      "p50_ms": 80.51,
      "p95_ms": 96.57
    },
    {
      "id": "q35",
      "max_ms": 147.95,
      "mean_ms": 100.26,
      "p50_ms": 88.42,
      "p95_ms": 136.4
    },
    {
      "id": "q36",
      "max_ms": 157.39,
      "mean_ms": 120.31,
      "p50_ms": 123.04,
      "p95_ms": 153.26
    },
    {
      "id": "q37",
      "max_ms": 90.82,
      "mean_ms": 82.99,
      "p50_ms": 84.98,
      "p95_ms": 90.09
    },
    {
      "id": "q38",
      "max_ms": 105.41,
      "mean_ms": 73.38,
      "p50_ms": 68.13,
      "p95_ms": 96.61
    },
    {
      "id": "q39",
      "max_ms": 95.84,
      "mean_ms": 74.22,
      "p50_ms": 71.88,
      "p95_ms": 88.91
    },
    {
      "id": "q40",
      "max_ms": 109.02,
      "mean_ms": 92.72,
      "p50_ms": 93.09,
      "p95_ms": 107.44
    },
    {
      "id": "q41",
      "max_ms": 106.62,
      "mean_ms": 87.86,
      "p50_ms": 84.35,
      "p95_ms": 102.81
    },
    {
      "id": "q42",
      "max_ms": 117.49,
      "mean_ms": 103.68,
      "p50_ms": 101.56,
      "p95_ms": 115.86
    },
    {
      "id": "q43",
      "max_ms": 125.85,
      "mean_ms": 105.9,
      "p50_ms": 101.78,
      "p95_ms": 119.64
    },
    {
      "id": "q44",
      "max_ms": 103.76,
      "mean_ms": 94.82,
      "p50_ms": 92.61,
      "p95_ms": 103.53
    },
    {
      "id": "q45",
      "max_ms": 123.34,
      "mean_ms": 111.03,
      "p50_ms": 112.02,
      "p95_ms": 122.86
    }
  ],
  "queries": [
    "q01",
    "q02",
    "q03",
    "q04",
    "q05",
    "q06",
    "q07",
    "q08",
    "q09",
    "q10",
    "q11",
    "q12",
    "q13",
    "q14",
    "q15",
    "q16",
    "q17",
    "q18",
    "q19",
    "q20",
    "q21",
    "q22",
    "q23",
    "q24",
    "q25",
    "q26",
    "q27",
    "q28",
    "q29",
    "q30",
    "q31",
    "q32",
    "q33",
    "q34",
    "q35",
    "q36",
    "q37",
    "q38",
    "q39",
    "q40",
    "q41",
    "q42",
    "q43",
    "q44",
    "q45"
  ],
  "threshold_p95_ms": 250.0,
  "verdict": "acceptable"
}
```
<!-- CONTEXT_LATENCY_METRICS_END -->
