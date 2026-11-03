# Restaurer une projection locale

Les synchronisations de skills, règles et définitions d'agents conservent
désormais un journal des fichiers créés, remplacés ou retirés, ainsi que le
manifeste de suivi précédent. Cela couvre aussi une mise à jour normale d'un
fichier géré, pas seulement le remplacement confirmé d'une modification locale.
Les sauvegardes de conflits existantes restent disponibles à leur emplacement.

Le journal réutilise le mécanisme de sauvegarde et de rollback du bootstrap,
sous `~/.studio-os/backups/bootstrap/library-<id>/`. Il contient uniquement des
cibles de projection et leurs manifestes. Une copie remplacée est conservée
octet pour octet. Une création peut être annulée ; un retrait géré peut être
restauré.

```powershell
studio-client library restore --list
studio-client library restore --backup-id library-<id>
```

Sans identifiant, la restauration choisit le dernier journal appliqué. `--home`
permet d'inspecter un autre répertoire de harnais explicite. La liste est bornée
à 20 journaux et indique le reliquat. Ces commandes fonctionnent hors ligne,
sans lire les credentials du client.

Toutes les entrées sont vérifiées avant le premier changement. Un fichier
modifié après la synchronisation, un fichier recréé après un retrait ou une
cible extérieure aux projections fait refuser la restauration. Aucun `--force`
n'est proposé par cette commande. Le journal restauré est marqué et ne peut
pas être réappliqué une deuxième fois.

La synchronisation vérifie aussi que le manifeste n'a pas changé depuis le
plan et conserve les protections existantes des fichiers. Une sélection
partielle conserve les autres entrées du manifeste.

La restauration concerne les fichiers locaux. Elle ne change aucune définition
ni activation du serveur et ne crée pas de verrou de version serveur. Si la
synchronisation automatique est activée, elle peut reproposer ou réappliquer
la version active distante ; utiliser le réglage existant de synchronisation
automatique pour suspendre ces mises à jour pendant une restauration durable.
Les journaux documentent les synchronisations terminées ; le rollback d'une
erreur d'application du daemon conserve son mécanisme existant de remise en
état locale.

Validation : `tests/client/test_projection_backups.py` couvre les trois copies
de skill, les règles, le manifeste, les créations, les retraits et recréations,
les éditions locales, les journaux altérés et les commandes hors ligne.
