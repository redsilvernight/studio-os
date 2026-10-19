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
| `tests/api/test_p05_pilot_gate.py` | 1 | Batch de deux admissions sur deux machines, puis troisième admission refusée dans une requête distincte (`budget_slots_exhausted`) ; B `dependency_pending` puis `not_launchable` tant que A n'a pas de handoff `completed` ; admise une seule fois ensuite ; même `Idempotency-Key` rejouée sans doublon |
| `tests/client/test_p05_machine_loss.py` | 2 | Heartbeats perdus : `offline_wip` puis `stale` ; rejeu de clé = original, nouvelle admission `409 machine_offline`, retry `409 launch_not_terminal` ; seule l'annulation libère le slot ; jamais plus d'un actif. Refus local : `rejected`/`not_opted_in`, ni re-pull ni relance |

Déjà couverts : `tests/api/test_admission_batch_concurrency.py` (courses entre
batchs, slots, rejeu), `tests/client/test_launch_e2e_acceptance.py` (coupure
réseau, refus local, annulation), `tests/client/test_two_machines_acceptance.py`
(convergence sans état local partagé).

Le test de dépendance crée directement une session pour A et son handoff ; il
vérifie la projection du statut `completed` vers l'étape S1, sans lancer de
harness pour A. Il ne prouve donc pas la fin de cette exécution ni la libération
de son slot. Les courses entre admissions sont couvertes séparément par
`test_admission_batch_concurrency.py`, pas par le scénario séquentiel ci-dessus.
La perte de heartbeat est simulée en vieillissant son horodatage en base ; aucun
processus harness ni lien réseau réel n'est interrompu par ces tests.

## Validation de la PR

CI [39018857889](https://github.com/redsilvernight/studio-os/actions/runs/39018857889),
terminée le 17 octobre 2026 sur le commit
`95e5bcc5596da67179d345abb4f9fa06dc588b29` de la
[PR #161](https://github.com/redsilvernight/studio-os/pull/161) :

- `lint`, `typecheck`, `test` et `dashboard` : succès.
- Backend : **4 103 passed, 34 skipped**, 82 avertissements, 91,72 s.
- Dashboard : **1 567 tests unitaires passed** ; Playwright :
  **298 passed, 1 skipped**.

Validation locale ciblée le même jour, au même commit : après
`pwsh scripts/test-env.ps1 -TimeoutSeconds 30` et la sonde d'infrastructure
(codes de retour 0),
`uv run --all-packages pytest tests/api/test_p05_pilot_gate.py tests/client/test_p05_machine_loss.py -q`
termine avec **5 passed en 18,17 s**, sans exclusion, code 0. PostgreSQL et
MinIO sont disponibles ; aucun transfert MinIO n'est exercé par ces cinq tests.

La revue indépendante du 17 octobre ne relève aucun défaut actionnable dans
les assertions API. Ces résultats automatisés ne valident pas la démonstration
physique ni l'acceptation humaine de la gate.

## Démonstration réelle deux machines

Réalisée le 19 octobre 2026 (heures locales). Cadre : DEC-0212 (pile locale jetable). Machines : `Flo`
(poste fixe, héberge la pile) et `Flo-laptop`, reliées par Tailscale.

Pile `studio-gate-demo` sur `Flo`, Caddy publié sur `127.0.0.1:8865` et sur
l'IP Tailscale de `Flo` uniquement ; volumes nommés, sans `docker/.data`.
Chaque machine fait tourner un daemon isolé (`APPDATA` et `XDG_CONFIG_HOME`
dédiés, sans jeton `STUDIO_MCP_*` hérité). La production est hébergée sur le
VPS OVH depuis DEC-0205 ; la démonstration utilise uniquement la pile jetable.

Projet jetable, roadmap : S1 (tâche A), S2 (tâche B, `depends_on` S1), tâche
indépendante C ; un slot par machine.

| Scénario | Attendu |
|---|---|
| Admission batch A + C | A et C lancés en parallèle, un par machine ; B exclu (dépendance) |
| Handoff A, S1 `done` | B devient admissible et n'est admis qu'une fois |
| Coupure du daemon `Flo-laptop` en cours de lancement | Lancement signalé hors ligne ; réadmission sans doublon ni dépassement de slot |
| Politique locale de `Flo-laptop` sans harness autorisé | Lancement `rejected` visible, sans relance automatique |

Résultats relevés dans `task_launches` et `machines` de la pile démo, et via le
dashboard :

| Scénario | Observé |
|---|---|
| Admission batch A + C | Batch 08:46:03 : `f2e18bc6` A sur `Demo-Flo`, `0c472ec3` C sur `Demo-Flo-laptop`, `running` en parallèle puis `succeeded` (08:47:36, 08:47:13) ; B exclue du dry-run (« En attente de S1 ») |
| Handoff A, S1 `done` | Plan à 33 % ; `4ecfe4e6` B sur `Demo-Flo` (08:49:56 → `succeeded` 08:52:05) ; le dry-run suivant exclut B (lancement actif, tâche réservée) |
| Coupure du daemon | `91794719` D `running` 09:15:41 ; daemon arrêté au plus tard 09:16:13, dernier heartbeat 09:16:03 ; à 09:17:32 le poste est « hors ligne, capacité atteinte », non éligible, un seul lancement actif. Relance du daemon 09:21:30 : `91794719` déclaré orphelin, `failed`/`harness_exited` (09:21:50), sans relance automatique ; réadmission `88371340` `running` 09:22:36 → `succeeded` 09:24:09 |
| Refus local (`allowed_harnesses: []`) | `f1b2a0a3` E : `requested` puis `rejected`/`harness_not_allowed` à 09:31:08 ; inchangé une minute plus tard, aucun nouveau lancement |

Constats et limites :

- Un batch antérieur (08:07:45) a admis deux lancements sur `Demo-Flo` à un
  slot ; le refus local `a9792ab3` (`capacity_reached`) a préservé la borne.
  L'admission serveur ne l'a pas empêché : à analyser hors de cette gate.
- Pendant la coupure, le lancement reste `running` côté serveur jusqu'au retour
  du daemon ; seul le poste passe hors ligne (seuil 90 s).
- Pré-requis découverts : branche `dev` dans le dépôt pilote
  (`preparation_failed` sinon), entrée MCP `studio-os` dans `opencode.json`
  (`mcp_entry_missing`), clé API valide du CLI opencode (`harness_exited`).
- Le refus local est atteint alors que le poste annonce opencode non configuré :
  le serveur laisse ce harness sélectionnable.
- Dashboard : le sélecteur de harness du batch se vide après un dry-run ; la
  session expire en cours de démonstration.

## Suites des constats

- Double admission sur un slot : corrigée par `aed07f4e` (les lancements admis
  non encore rapportés sont déduits de `free_slots`).
- Harness non configuré : corrigé par `e3d162ee` ; l'éligibilité n'accepte que
  les harness annoncés `detected` et `configured` (raison
  `harness_incompatible` sinon), test `test_machine_eligibility.py`.
- Sélecteur de harness du batch : corrigé (`349913e8`) ; le harness choisi
  reste proposé et sélectionné après un nouveau dry-run, et seuls les harness
  `configured` sont listés (`admissionPanel.test.ts`).
- Expiration de session : dans un navigateur, le JWT vit 15 min sans
  renouvellement ; le renouvellement persistant n'existe qu'avec le coffre du
  Desktop. Limite connue, non corrigée.

Ces correctifs ne sont pas redémontrés sur deux machines réelles.

## Non démontré

- Revue humaine.
- Redémonstration deux machines après les correctifs.
