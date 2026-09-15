# AI Operating Reference

## Mission du systeme
Studio OS est la source d'etat partagee entre deux humains et leurs agents. Une IA doit l'utiliser pour comprendre le contexte avant d'agir, journaliser ses actions importantes et eviter les collisions.

## Regles de comportement
1. Avant une modification substantielle, recuperer la tache et l'etat du projet.
2. Verifier claims et conflits avant de modifier des ressources sensibles.
3. Respecter les decisions DEC-XXXX deja validees.
4. Utiliser Graphify pour cibler les fichiers avant un balayage massif du repo.
5. Utiliser la memoire partagee en lecture; n'ecrire que si le role l'autorise.
6. La memoire partagee est en lecture seule par defaut : un agent n'y ecrit que si son role l'autorise explicitement.
7. Tout travail IA substantiel doit produire un AIWorkLog.
8. Ne jamais inventer l'etat d'un autre developpeur; interroger Studio OS.
9. Ne jamais supposer un LAN commun ou un acces direct a l'autre machine.
10. Pour les gros fichiers, utiliser Studio Transfer; ne jamais les pousser via l'API applicative.

## Hierarchie de contexte
Ordre de confiance:
1. Contrats et decisions valides.
2. Etat courant Studio OS.
3. Git local et GitHub.
4. Graphify local.
5. Memoire projet/studio.
6. Hypotheses de l'agent.

## Cycle de tache IA
- load task
- load project state
- inspect decisions
- inspect conflicts/claims
- fetch targeted graph context
- execute work
- run tests
- record changed files/tests/result
- set review state
- emit relevant events

## Interdictions
- Pas de modification silencieuse des contrats partages.
- Pas de creation d'un backend parallele.
- Pas de synchronisation de memoire privee.
- Pas de verrou bloquant des fichiers.
- Pas de suppression automatique d'un transfert non expire sans politique explicite.
