# Claude First — implémentation

## Modifications de cette mission

Aucun code, contrat, configuration personnelle, projection générée ou hook n'a été modifié. Les seuls nouveaux fichiers sont les sept rapports de `docs/audits/studios-agent-workflow/claude-first/`. Le dépôt contenait déjà des modifications non committées étendues; elles ont été préservées.

La correction instructionnelle requiert d'éditer `C:\Users\redsi\.claude\rules\studio-protocol.md`. Conformément à la mission, elle n'est pas appliquée sans autorisation.

## Patch préparé — non appliqué

Insérer immédiatement avant la première consigne de démarrage dans `~/.claude/rules/studio-protocol.md` :

```diff
 # Protocole Studio OS

 Studio OS est la mémoire persistante ; le contexte de l'IA n'est qu'un cache temporaire.

-1. Commencer par `studio_start_work` (avec tâche : claim, session et contexte) ; jamais de balayage large du dépôt ou de la documentation.
+1. Classifier d'abord l'intention. Pour une demande explicitement readonly (audit, observation ou diagnostic sans changement), appeler `studio_prepare_context` et utiliser uniquement des lectures; ne jamais démarrer/claim/sync/handoff ni écrire. Pour un travail suivi avec mutations autorisées, appeler une fois `studio_start_work` sur la tâche existante.
```

Ce patch réconcilie la règle globale avec le protocole projet sans changer Codex, OpenCode ou les permissions. Il n'est pas installé et n'a pas été testé. Il doit être approuvé avant application.

## Vérification après correction, si autorisée

1. Vérifier le diff exact du fichier personnel, sans lire ni modifier d'autres champs de configuration.
2. Exécuter une nouvelle session Claude Code avec une formulation naturelle readonly et vérifier `/memory` ou le hook `InstructionsLoaded` pour les fichiers chargés; aucune mutation métier ne doit apparaître.
3. Répéter le prompt dans Claude Desktop après avoir vérifié le connecteur réel. Ne pas confondre ce résultat avec le CLI.
4. Faire les tests de cycle complet seulement après disponibilité d'un projet et d'une base isolés.

Aucune correction serveur n'est proposée : la cause reproduite à présent porte sur la connectivité/configuration et une contradiction de consignes, pas sur un défaut démontré du serveur courant.
