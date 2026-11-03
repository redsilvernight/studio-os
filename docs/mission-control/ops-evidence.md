# P06 — Preuves d'exploitation

Collecte du 15 octobre 2026, tâche `bb335466-469f-4e92-a044-dcd077f54971`,
étape `P06-ops-evidence` de la roadmap `c289fb39-6486-4d6a-b395-527391124b19`.
Base finale vérifiée : `b8b9d9b6fd1cd1ee409f623f1b3986c5c8781470` (`dev`).
Les résultats structurés et empreintes sont conservés dans [ops-evidence.json](ops-evidence.json).

## Conclusion et rattachement aux tickets

La restauration isolée PostgreSQL/MinIO est reproduite avec les procédures existantes.
La charge légère, la coupure/reprise simulée et la révocation sont exécutées avec
les tests existants. Le préflight public passe ; la promotion publique complète
reste conditionnée aux réserves ci-dessous. Cette collecte ne clôt aucun autre ticket.

| Ticket existant | Preuve collectée | Limite / suite à conserver dans ce chantier |
|---|---|---|
| `8592d0fd-a1f6-48ae-bce7-f8b6407c1740` — charge, chaos, exploitation, restauration périodique | Restauration vierge ci-dessous ; charge 50/100 requêtes ; coupure/rejeu ; révocation API/MCP et refresh tokens | Campagne périodique et rétention hors site à prouver ; pas de benchmark VPS |
| `538ea67b-1cf7-4772-9a3b-89a1eb12fa10` — CSP | Domaine public accessible, header CSP Report-Only effectivement présent | Zéro violation sur les parcours réels puis enforcement toujours à établir ; le motif historique « attendre le VPS » doit être réévalué |
| `8fbf67fe-1575-49d0-b14e-2250391eb8a6` — chemins de déploiement | Préflight public et CI de `deploy/ovh-vps` observés | Le ticket décrit Flo-laptop ; cette collecte ne prouve pas l'unification de son poller ni l'état des ports sur l'hôte |

Références existantes : [checklist d'intégration](../Studio_OS_Documentation_Pack/studio_os_docs/IMPLEMENTATION/04_INTEGRATION_CHECKLIST.md),
[runbook OVH](../Studio_OS_Documentation_Pack/studio_os_docs/HUMAN/04_DEPLOIEMENT_OVH.md),
[gate public C4](../DESKTOP_C4_PRODUCTION_GATE.md), DEC-0021/0022 et DEC-0212.
Les validations locales admises par DEC-0212 pour P02/P03/P04 ne suffisent pas
à elles seules pour les gates P06.

## Restauration réellement exécutée

Exécution finale `ops-bb335466-7c9e6845`, du 15 octobre 2026 à 12:29:13–12:29:37
(Europe/Paris ; horodatages UTC dans le reçu), après migration de la base dédiée
à `0034`, vérifiée égale au head Alembic.

Le [script de collecte](../../scripts/ops-evidence.ps1) copie `backup.sh`,
`restore.sh` et `dotenv.sh` sans modification fonctionnelle (normalisation LF),
puis les exécute dans deux projets Compose distincts avec noms aléatoires.
La fixture utilise PostgreSQL 16 Alpine et la même image MinIO épinglée que
`docker/docker-compose.yml`, avec volumes neufs et sans publication de ports.
Seul le schéma de la base de test dédiée est lu ; aucune donnée de production
ni aucun credential réel n'est copié.

Contrôles effectifs :

- La source contient le schéma migré, la ligne Alembic `0034`, une ligne témoin
  `ops_evidence_marker` et un objet `ops-evidence/roundtrip.txt` synthétique.
- `docker/backup.sh` produit un dump custom et un miroir MinIO. La source est
  arrêtée avant le démarrage de la destination.
- La destination comporte initialement **0 table publique et 0 bucket**.
  `docker/restore.sh` restaure le dump et l'objet dans ces volumes vierges.
- Les comptages des **42 tables** sont identiques avant/après ; la ligne témoin,
  la révision Alembic et le contenu exact de l'objet sont comparés.
- Les deux projets sont arrêtés à la fin ; aucun volume ni répertoire n'est
  supprimé. Les sauvegardes restent dans le répertoire ignoré `output/`.

SHA-256 de l'objet restauré :
`163ac3c3bccbfb93ea4259218e063433fd8118502e28e0c2e85a25742dbd6643`.
L'empreinte du dump, du script de collecte et des trois procédures est dans le reçu.
Les données métier sont synthétiques ; cet exercice ne mesure ni RTO/RPO de
production, ni réplication hors site, ni récupération des secrets hors du VPS.

## Sauvegarde périodique de production (20 octobre 2026)

Tâche `8592d0fd`. Constat initial sur le VPS `vps-7cb819b7` : aucune crontab
(`ubuntu` ni `root`) ; seuls existaient les dumps `predeploy-*` de `docker/backups/`,
sans miroir MinIO.

- Racine dédiée `/home/ubuntu/studio-backups` (mode 700), hors du checkout.
- `install-backup-cron.sh /home/ubuntu/studio-backups 2 7` : tous les jours à 02:00,
  sept sauvegardes conservées, journal `backup.log` dans la racine.
- Sauvegardes manuelles `20261020T073617Z` et `20261020T073735Z` : dump PostgreSQL
  3,3 Mo et miroir MinIO de 5 objets (325 Mio).
- Défaut corrigé : le miroir MinIO était écrit en `root` par le conteneur, la rétention
  lancée par `ubuntu` aurait échoué au huitième jour. `backup.sh` rend désormais le miroir
  à l'utilisateur appelant ; vérifié sur le VPS (0 fichier non `ubuntu`).

Restauration de la sauvegarde réelle `20261020T073735Z`, copiée hors du VPS
(empreintes identiques des deux côtés : dump
`9071383912664a2e12fb47b90216a573063d4c92d216008d86cee1cb65acfc32`, 5 objets,
340 596 479 octets) puis restaurée sur un poste dans des conteneurs neufs
(PostgreSQL 16 Alpine, images MinIO épinglées), sans ports publiés :

- base initiale à 0 table publique ; `pg_restore --exit-on-error` rend 0 ;
- **41 tables** aux comptages identiques à la production relevée au même moment ;
  révision Alembic `0035` ;
- **5/5 objets** MinIO restaurés au SHA-256 identique à la sauvegarde.

Reste : la copie hors site automatique (destination à choisir) et la première exécution
du cron, à constater dans `backup.log` après 02:00.

## Charge, chaos et credentials

Exécution ciblée sur la base dédiée : **21 passed, 0 skipped**, base initiale
`dee24f62318d88133e1ba2f2c9c550eb994500d3`. La suite complète ci-dessous porte
ensuite sur `b8b9d9b6fd1cd1ee409f623f1b3986c5c8781470`.

| Commande / sélection existante | Ce qu'elle établit |
|---|---|
| `tests/api/test_load_basic.py` | 50 health checks concurrents réussissent ; 100 requêtes sans auth sont rejetées en 401/429 ; les métriques reflètent la charge |
| `tests/client/test_launch_e2e_acceptance.py::test_two_machine_launch_full_cycle_with_network_cut_and_idempotent_replay` | Coupure du transport injectée, outbox SQLite conservée, reprise ordonnée et rejeu idempotent après reconnexion |
| `tests/api/test_machines_self_service.py::test_a_user_revokes_its_own_machine` | Révocation d'une machine créée par le test, puis 401 avec son ancien credential |
| `tests/mcp/test_auth.py::test_authenticate_rejects_revoked_machine` | Le MCP refuse effectivement la machine révoquée |
| `tests/api/test_refresh_tokens.py` | Rotation, refus du rejeu, révocation de famille, expiration et logout |

L'API est exercée via ASGI avec PostgreSQL réel. La coupure réseau et les deux
machines de ce test sont simulées ; le harness est un substitut lançant un vrai
sous-processus. Ce résultat ne remplace ni le pilote à deux machines physiques,
ni une panne réseau du VPS, ni une charge soutenue. Les avertissements de clé JWT
courte proviennent des fixtures de test. Aucun secret JWT de production n'est
roté et aucun compte/machine réel n'est révoqué par cette collecte.

Suite complète `uv run --no-sync pytest -n 6 -q` : **4064 passed, 9 skipped,
0 failed**, 252,93 s. Les 9 exclusions concernent 5 cas de symlinks indisponibles,
la sonde OpenCode indisponible dans l'environnement de test et 3 mesures Graphify
opt-in (`STUDIO_CODE_GRAPH_PERF=1`). Détail dans le reçu structuré.

## Disponibilité et readiness VPS/publique

Sondes sans authentification du 15 octobre 2026 à 12:25 (Europe/Paris) :

| Sonde | Résultat observé |
|---|---|
| `https://studio.flosrent.fr/healthz` | 200 JSON, `status=ok`, HSTS présent |
| `https://studio.flosrent.fr/` | 200 HTML ; CSP Report-Only, sans CSP en enforcement |
| `https://storage.flosrent.fr/minio/health/live` | 200, HSTS présent |
| `https://studio.flosrent.fr/version` | 200 **HTML du dashboard** ; aucune version API déductible de cette réponse |

Le préflight `desktop/scripts/production-gate.mjs` a terminé avec `ok=true` à
12:27:25 (Europe/Paris) : santé, routes d'inscription OpenAPI présentes, taille/SHA-256
des manifestes comparés aux métadonnées des assets GitHub et présence d'une
signature updater. Les binaires ne sont pas téléchargés ni leurs signatures
vérifiées cryptographiquement par ce préflight. Mode `--registration present` :
l'ouverture ou la fermeture effective des inscriptions n'est pas testée.
Canal Dev `0.6.0-dev.221` vers `http://127.0.0.1:8765`, canal Prod
`0.6.0-prod.201` vers `https://studio.flosrent.fr`.

La référence distante `deploy/ovh-vps` vaut `354e9fe790d128b1a2992bd62ec60e589358cb2f`.
Ses [CI](https://github.com/redsilvernight/studio-os/actions/runs/38131715312) et
[Desktop channels](https://github.com/redsilvernight/studio-os/actions/runs/38131715318)
ont une conclusion `success`. Cela décrit cette référence Git ; aucune empreinte
de build servie par le VPS n'a été attestée. La CI de la présente branche reste
à exécuter après autorisation du push/PR.

Réserves pour la promotion humaine P06 :

1. Terminer la validation CSP et son ticket, puis vérifier l'enforcement sur les
   parcours authentifiés du domaine public.
2. Rétablir/attester le routage de la sonde `/version` exposée aux clients,
   puis identifier le build réellement déployé ; le préflight actuel ne le vérifie pas.
3. Conserver les exercices périodiques, la preuve de restauration d'un backup
   représentatif du VPS, la rétention/réplication et la garde des secrets.
4. Les exercices de rotation globale JWT, rollback N-1 vers N et deux machines
   physiques restent distincts des tests automatisés de cette collecte.

## Reproduction

Première préparation, avec une base neuve dédiée (ne pas réutiliser une base
d'un autre travail) :

```powershell
docker exec studio-os-test-pg createdb -U studio studio_os_ops_bb335466
uv sync --all-packages
pwsh -NoProfile -File scripts/test-env.ps1 -Database studio_os_ops_bb335466
$env:STUDIO_DATABASE_URL = 'postgresql+asyncpg://studio:studio@127.0.0.1:5432/studio_os_ops_bb335466'
Push-Location services/api
uv run --no-sync alembic current
uv run --no-sync alembic heads
Pop-Location
pwsh -NoProfile -File scripts/ops-evidence.ps1
$env:STUDIO_TEST_DATABASE_URL = $env:STUDIO_DATABASE_URL
uv run --no-sync pytest -n 6 -q --junitxml=output/ops-evidence/full.xml
node desktop/scripts/production-gate.mjs --base-url https://studio.flosrent.fr --expected-api-origin https://studio.flosrent.fr --registration present --require-stable
```

Le script de récupération crée à chaque appel deux nouveaux projets Compose et
écrit `recovery.json`/`recovery.log` sous `output/ops-evidence/<run_id>/`.
Les sorties brutes ciblées, suite complète, préflight et sondes publiques restent
dans `output/ops-evidence/`. Ne pas commiter les dumps ni les volumes.
Le nettoyage de ces ressources conservées attend un accord explicite.

Incident de préparation constaté : `scripts/test-env.ps1` a imprimé `ready` et
rendu 0 après `Can't locate revision identified by '0034'` sur la base partagée,
alors que le premier checkout était encore à `0033`. La base partagée n'a pas été
abaissée ; une base distincte a été créée et le head a été contrôlé explicitement.
