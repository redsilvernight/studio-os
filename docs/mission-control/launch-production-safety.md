# Lancements protégés et autorisation de production

Implémentation : DEC-0235, ticket fa864f0d-e0c9-44f0-894f-148f7548b31c.

## Comportement

Un nouveau lancement utilise le mode protégé par défaut : édition dans le dossier
courant, sans outils permettant d’exécuter une commande. Si la tâche exige une
commande, l’agent rend un handoff `blocked` indiquant la commande et la cible.
Il faut alors une nouvelle demande humaine ; l’agent ne peut pas s’auto-autoriser.

La case « Autoriser les commandes et les actions de production pour ce lancement »
est décochée au départ. La confirmation mentionne explicitement l’autorisation ;
la case est remise à zéro après création et lors d’un changement de cible.
Le dernier lancement affiche le choix enregistré côté serveur.

`allow_production=true` exige un JWT utilisateur validé. Un jeton machine/MCP,
même admin, reçoit `403 production_approval_requires_user_session`, avant le
raccourci d’idempotence et dans le service de création. La valeur est immuable,
stockée avec le demandeur et la date ; les retries/replays repartent toujours à
false. L’autorisation ne permet pas de contourner le profil ni les garde-fous
locaux, et ne vaut pas autorisation de push, merge ou rebase.

## Mise à jour coordonnée

Le contrat API passe de 2 à 3, transport `/api/v1` conservé. Déployer ensemble
API, dashboard et daemon compatibles. Migration 0037 : colonne booléenne non nulle
`task_launches.allow_production`, défaut serveur false, sans autoriser les archives.
Downgrade réversible vers 0036, validé uniquement sur la base de test.

La machine doit annoncer `launch_safety=true` pour être éligible. Sans cette
capacité, création/retry sont refusés et le pull ne livre aucun lancement.
Mettre à jour puis attendre un nouveau heartbeat avant de relancer.

Le mode protégé est garanti pour Claude Code par `--restricted` et une liste
fermée de tools (`Read,Edit,Write,Grep,Glob` ; lecture seule sans Edit/Write).
Il nécessite Claude Code >=2.1.248 ; une CLI antérieure échoue avant exécution.
Les autres adaptateurs échouent fermés en mode protégé tant qu’ils n’offrent pas
cette garantie. Une autorisation de production explicite peut autoriser leur
mode habituel, sans élargir leur sandbox ou profil existant.

## Preuves locales

- Migration 0037 : upgrade, downgrade 0036, upgrade exécutés sur `studio_os_test`.
- Tests API : défaut protégé, ancien daemon refusé, machine non autorisée,
  JWT humain autorisé, persistance et idempotence, retry sans héritage.
- Tests daemon : un adaptateur sans garantie est refusé avant préparation ou
  exécution ; le marqueur de la commande adversariale reste absent.
- Essai réel Claude Code 2.1.287 avec un faux MCP local et un script de déploiement
  inoffensif : `studio_start_work` puis `studio_handoff(task_status=blocked)`,
  aucune création du marqueur, code de sortie 0.
- Dashboard : compilation, tests unitaires et parcours Chromium incluant la
  confirmation de production et la remise à zéro du choix.

Le faux MCP et les sorties brutes de l’essai sont des fichiers temporaires locaux,
pas des services de production. Cette modification ne déploie rien.
