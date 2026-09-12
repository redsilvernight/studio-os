# Vision produit - Studio OS

## Resume
Studio OS est le systeme d'exploitation interne du studio. Il ne remplace pas Godot, Git, Claude, Qwen, Obsidian ou Graphify: il les relie afin que deux developpeurs et leurs agents IA partagent le meme contexte operationnel.

## Probleme resolu
Sans Studio OS, l'information est fragmentee: une tache est dans un outil, une decision dans une discussion, un commit sur GitHub, une note dans Obsidian, un graphe dans Graphify, une capture video sur un disque local et une IA ignore souvent ce que l'autre humain ou l'autre agent est en train de faire.

Studio OS centralise les liens entre ces objets sans obliger a centraliser tous les fichiers de travail.

## Proposition de valeur
Studio OS doit permettre de repondre immediatement a ces questions:
- Sur quoi travaille chaque humain ?
- Quels agents travaillent actuellement ?
- Quelles taches sont actives, bloquees ou en review ?
- Quels fichiers/sous-systemes risquent un conflit ?
- Quelles decisions architecturales s'appliquent a cette tache ?
- Quel contexte faut-il donner a Claude ou Qwen ?
- Quels travaux IA attendent une validation ?
- Quel build est le dernier valide ?
- Quels moments de capture peuvent alimenter le marketing ?
- Quels fichiers mon collegue m'a envoyes et pourquoi ?

## Architecture humaine
Le studio comporte deux developpeurs a distance. Chacun garde ses outils locaux. Un VPS OVH central heberge les services partages: API, MCP, base PostgreSQL, dashboard, event store et stockage objet.

## Ce que Studio OS n'est pas
- Ce n'est pas un IDE.
- Ce n'est pas un moteur de jeu.
- Ce n'est pas un remplacement de Git.
- Ce n'est pas un outil de surveillance de productivite.
- Ce n'est pas un systeme de partage de disque reseau.
- Ce n'est pas une IA unique qui controle tout.

## Philosophie
L'outil doit automatiser la documentation du travail plutot que forcer les developpeurs a remplir manuellement des formulaires. L'etat doit etre derive autant que possible de Git, des sessions de travail, des agents et des integrations locales.
