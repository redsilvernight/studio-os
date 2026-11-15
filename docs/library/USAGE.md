# Library canonique : guide d'usage

La Library Studio OS est la source unique de la configuration IA : règles,
skills, définitions d'agents et hooks. Les fichiers lus par les harnais
(Claude Code, Codex, OpenCode) en sont des **projections** : on ne les édite
pas pour changer la référence, on publie dans la Library.

## Modèle

| Scope | Pour qui | Où elle est projetée |
| --- | --- | --- |
| `studio` | tout le studio | dossier personnel de chaque poste |
| `project` | membres du projet | dépôt du projet (`bootstrap sync`) |
| `user` | son propriétaire seul | dossier personnel du propriétaire |

Une ressource a des versions immuables et une version active. Créer une
version ne change rien ; seule l'**activation** la rend effective. À clé
égale, une ressource `user` active masque la ressource commune : c'est
l'**override**. Un override déprécié rend la main au commun (DEC-0324).

## Parcours de bout en bout

1. **Publier le commun.** Dans le dashboard, page Library : créer la
   ressource (version 1 en brouillon), puis l'activer. Une nouvelle version
   suit le même chemin (créer, puis activer).
2. **Recevoir la mise à jour.** Le daemon de chaque poste compare la Library
   active à ses projections. Si la synchronisation automatique est désactivée,
   la mise à jour reste « à confirmer » et rien n'est écrit.
3. **Confirmer.** Panneau « Synchronisation de la Library » : pour chaque
   élément, choisir *Utiliser la Library*, *Garder ma version* ou, si le
   fichier a été modifié localement, *Publier comme mon override* ; puis
   *Appliquer les choix* et confirmer. Avec la synchronisation automatique
   active, les mises à jour sans conflit local sont appliquées au démarrage
   du daemon ; un fichier modifié localement n'est jamais écrasé sans choix.
4. **Projection.** Les règles, skills et agents sont écrits dans les dossiers
   des harnais (voir « Fichiers locaux » plus bas). Chaque écriture est
   journalisée et restaurable.
5. **Hooks.** Un hook commun n'est jamais installé sans consentement
   explicite. Toute nouvelle version redemande ce consentement.
6. **Override.** Publier sa version (choix *Publier comme mon override*, ou
   création d'une ressource `user` dérivée du commun, puis activation). Elle
   n'est projetée que chez son propriétaire ; les autres utilisateurs ne la
   voient pas, même via l'API (404).
7. **Alerte.** Quand le commun active une nouvelle version, l'override affiche
   « mise à jour de la base disponible » dans son détail.
8. **Fusion.** Le détail de l'override montre trois volets (base, ma
   version, nouveau commun), l'aperçu fusionné et les conflits. Pour chaque
   bloc en conflit : accepter le commun, garder ma version, garder les deux
   ou revenir à la base. Le résultat reste modifiable ; *Publier le
   résultat* n'est possible qu'une fois tous les conflits résolus, après une
   seule confirmation. *Garder mon override* le rattache au nouveau commun
   sans changer son texte.
9. **Retour au commun.** *Revenir au commun* déprécie l'override : la
   prochaine synchronisation projette le commun. L'override reste dans
   l'historique et une version précédente peut être réactivée.

Côté API, les choix de l'étape 8 et 9 passent par
`POST /api/v1/library/{id}/merge-apply` (DEC-0356, `TECH/02_API_CONTRACT.md`).
Un conflit non résolu, un contenu invalide pour le kind ou un aperçu périmé
n'écrit rien.

## Droits

Rôles : `admin`, `developer`, `agent` (écriture) et `readonly` (lecture).

| Scope | Lire | Créer, versionner, activer, déprécier |
| --- | --- | --- |
| `studio` | tout membre d'au moins un projet | `admin` seulement |
| `project` | membres du projet | membres du projet en rôle d'écriture, quel que soit le créateur |
| `user` | propriétaire et `admin` | propriétaire et `admin` |

L'aperçu et l'application d'une fusion sont réservés au propriétaire de
l'override. Une ressource `user` d'autrui répond 404, jamais 403.

## Fichiers locaux et suivi Git

**Suivi dans Git (dépôt du projet).** `.studio/studio-protocol.md`,
`AGENTS.md`, `CLAUDE.md`, `opencode.json` et les projections projet
`.claude/`, `.codex/`, `.opencode/`. Ces projections sont générées : les
régénérer par `studio-client bootstrap sync --project-id <id>`, puis vérifier
par `studio-client adapters check --project-id <id>`, au lieu de les éditer.
`.agents/` n'est plus suivi (P45).

**Jamais suivi (dossier personnel du poste).**

- Projections globales : `~/.claude/rules/`, `~/.claude/skills/`,
  `~/.claude/agents/`, `~/.agents/rules/`, `~/.agents/skills/`,
  `~/.agents/definitions/`, `~/.config/opencode/skills/`.
- Manifestes de suivi : `~/.studio-os/library-*-manifest.json`.
- Journaux de restauration : `~/.studio-os/backups/bootstrap/library-<id>/`.
- Consentement des hooks : `~/.studio/hook-consent.json`.
- État et réglage de la synchronisation : `skills-sync-status.json` et
  `skills-sync-settings.json` dans le dossier de données du client.

Dans le dépôt, `.studio-os/` et `.claude/settings.local.json` sont ignorés.

## Restaurer

```powershell
studio-client library restore --list
studio-client library restore --backup-id library-<id>
```

Hors ligne, sans credentials ; refuse si un fichier a été modifié depuis. Pour
le dépôt du projet : `studio-client bootstrap rollback --list` puis
`--backup-id <id>`. Détails : [restauration des projections](../LIBRARY_PROJECTION_RESTORE.md)
et [Library dans ce dépôt](P46-self-hosting.md).

Preuve de bout en bout : `tests/client/test_p80_library_canonical_e2e.py`.
