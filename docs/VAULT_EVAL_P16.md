# Évaluation finale de la roadmap vault — P16 (avant / après)

- P00 : `docs/DEC_RELEVANCE_BASELINE_P00.md` (baseline figée, bloc machine relu)
- P04 : `docs/VAULT_SEARCH_EVAL_P04.md` (recherche vault, bloc machine relu)
- P07 : `docs/DEC_RELEVANCE_P07.md` (sélection des décisions, bloc machine relu)
- P16 : sélection actuelle rejouée par `scripts.dec_relevance_eval` sur `tests/eval/dec_queries.json` et `tests/eval/dec_corpus.json`
- Latence : `docs/CONTEXT_LATENCY_P16.md` (`studio.eval.context-latency/v1`)
- Tokens : approximation `ceil(caractères / 4)` sur les corps retournés

## Commande

```
uv run python -m scripts.vault_eval_p16 --root . --check   # exit 1 si périmé
uv run python -m scripts.vault_eval_p16 --root . --apply   # (ré)écrit ce rapport
```

## Agrégat P00 / P04 / P07 / P16

| Métrique | P00 | P04 | P07 | P16 |
|---|---|---|---|---|
| Requêtes | 45 | 45 | 45 | 45 |
| Réponses `decisions: []` | 0.0 % | 0.0 % | 0.0 % | 0.0 % |
| Rappel micro | 75.0 % | 76.3 % | 72.4 % | 72.4 % |
| Rappel macro | 79.6 % | 79.6 % | 77.4 % | 77.4 % |
| Précision micro | 25.7 % | 25.8 % | 38.7 % | 38.7 % |
| Vrais positifs | 57 | 58 | 55 | 55 |
| Éléments retournés | 222 | 225 | 142 | 142 |
| Tokens injectés (total) | 33927 | 16474 | 20376 | 20376 |
| Tokens par appel (moyenne) | 753.93 | 366.09 | 452.80 | 452.80 |

P04 mesure la recherche vault (`studio_vault_search`), P00, P07 et P16 la sélection
des décisions de `studio_prepare_context` ; « — » signale une métrique absente.

## Critères de P16

| # | Critère | Verdict |
|---|---|---|
| 1 | mêmes requêtes que P00 (égalité des ids) | atteint |
| 2 | taux de decisions: [] et rappel meilleurs que P00, ou écart expliqué | atteint, écart expliqué |
| 3 | latence de prepare_context mesurée et acceptable | atteint |

1. Les 45 ids de requête de `tests/eval/dec_queries.json` sont comparés, dans l'ordre, à ceux des blocs
   P00, P04, P07 et du rejeu P16.
2. Réponses vides : 0.0 % en P00, 0.0 % en P16 ; rappel micro 75.0 % → 72.4 %, précision micro 25.7 % → 38.7 %. Un rappel inférieur n'est
   accepté que si les vrais positifs perdus et gagnés ci-dessous expliquent tout
   l'écart et que la précision micro progresse.
3. Voir la section latence.

## Écart de rappel expliqué

Vrais positifs : 57 en P00, 55 en P16 (perdus : 3, gagnés : 1).

| id | objectif | perdus vs P00 | gagnés vs P00 |
|---|---|---|---|
| q03 | Ajouter un worker d'expiration des transferts et son job CLI | DEC-0019 | — |
| q08 | Ajouter une file de review pour les propositions de roadmap | — | DEC-0049 |
| q23 | Robustifier le bootstrap permanent et ses cibles d'actions manuelles | DEC-0181 | — |
| q28 | Rendre l'autorisation transverse minimale par rôle et propriété | DEC-0063 | — |

### Plafond lexical (données P07)

| id | attendues sans terme commun avec l'objectif |
|---|---|
| q07 | DEC-0018 |
| q24 | DEC-0173, DEC-0177 |
| q29 | DEC-0055 |

4 décisions attendues sur 76 ne partagent aucun terme avec leur objectif : aucune règle lexicale ne peut les
atteindre, le rappel micro maximal est donc 94.7 %.

## Latence de `prepare_context`

| p50 | p95 | max | seuil p95 | verdict |
|---|---|---|---|---|
| 90.99 ms | 122.27 ms | 183.9 ms | 250.0 ms | acceptable |

## Métriques machine (vérifiées par `--check`)

<!-- VAULT_EVAL_P16_METRICS_BEGIN -->
```json
{
  "criteria": [
    {
      "evidence": {
        "count": 45,
        "equal": true
      },
      "id": 1,
      "label": "mêmes requêtes que P00 (égalité des ids)",
      "verdict": "met"
    },
    {
      "evidence": {
        "empty_rate_not_worse": true,
        "gap_accounted_by_listed_true_positives": true,
        "micro_precision_improved": true,
        "recall_not_worse": false
      },
      "id": 2,
      "label": "taux de decisions: [] et rappel meilleurs que P00, ou écart expliqué",
      "verdict": "met_with_explained_gap"
    },
    {
      "evidence": {
        "latency_verdict": "acceptable",
        "measured": true
      },
      "id": 3,
      "label": "latence de prepare_context mesurée et acceptable",
      "verdict": "met"
    }
  ],
  "format": "studio.eval.vault-p16/v1",
  "latency": {
    "max_ms": 183.9,
    "p50_ms": 90.99,
    "p95_ms": 122.27,
    "source": "docs/CONTEXT_LATENCY_P16.md",
    "threshold_p95_ms": 250.0,
    "verdict": "acceptable"
  },
  "lexical_ceiling": {
    "attainable_recall": 0.9474,
    "expected_total": 76,
    "per_query": [
      {
        "id": "q07",
        "unreachable": [
          "DEC-0018"
        ]
      },
      {
        "id": "q24",
        "unreachable": [
          "DEC-0173",
          "DEC-0177"
        ]
      },
      {
        "id": "q29",
        "unreachable": [
          "DEC-0055"
        ]
      }
    ],
    "source": "docs/DEC_RELEVANCE_P07.md",
    "unreachable_total": 4
  },
  "phases": {
    "P00": {
      "empty_rate": 0.0,
      "expected_total": 76,
      "macro_recall": 0.7963,
      "micro_precision": 0.2568,
      "micro_recall": 0.75,
      "queries": 45,
      "retrieved_total": 222,
      "tokens_per_call_mean": 753.93,
      "tokens_total": 33927,
      "true_positives": 57
    },
    "P04": {
      "empty_rate": 0.0,
      "expected_total": 76,
      "macro_recall": 0.7963,
      "micro_precision": 0.2578,
      "micro_recall": 0.7632,
      "queries": 45,
      "retrieved_total": 225,
      "tokens_per_call_mean": 366.09,
      "tokens_total": 16474,
      "true_positives": 58
    },
    "P07": {
      "empty_rate": 0.0,
      "expected_total": 76,
      "macro_recall": 0.7741,
      "micro_precision": 0.3873,
      "micro_recall": 0.7237,
      "queries": 45,
      "retrieved_total": 142,
      "tokens_per_call_mean": 452.8,
      "tokens_total": 20376,
      "true_positives": 55
    },
    "P16": {
      "empty_rate": 0.0,
      "expected_total": 76,
      "macro_recall": 0.7741,
      "micro_precision": 0.3873,
      "micro_recall": 0.7237,
      "queries": 45,
      "retrieved_total": 142,
      "tokens_per_call_mean": 452.8,
      "tokens_total": 20376,
      "true_positives": 55
    }
  },
  "query_ids": {
    "count": 45,
    "ids": [
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
    ]
  },
  "recall_gap_vs_p00": {
    "gained_total": 1,
    "lost_total": 3,
    "per_query": [
      {
        "gained": [],
        "id": "q03",
        "lost": [
          "DEC-0019"
        ],
        "objective": "Ajouter un worker d'expiration des transferts et son job CLI"
      },
      {
        "gained": [
          "DEC-0049"
        ],
        "id": "q08",
        "lost": [],
        "objective": "Ajouter une file de review pour les propositions de roadmap"
      },
      {
        "gained": [],
        "id": "q23",
        "lost": [
          "DEC-0181"
        ],
        "objective": "Robustifier le bootstrap permanent et ses cibles d'actions manuelles"
      },
      {
        "gained": [],
        "id": "q28",
        "lost": [
          "DEC-0063"
        ],
        "objective": "Rendre l'autorisation transverse minimale par rôle et propriété"
      }
    ],
    "true_positives_p00": 57,
    "true_positives_p16": 55
  },
  "sources": {
    "P00": "docs/DEC_RELEVANCE_BASELINE_P00.md",
    "P04": "docs/VAULT_SEARCH_EVAL_P04.md",
    "P07": "docs/DEC_RELEVANCE_P07.md",
    "P16": "replay of docs/DEC_RELEVANCE_P07.md selection",
    "corpus": "tests/eval/dec_corpus.json",
    "queries": "tests/eval/dec_queries.json"
  }
}
```
<!-- VAULT_EVAL_P16_METRICS_END -->
