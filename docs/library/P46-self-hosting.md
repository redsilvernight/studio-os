# Library canonique dans le dépôt Studio OS

La Library Studio OS fournit les définitions communes des agents, règles et
skills. Après avoir configuré le profil du client, depuis la racine du dépôt :

```powershell
$projectId = '2a836038-153c-41cf-879a-73bd794760b0'
studio-client bootstrap check --project-id $projectId
studio-client bootstrap sync --project-id $projectId
studio-client adapters check --project-id $projectId
```

Examiner les conflits signalés par `bootstrap check` avant de confirmer un
remplacement. Relancer `adapters check` après la synchronisation pour vérifier
les projections gérées contre la Library active.

## Si le serveur est indisponible

- Sur un poste déjà synchronisé, conserver les projections locales. Le client
  charge les définitions avant toute écriture de `bootstrap sync`. Les commandes
  de vérification qui consultent la Library pourront être reprises à son retour.
- Sur un clone neuf, partir de [`.studio/studio-protocol.md`](../../.studio/studio-protocol.md)
  et des règles versionnées sous [`.claude/rules/`](../../.claude/rules/).
  Pour retrouver une règle historique précise, consulter
  `git show 1d394baf:.agents/rules/<règle>.md`. Ces fichiers permettent de
  poursuivre la lecture du code, l’édition et les tests locaux. Reprendre les
  opérations de suivi Studio OS et la génération des projections au retour du serveur.
- Si la dernière synchronisation doit être annulée, lister ses sauvegardes
  locales avec `studio-client bootstrap rollback --list`, choisir l’identifiant
  de l’opération, puis lancer `studio-client bootstrap rollback --backup-id <id>`.
  En cas de refus lié à une modification plus récente, examiner cette modification
  avant de restaurer. Le rollback fonctionne hors ligne.

## Vérification du basculement

Le merge P45 (`7a846975`) déplace le protocole dans `.studio/` et retire les
sources `.agents/` du suivi Git. Comparaison du parent `1d394baf` avec la
Library active le 13 novembre 2026, après normalisation des fins de ligne et
retrait du front matter historique :

| Règles | Résultat |
| --- | --- |
| `contracts`, `database`, `mcp-tools`, `offline-sync`, `python-conventions`, `storage-transfers`, `testing` | 7 sur 7 en version projet 2, textes et listes `applies_to` identiques |
| `studio-protocol` | Texte identique à la version studio active 1 |

`git diff --exit-code 1d394baf 6fa6fa78 -- .claude/rules` confirme aussi que
les sept règles Claude versionnées sont identiques avant et après le basculement.
