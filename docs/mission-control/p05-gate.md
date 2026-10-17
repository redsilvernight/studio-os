# P05-gate — pilote à deux machines et arrêt aux gates

Tâche `8a0f715c-efa7-4935-a681-b4b69c599967`. **Gate non acceptée ; aucun
critère coché.**

## Critères

1. Parallélisme borné réel, dépendante jamais lancée avant handoff/gate valide.
2. Perte de machine et refus local visibles, sans lancement doublon ni
   dépassement d'admission.
3. Preuve réelle et limites consignées ; disponibilité de deux machines
   confirmée.

## Preuve automatisée

API exercée via ASGI avec PostgreSQL réel ; machines et harness simulés.

| Test | Critère | Ce qu'il prouve |
|---|---|---|
| `tests/api/test_p05_pilot_gate.py` | 1 | Batch sur deux machines borné par les slots (3e item `budget_slots_exhausted`) ; B `dependency_pending` puis `not_launchable` tant que A n'a pas de handoff `completed` ; admise une seule fois ensuite ; même `Idempotency-Key` rejouée sans doublon |
| `tests/client/test_p05_machine_loss.py` | 2 | Heartbeats perdus : `offline_wip` puis `stale` ; rejeu de clé = original, nouvelle admission `409 machine_offline`, retry `409 launch_not_terminal` ; seule l'annulation libère le slot ; jamais plus d'un actif. Refus local : `rejected`/`not_opted_in`, ni re-pull ni relance |

Déjà couverts : `tests/api/test_admission_batch_concurrency.py` (courses entre
batchs, slots, rejeu), `tests/client/test_launch_e2e_acceptance.py` (coupure
réseau, refus local, annulation), `tests/client/test_two_machines_acceptance.py`
(convergence sans état local partagé).

## Démonstration réelle deux machines

Non réalisée. Cadre : DEC-0212 (pile locale jetable). Machines : `Flo`
(poste fixe, héberge la pile) et `Flo-laptop`, reliées par Tailscale.

Pile `studio-gate-demo` sur `Flo`, Caddy publié sur `127.0.0.1:8865` et sur
l'IP Tailscale de `Flo` uniquement ; volumes nommés, sans `docker/.data`.
Chaque machine fait tourner un daemon isolé (`APPDATA` et `XDG_CONFIG_HOME`
dédiés, sans jeton `STUDIO_MCP_*` hérité) ; sur `Flo-laptop`, la pile de prod
n'est pas touchée.

Projet jetable, roadmap : S1 (tâche A), S2 (tâche B, `depends_on` S1), tâche
indépendante C ; un slot par machine.

| Scénario | Attendu |
|---|---|
| Admission batch A + C | A et C lancés en parallèle, un par machine ; B exclu (dépendance) |
| Handoff A, S1 `done` | B devient admissible et n'est admis qu'une fois |
| Coupure du daemon `Flo-laptop` en cours de lancement | Lancement signalé hors ligne ; réadmission sans doublon ni dépassement de slot |
| Politique locale de `Flo-laptop` sans harness autorisé | Lancement `rejected` visible, sans relance automatique |

## Non démontré

- Démonstration physique deux machines (critère 3).
- Revue humaine.
