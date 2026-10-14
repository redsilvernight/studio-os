# P02-gate — validation de Mission Control

Rapport du 11 octobre 2026. Tâche `7cfd9c38-9669-447d-8820-fb1eef5f987f`,
roadmap `c289fb39-6486-4d6a-b395-527391124b19`, étape `P02-gate`.
Code testé : `95b2907a797234e6c0c99f0a59365e71862c1275`, intégration de la PR #140
sur `dev`. Environnement : Windows 11, Python 3.14.7, PostgreSQL 16.15,
Alembic `0031`, MinIO local.

**Verdict : gate non acceptée.** Les vérifications automatisées sont vertes et
les mesures ont été reproduites. Le parcours réel, bloqué en production, a été
démontré le 14 octobre sur une pile locale (section dédiée) ; la revue humaine
reste attendue. Aucun critère de gate n'est coché.

## Parcours réellement observé

Le navigateur connecté par l'utilisateur sur `https://studio.flosrent.fr` montre
l'accueil, la tâche prise par Codex sur Flo-desktop, sa session active, puis le
projet Studio OS. La session est visible dans « Sessions, journaux et
automatisations » ; le bloc indique « Aucun lancement ».

Deux obstacles empêchent la suite du parcours :

- Le projet déployé ne propose pas l'onglet « Exécutions », y compris après
  ouverture de « Plus » (Membres et Intégration IA). La lecture authentifiée de
  `GET /api/v1/projects/2a836038-153c-41cf-879a-73bd794760b0/mission` répond
  `404 {"detail":"Not Found"}`. Le SHA du serveur déployé reste inconnu ; le
  commit testé localement n'est pas présenté comme la version déployée.
- Le sélecteur « Poste cible » désactive Flo-desktop avec le motif « online ·
  lancements non acceptés sur le poste ». Les autres postes proposés sont hors
  ligne. Les boutons d'aperçu et de lancement restent désactivés.

Aucun TaskLaunch de production n'a été créé. La session de ce rapport a été
ouverte manuellement avec `start_work` : elle ne constitue pas une preuve du
parcours navigateur → TaskLaunch → machine → worktree → harness → start_work →
sync → handoff → AIWork. Les cas réels exit0 sans protocole et annulation restent
également à observer. La connexion au navigateur n'est pas une acceptation de gate.

## Vérifications exécutées

Préparation : `pwsh -NoProfile -File scripts/test-env.ps1 -TimeoutSeconds 25`,
puis `uv sync --all-packages` dans le worktree. Le premier essai dans le sandbox
avait expiré sur Docker ; l'ancien checkout principal ne connaissait pas la
migration `0031`. La préparation dans le worktree du dernier `dev` a réussi.
La première collecte pytest a révélé le package client absent ; la synchronisation
de tous les packages a corrigé l'environnement avant les résultats ci-dessous.

- `npm ci --offline --no-audit --no-fund`, puis `npm run build` : réussite.
- `uv run --all-packages pytest -q tests/client/test_launch_e2e_acceptance.py
  tests/api/test_mission.py tests/api/test_task_launch_recovery.py
  tests/scripts/test_mission_metrics.py` : **52 passed**, 11,16 s.
- `STUDIO_DASHBOARD_PREVIEW_PORT=4176 npm run test:e2e --
  e2e/p02-mission.spec.ts e2e/task-launch.spec.ts e2e/a2-session-end.spec.ts
  e2e/p01-metrics.spec.ts --reporter=list` : **25 passed**, 11,8 s.
  Le port 4173 était occupé ; aucun processus existant n'a été arrêté.
- Mesure UI séparée avec `P01_METRICS_WRITE=1`,
  `e2e/p01-metrics.spec.ts --workers=1` : **11 passed**, 7,8 s.
  Ces onze tests recouvrent ceux du run précédent. La baseline versionnée a été
  restaurée octet pour octet ; la nouvelle mesure est conservée séparément.
- Après préparation de la base, **une seule suite complète** :
  `uv run --all-packages pytest -n 6 -q
  --junitxml=output/p02-gate/pytest-full.xml` : **3843 passed, 9 skipped,
  82 warnings**, 273,78 s ; code de sortie 0. Le JUnit archive les motifs de skip.

Les E2E du dashboard utilisent des réponses API stubbées. L'acceptance Python
utilise les services et PostgreSQL/MinIO locaux, un transport ASGI et des harness
contrôlés. Elle couvre le rejeu après coupure réseau, exit0 sans consigne,
refus local, annulation, rattachement de session et preuve de handoff. Ces résultats
ne remplacent pas une exécution avec un vrai harness depuis le navigateur.

La CI du **commit de base** a été lue :
[CI](https://github.com/redsilvernight/studio-os/actions/runs/38170383982),
[Desktop validation](https://github.com/redsilvernight/studio-os/actions/runs/38170383989)
et [Desktop channels](https://github.com/redsilvernight/studio-os/actions/runs/38170383976)
sont `completed / success`. Cela ne certifie ni un nouveau commit de rapport,
ni un déploiement du serveur.

## Mesures avant/après P01

Sources : [metrics.md](metrics.md), baseline backend publiée dans
`4ee2bc68e540d5c1be5c9e24dee9cd68716fa636` (code mesuré `56778a17`),
et `dashboard/e2e/p01-metrics.json` pour l'UI P01. Mesure actuelle au commit
`95b2907a`, le 11 octobre à 20:27:47 UTC, avec le scénario seedé canonique
`20261009`, deux passes d'échauffement et dix échantillons par appel.
Le script `scripts.mission_metrics._run_db_eval` crée puis nettoie ses propres
fixtures ; ses JSON ont été archivés sans réécrire les baselines.

- Contexte `start_work(task)` : **3020,75 → 2924,25** tokens approximatifs.
- Contexte `sync` : **209 → 112,5** tokens approximatifs.
- `start_work` sans tâche et `prepare_project_context` : **2405,25** et
  **2468**, inchangés. Lecture `project_mission` actuelle : **225,25**.
- Bruit présenté par `sync`, comparaison P02-noise documentée dans `metrics.md` :
  **2 → 1 item par AIWork**. Mesure actuelle : 15 items pour 15 identifiants,
  sur dix tâches. Les événements bruts restent **92**, dont 60 événements
  AIWork pour 30 entrées ; aucun événement n'est supprimé par le regroupement.
- Dix `sync` sans acquittement : **40 → 20** items, **36 → 18** répétitions.
  Il s'agit du rejeu attendu sans `ack`, pas de créations dupliquées.
- JS initial, fermeture d'imports statiques : **76490 → 43137 octets gzip**
  (74,7 → 42,13 Kio), sous la cible de 61440 octets.
- Éléments majeurs UI : accueil 6, travail 5, à valider 3, projet **6 → 7**,
  roadmap 4, fiche tâche **5 → 6** ; tous restent dans le budget de 7.
- Identifiants techniques visibles : **0** ; indicateur de connexion : **1**
  sur chacun des six écrans mesurés.
- Clics S1/S2/S3/S4 : **1/1/0/2**, inchangés. S3 commence sur « À valider »
  avec la prochaine action déjà visible ; zéro ne mesure pas un parcours complet.

Les tokens sont des tailles de réponse estimées par caractères/4. Les mesures
backend sont prises en processus et hors réseau. Les fixtures UI sont contrôlées.
Aucune économie de tokens facturés, aucun coût provider et aucune couverture d'un
collecteur réel ne sont déduits de ces chiffres. Les latences ne sont pas comparées
comme un gain de performance entre deux exécutions locales.

## Démonstration réelle sur pile locale (14 octobre 2026)

Cadre : DEC-0212 (proposée) accepte une pile locale pour la démonstration réelle ;
la revue humaine reste requise. Code : `dev` à `f3a12b3`. Pile Docker jetable
`studio-gate-demo` (API, MCP, dashboard, Caddy, PostgreSQL, MinIO) sur
`127.0.0.1:8865`, projet jetable « Gate demo », poste « Demo-desktop » avec un
daemon isolé (`APPDATA` et `XDG_CONFIG_HOME` dédiés) et le vrai harness
OpenCode 1.18.32 (modèle big-pickle). Chaque lancement est demandé dans le
dashboard ; aucune écriture n'a été faite directement en base.

| Parcours | Observé dans le dashboard |
|---|---|
| Handoff | Demandé → Accepté → En cours ; worktree `task/*` ; session, commit, AIWork ; « Processus terminé (code 0) · Handoff reçu · tâche : à relire » ; tâche Terminé |
| exit0, consigne « sans protocole » | Consigne ignorée par l'agent : session et handoff faits ; « Résultat transmis » |
| exit0, MCP coupé (`docker compose stop mcp`) | Commit fait, 0 session, 0 AIWork ; « Processus terminé (code 0) · Protocole non vérifié » ; tâche restée À faire |
| Annulation | Confirmation explicite, processus arrêté 8 s après, 8 commits conservés ; « Annulé · annulé par le demandeur » |

Mission Control (onglet Exécutions) : « 4 exécution(s) sur 168 h », À vérifier 1
(« Processus terminé sans session »), Terminée 2 (« Résultat transmis »),
Annulée 1. Le succès du processus est donc distinct de la preuve de protocole.
Provenance du handoff : capture partielle (lancement sans agent), harness,
mode `workspace_write`, commit et worktree propre ; « Combien » : 1 mesure,
2 min 43 s, coût et jetons inconnus. Les jetons dans la sortie capturée
apparaissent masqués `<token>`.

Défauts constatés, non corrigés ici :

- Après annulation, la session reste « toujours active » et la tâche « En
  cours » alors que le processus est arrêté ; Mission Control ne la signale pas.
- « Actualiser l'état » laisse « Protocole non vérifié » et Sessions (0) après
  la fin ; seul le rechargement de la vue montre le handoff.
- L'agent a lu hors de son worktree (configuration de démo, puis
  `~/.config/opencode` réel) ; aucun jeton visible dans l'extrait capturé.
- Le lancement annulé ne produit aucune mesure d'usage.
- Un dossier `%SystemDrive%/` apparaît dans chaque worktree (effet probable de
  l'override `APPDATA` propre à la démo).

Preuves (textes, captures, SHA) dans `output/gate-demo-local/`, ignoré par Git.

## État des critères et reprise

1. Démonstration réelle, mesures et tests archivés : les trois parcours sont
   observés sur pile locale réelle (DEC-0212) ; critère non coché tant que
   DEC-0212 et la revue ne sont pas acceptées.
2. Sessions actives/bloquées visibles et succès distinct de la preuve : observé
   dans Mission Control local, sauf la session orpheline après annulation ;
   non coché.
3. Lisibilité acceptée par un humain : revue du parcours réel attendue ;
   non coché. DEC-0201 reste la référence pour distinguer processus et protocole.

Reprise : faire relire la lisibilité sur ces preuves, accepter ou remplacer
DEC-0212, traiter la session orpheline après annulation, puis mettre à jour ce
rapport. Le retour arrière prévu par l'étape est le parcours tâche V2.

Artefacts locaux conservés dans `output/p02-gate/` du worktree
`mission-control-gate` : build, logs et JUnit, JSON backend/UI avant et après.
Les captures `project-deployed.jpg`, `launch-deployed.jpg` et le DOM du sélecteur
sont sous `output/p02-gate/` du checkout principal. Ces fichiers sont ignorés par
Git ; le présent rapport conserve les résultats nécessaires à la revue.
