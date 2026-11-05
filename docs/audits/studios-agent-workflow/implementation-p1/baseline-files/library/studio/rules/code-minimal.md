---
kind: rule
stable_key: code-minimal
scope: studio
description: "Code minimal (d'après ponytail, MIT) : résoudre toute la tâche avec le moins de code neuf, sans rogner sécurité ni validation."
---

# Code minimal (d'après ponytail, MIT)

Le meilleur code est celui qu'on n'écrit pas : résoudre toute la tâche avec le moins de code neuf.

- Avant d'écrire : lire la tâche et le code touché ; lister ce que le changement doit atteindre (appelants, tests, fixtures, config, exports) et ce qu'il peut casser. C'est le périmètre ; les extras n'en sont pas.
- Prendre la première option qui marche entièrement : inutile → ne pas le faire (le nommer en une ligne) ; déjà dans le dépôt → réutiliser comme le code voisin ; bibliothèque standard ou plateforme ; dépendance déjà installée (jamais une nouvelle pour quelques lignes) ; une ligne lisible d'un coup d'œil ; sinon le minimum.
- Paresseux sur la solution, jamais sur le changement : finir appelants, tests et fixtures que le changement casse.
- Ni abstraction, wrapper, option, config ni code « pour plus tard » non demandés ; supprimer plutôt qu'ajouter ; garder la structure existante.
- Bug : chercher tous les appelants, corriger la cause une seule fois dans le code partagé.
- Logique non triviale (branche, boucle, parseur, argent, sécurité, nouveau script) : un petit test ou une auto-vérification.
- Raccourci à limite connue : commentaire `shortcut: <limite>, <quand l'améliorer>`.
- Jamais rogné : validation aux frontières de confiance, gestion d'erreurs contre la perte de données, sécurité, accessibilité, ce que l'utilisateur a demandé.
- Fin de réponse : une ligne sur ce qui est omis ou non vérifié et le risque éventuel.
