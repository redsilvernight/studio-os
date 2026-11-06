---
kind: skill
stable_key: itch-io-publish
scope: studio
description: "Publier une version d'un jeu Godot sur itch.io : export headless, upload Butler, channels, gate de confirmation. Porté par l'agent devops. Pas pour TikTok/Instagram ni pour modifier le code du jeu."
---

# Publication de versions de jeu sur itch.io

Pipeline complet : localiser le projet Godot, l'exporter si besoin, pousser la build sur itch.io via Butler. Normalement exécuté par l'agent `devops`, appelé par `chef-marketing` pour l'orchestration (contenu, date).

## Prérequis

- Godot 4 (CLI headless) et les modèles d'export de cette version.
- Butler, authentifié par l'utilisateur lui-même (`butler login`, autorisation OAuth dans son navigateur ; aucun identifiant ne passe par l'agent).
- Absent ou non authentifié : le signaler, proposer l'installation ou l'authentification, ne jamais improviser un substitut.

## Repères

- **Projet** : chercher, sous la racine des projets indiquée par l'utilisateur, un `project.godot` dont `config/name` correspond ; un jeu peut être niché dans un sous-dossier. Jamais de chemin supposé depuis le seul nom.
- **Compte itch.io** : celui du studio, à confirmer avec l'utilisateur. Le slug exact de la page d'un jeu se confirme avant le tout premier push, puis se mémorise dans la config ci-dessous ; jamais deviné.
- **Butler** : appelé par son chemin complet s'il n'est pas sur le PATH.

## Config par projet : `<projet>/itch-release.json`

Créée au premier push, à côté de `project.godot`, pour ne pas reposer les mêmes questions :

```json
{
  "itch_user": "<compte>",
  "itch_project_slug": "<slug>",
  "channels": {
    "windows": "export/windows",
    "html5": "export/web"
  }
}
```

- `channels` associe un nom de channel (convention Butler : `windows`, `html5`, `linux`, `osx`, minuscules sans tiret) au **dossier ou fichier exporté**. Pour un exécutable avec ses `.pck`/bibliothèques, pointer le dossier complet sauf si les annexes sont déjà isolées ; vérifier `export_path` dans `export_presets.cfg`.
- Pas un secret ; peut être versionné, mais demander avant d'ajouter un fichier suivi au dépôt.
- S'il existe, le lire sans redemander compte, slug ni channels, sauf changement signalé.

## Processus de release

1. **Localiser le projet** (voir Repères).
2. **Lire ou créer `itch-release.json`**. Absent : demander le slug et les channels (par défaut, tous les presets de `export_presets.cfg`).
3. **Ré-export nécessaire ?** Comparer la date des dossiers d'export à celle des sources (`git log -1 --format=%ct`, ou dates des dossiers de scènes et scripts). Sources plus récentes : ré-exporter avant de pousser ; jamais de build périmée poussée sans le dire.
   ```
   "<godot>" --headless --path "<projet>" --export-release "<preset>" "<export_path>"
   ```
   Préférer `--export-release` (`--export-debug` seulement sur demande). Échec peu bavard : vérifier d'abord la présence des modèles d'export, en capturant toute la sortie.
4. **Version** : `project.godot` n'a souvent pas de `config/version` fiable ; demander la version (ou un tag git existant) à l'utilisateur ou à `chef-marketing`, jamais l'inventer. Transmise via `--userversion`.
5. **État avant push** : itch.io n'a pas de brouillon ; un push modifie immédiatement le channel, visible des joueurs en mise à jour automatique (sauf page privée ou brouillon côté itch.io). Afficher `butler status <user>/<slug>:<channel>` et l'inclure au récapitulatif.
6. **Gate de publication (obligatoire, jamais contournée)** : récapituler jeu, version, channels, fichiers poussés, taille approximative, et attendre une confirmation explicite de l'utilisateur avant `butler push`. Même si `chef-marketing` a validé contenu et date : la confirmation d'exécution reste distincte de la décision éditoriale.
7. **Push**, pour chaque channel confirmé :
   ```
   "<butler>" push "<chemin_build>" <itch_user>/<itch_project_slug>:<channel> --userversion "<version>"
   ```
8. **Vérifier** : `butler status` après push pour confirmer que le nouveau build est en tête du channel ; rapporter lien, version et channels mis à jour.

## Ce que ce skill ne fait pas

- Ne décide ni du contenu ni de la date de la release (`chef-marketing` ou l'utilisateur).
- Ne modifie jamais le code du jeu.
- Ne gère pas la page itch.io (description, captures, prix) : action manuelle de l'utilisateur.
