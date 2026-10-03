# Brancher un projet et ses agents IA

Ce guide couvre les quatre opérations courantes du Project AI Bootstrap. Les
commandes sont à lancer depuis la racine du dépôt Git concerné.

## Préparer le poste

Le poste doit disposer de `studio-client`, d'un profil connecté et d'au moins un
harness installé (`claude-code`, `opencode` ou `codex`).

```powershell
studio-client login --api-base-url https://studio.example.com
studio-client projects list
```

Conserver l'identifiant UUID du projet renvoyé par `projects list`.

## Connecter un projet existant

L'enregistrement local associe le dépôt de ce poste au projet partagé. Il ne
modifie pas le dépôt.

```powershell
studio-client workspaces register `
  --path C:\chemin\absolu\du\depot `
  --project-id 00000000-0000-0000-0000-000000000000 `
  --slug mon-projet
```

Prévisualiser ensuite l'installation du hook d'identité, puis l'appliquer pour
chaque harness utilisé sur ce poste :

```powershell
studio-client setup-hooks --harness codex --dry-run
studio-client setup-hooks --harness codex
```

Si le dépôt ne contient pas encore de manifeste, initialiser ses sources
canoniques, matérialiser les projections et vérifier le résultat :

```powershell
studio-client bootstrap init `
  --project-slug mon-projet `
  --project-name "Mon projet" `
  --harness codex
studio-client bootstrap sync
studio-client bootstrap check
studio-client adapters check
```

Le registre de workspace et les identifiants locaux restent hors du dépôt. Le
manifeste `.agents/bootstrap.json`, les sources `.agents/` et les blocs gérés
sont partageables par Git.

Pour que le poste publie son heartbeat et reçoive les opérations distantes,
lancer l'application Desktop ou `studio-client-daemon`.

## Ajouter un harness

Ne pas recréer les règles ou skills : `.agents/` reste la source unique. Rejouer
`bootstrap init` avec `--overwrite` et la liste complète des harnesses voulus,
puis régénérer les projections.

```powershell
studio-client setup-hooks --harness opencode --dry-run
studio-client setup-hooks --harness opencode
studio-client bootstrap init `
  --project-slug mon-projet `
  --project-name "Mon projet" `
  --harness codex `
  --harness opencode `
  --overwrite
studio-client bootstrap sync
studio-client adapters check
```

Un second `bootstrap sync` doit répondre que tout est à jour. Si le projet
utilise aussi Claude Code, conserver également `--harness claude-code` dans la
liste : `init --overwrite` décrit l'ensemble attendu, pas seulement l'ajout.

## Diagnostiquer et réparer un drift

Commencer par une vérification sans écriture et lire le diff :

```powershell
studio-client bootstrap check
studio-client bootstrap diff
```

Si les changements sont bien des projections obsolètes, les régénérer :

```powershell
studio-client bootstrap sync
studio-client bootstrap check
studio-client adapters check
```

La politique `refuse` bloque un fichier modifié hors gestion. La politique
`ask` demande une confirmation ; ne passer `--yes` qu'après lecture du diff.
Pour annuler la dernière synchronisation :

```powershell
studio-client bootstrap rollback --list
studio-client bootstrap rollback
```

Le rollback refuse par défaut d'écraser un fichier modifié depuis la sauvegarde.
`--force` est une récupération explicite, à réserver à un état déjà inspecté.

Si le drift concerne les bibliothèques ou règles partagées plutôt que le bundle
du projet, utiliser les contrôles dédiés :

```powershell
studio-client skills check
studio-client skills diff
studio-client skills sync
studio-client rules sync
```

Un manifeste dont `format` annonce une version inconnue ou future est refusé
avant toute écriture. Mettre le client à niveau ou réinitialiser le manifeste
après revue ; ne pas modifier seulement la chaîne de version pour contourner le
contrôle.

## Lancer une tâche à distance

Sur le poste qui exécutera la tâche :

1. enregistrer le vrai dépôt Git avec `workspaces register` ;
2. ouvrir **Desktop > Intégrations** ;
3. activer **Accepter les lancements demandés à distance sur ce poste** ;
4. choisir la concurrence maximale et les harnesses autorisés ;
5. laisser le daemon actif.

Dans le Dashboard, ouvrir la tâche, choisir une machine éligible, un harness et,
si nécessaire, un agent. Vérifier l'aperçu de résolution, puis utiliser **Lancer
sur cette machine**. La fiche affiche ensuite le statut rapporté par la machine,
la session associée et l'action d'annulation.

Un lancement ne transmet ni commande arbitraire, ni chemin de travail, ni
variables d'environnement. Le serveur contrôle l'accès au projet et le grant de
lancement ; la machine applique encore son opt-in, son workspace enregistré, sa
liste de harnesses et sa limite de concurrence.

## En cas d'échec

- « workspace introuvable » : enregistrer le chemin du vrai dépôt Git, pas un
  dossier parent ou une copie sans `.git` ;
- harness non éligible : l'installer, ajouter son hook et l'autoriser dans les
  réglages locaux ;
- version de manifeste non supportée : mettre à niveau le client ou revenir à
  un manifeste `studio.bootstrap/v1` validé ;
- drift persistant : relire `bootstrap diff`, puis restaurer ou accepter
  explicitement le fichier concerné avant de synchroniser.
