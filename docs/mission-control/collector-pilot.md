# Mission Control — collecteur pilote Claude Code (P03-collector)

Décision : DEC-0197. Code : `packages/studio-client/src/studio_client/usage/collectors/`
(registre par harness), `usage/recorder.py` (entrée de ledger mise en outbox), branchement
dans `daemon/launch_executor.py` ; le runner (`daemon/launch_runner.py`) ne fait que
mesurer la période et la durée du processus.

## Collecteurs certifiés

| Harness | Collecteur | Version | Source | Tokens | Coût | Durée |
|---|---|---|---|---|---|---|
| `claude-code` 2.1.x | `studio-claude-code` | 1.0.0 | document final `type=result` de `claude -p --output-format json` (ou dernière ligne `stream-json`) | `usage` : entrée, sortie, cache création + lecture (portée `additional_to_input`) | `total_cost_usd`, mesuré, USD | runner, mesurée |
| `codex`, `opencode`, tout autre | `studio-runner` (mode dégradé) | 1.0.0 | aucune | inconnu | inconnu | runner, mesurée |

Le mode headless de Claude Code passe de `--output-format text` à `json` ; l'extrait de
lancement reste lisible : c'est le champ `result` du document qui est redacté et envoyé.

## Modes dégradés (raisons stables)

Le run n'échoue jamais à cause du collecteur : toute exception du collecteur ou de la
mise en file est absorbée (`collector_failed`, ou journal sans entrée).

| Situation | Raison | Effet |
|---|---|---|
| Harness non certifié | `uncertified_harness` | tokens et coût inconnus, durée mesurée |
| Sortie vide / texte sans JSON | `output_empty` / `no_result_document` | idem |
| JSON tronqué par la borne de 64 Kio | `output_truncated` | idem |
| JSON illisible | `corrupted_output` | idem |
| JSON sans document `result` ou clés de compteurs absentes | `unsupported_schema` | compteurs concernés inconnus |
| `usage` ou `total_cost_usd` absent (format futur) | `usage_missing`, `cost_missing` | tokens / coût inconnus, jamais 0 |
| Compteur négatif, non entier, coût non numérique | `invalid_counter` | compteur inconnu |
| `is_error: true` | `harness_error_result` | compteurs lus tels quels (0 mesuré si aucun appel API) |
| Plusieurs modèles | `multiple_models` | modèle = le plus coûteux |
| Timeout / annulation | `run_interrupted` | durée mesurée, reste selon la sortie |

## Runs réels (Claude Code 2.1.287)

Trois runs `claude -p "réponds OK" --output-format json --max-turns 1` dans un dossier
temporaire vide, le 2026-10-13. Durée murale chronométrée autour du processus, comme le
fait le runner ; sorties passées telles quelles au collecteur.

| Run | Source : in / out / cache créa. / cache lect. | Mesure : in / out / cached / total | Source : coût USD | Mesure : coût | Source : `duration_ms` | Mesure : durée (s) | Diagnostics |
|---|---|---|---|---|---|---|---|
| 1 | 2 / 4 / 32 926 / 0 | 2 / 4 / 32 926 / 32 932 | 0,263496 | 0,263496 USD, mesuré | 4 058 | 10,383 | aucun |
| 2 | 2 / 4 / 11 973 / 23 184 | 2 / 4 / 35 157 / 35 163 | 0,1005088 | 0,1005088 USD, mesuré | 3 570 | 8,218 | aucun |
| 3 | 2 / 4 / 12 570 / 23 184 | 2 / 4 / 35 754 / 35 760 | 0,1052848 | 0,1052848 USD, mesuré | 7 550 | 12,301 | aucun |

Modèle et fournisseur relevés : `claude-opus-5-5`, `anthropic` (`provider: firstParty`).
Couverture des cinq mesures : `measured`.

### Écarts expliqués

- **Tokens : aucun écart.** `tokens_cached` = création + lecture de cache ; ces comptes
  sont disjoints de `input_tokens`, d'où la portée `additional_to_input` et un total
  in + out + cached. Le cache domine (contexte système et configuration utilisateur),
  le prompt lui-même ne pèse que 2 tokens.
- **Coût : aucun écart** avec `total_cost_usd`. C'est le coût que Claude Code calcule
  au tarif public (`costBasis: list`) : mesuré au sens « lu dans le runtime », pas
  forcément facturé (abonnement). Le run 1 coûte plus cher car il écrit tout le cache.
- **Durée : écart attendu de 4,6 à 6,3 s.** La mesure est la durée murale du processus
  (démarrage du CLI, chargement de configuration et des serveurs MCP, arrêt) ; le
  `duration_ms` de Claude Code ne couvre que la session interne. Le ledger garde la
  durée murale, cohérente avec la période `period_start`–`period_end`.
- Une erreur réelle (`--model` inexistant, sans appel facturé) a été capturée en
  fixture : stderr fusionné avant le JSON, compteurs à 0 mesurés, `harness_error_result`.

## Points ouverts

- `harness_version` reste vide : la sortie JSON ne porte pas la version du CLI.
- Les diagnostics ne sont pas persistés côté serveur (le contrat n'a pas de champ) :
  seule la couverture par mesure voyage ; les raisons sont journalisées localement.
- Un run annulé par le demandeur (tâche asyncio annulée) ne produit pas d'entrée.
- Codex et OpenCode restent en mode dégradé jusqu'à certification de leurs sources.
