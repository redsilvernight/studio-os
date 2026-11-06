# Plan de reconstruction et purge de la Library

## État de préparation

**Purge non exécutée. Aucun accès de mutation à la production n’a été utilisé.** La découverte actuelle prouve que le catalogue n’est pas vide: 38 définitions Studio, 30 User et 19 Project pour Studio OS. Elle ne compte ni les références, ni les installations, ni les projets utilisateurs concernés.

## Périmètre candidat à valider

Le code de migration `services/api/alembic/versions/0009_ai_library.py` crée les tables `library_resources`, `library_resource_versions`, `library_resource_links` et `library_project_locks`. Ce sont les seules tables candidates identifiées à ce stade. Ne pas supprimer des tâches, décisions, sessions, événements, données de vault, fichiers de transfert, comptes ou métadonnées runtime. Les liens et locks peuvent relier des versions à des installations/projets et doivent être inventoriés avant toute décision de périmètre.

Le manifeste exact de purge n’est **pas encore établi**: il faut lire les modèles et contraintes actuels, inventorier les tables réelles et les dépendances externes (projections locales, locks, versions pinned, hooks consentis) puis confirmer quelles ressources entrent dans le périmètre.

## Volumes et effets connus

| Élément | Volume connu | Effet / incertitude |
|---|---:|---|
| Définitions visibles dans les scopes interrogés | 87 | Compte les ressources visibles dans les scopes Studio, User et Project; ne représente pas les lignes DB si versions historiques incluses. |
| Versions historiques | non mesuré | Les pointers/locks peuvent référencer une version précise. |
| Liens de dépendance et project locks | non mesuré | Leur suppression peut casser résolution, pinning ou synchronisation. |
| Installations locales et projections | non mesuré | La suppression serveur peut laisser des fichiers locaux puis rendre la future synchro impossible; les sauvegardes/manifests doivent guider le rollback. |
| Utilisateurs affectés / hooks consentis | non mesuré | Risque d’inactiver des outils et de changer une empreinte nécessitant un nouveau consentement. |

## Préconditions obligatoires

1. Lire les modèles, contraintes FK/cascade, endpoints et comportement client de désinstallation/retour arrière.
2. Obtenir un inventaire en lecture seule par scope: ressources actives/dépréciées, versions, links, locks, références de résolution et permissions. Calculer les volumes par code, pas par estimation.
3. Sauvegarder les seules tables approuvées dans une sauvegarde cohérente et protégée. Vérifier absence de secrets dans les copies de rapport.
4. Restaurer la sauvegarde dans un environnement isolé et comparer les compteurs, relations, hashes et résolutions.
5. Préparer un catalogue seed et son manifeste: versions, liens, dépendances, scopes, owners, permissions attendues.
6. Tester import, installation Core seule, Core + Personal, mise à jour, désinstallation de l’overlay et rollback dans une base isolée.
7. Répéter la purge en environnement isolé puis restaurer; capturer compteurs et diff avant/après.
8. Faire un dernier dry-run production, confirmer l’URL/environnement sans afficher de credential, puis présenter périmètre, volumes, sauvegarde/restauration, impacts et rollback.

## Rollback envisagé

Stopper le job à la première divergence; ne pas poursuivre une publication partielle. Restaurer le snapshot validé des seules tables de Library, vérifier les FK/liens et les permissions, puis réinstaller les projections à partir des manifestes sauvegardés. L’ordre et la procédure transactionnelle restent à confirmer sur le modèle réel et le test isolé.

## Point d’arrêt humain

Avant toute purge de production ou publication, présenter le manifeste exact et les preuves ci-dessus, puis attendre une confirmation explicite dans cet échange. L’autorisation générale contenue dans le brief ne vaut pas cette confirmation spécifique. État actuel: **approbation de production non sollicitée, aucun changement de production**.


## Phase 2D — ce que l'environnement isolé prouve (et ne prouve pas)

**Prouvé** (base isolée) : reconstruction Core → Project → Personal (84), rejeu sans effet, confidentialité inter-utilisateurs par l'API réelle, mise à jour, retour de version, reprise après échec partiel, installations par runtime.

**Non prouvé** : aucune purge n'a été exécutée, même isolée ; restauration d'un snapshot, FK, volumes et installations d'une base de production peuplée ; comportement réseau sous charge (429) ; runtimes réellement lancés. Le point d'arrêt humain reste intact : aucune mutation de production, aucune approbation sollicitée.


## Phase 2E — implications des skills multi-fichiers

Les auxiliaires vivent dans le contenu JSON des versions (aucun artefact objet) : une sauvegarde de base les inclut, aucune étape MinIO supplémentaire. Après une restauration de production, resynchroniser les postes : un arbre local peut contenir des auxiliaires d'une version plus récente que la base restaurée (dérive signalée par le manifeste, `overwrite` explicite requis). Prévoir dans l'estimation le volume des versions de `studio-task`, `graphify`, `workstation-setup`. Un `pg_dump`/`pg_restore` a été rejoué en base isolée (`VALIDATION.md` § Phase 2E) ; il ne remplace pas une répétition sur une copie de production, qui reste un prérequis. Point d'arrêt humain inchangé : aucune mutation de production.
