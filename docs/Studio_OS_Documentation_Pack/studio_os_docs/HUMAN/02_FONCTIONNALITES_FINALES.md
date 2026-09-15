# Fonctionnalites finales prevues

## Coordination du studio
- Tableau de bord global des projets, utilisateurs, machines et agents.
- Presence en ligne/idle/offline via heartbeat.
- Taches avec proprietaire humain ou agent, priorite, statut et dependances.
- Sessions de travail liees a une tache, une branche, une machine et des agents.
- Timeline des actions importantes.

## Collaboration et conflits
- Soft locks sur fichier, dossier, scene, ressource, module ou sous-systeme.
- Detection des claims qui se chevauchent.
- Detection des branches qui modifient les memes fichiers.
- Alertes de dependances bloquees.
- Suggestions d'action sans blocage de Git.

## IA et orchestration
- MCP central pour tout client compatible MCP.
- Studio Producer qui analyse priorites, blocages et parallelisation.
- Decomposition d'une grosse tache en sous-taches avec dependances.
- Recommandation d'executant: humain ou agent IA.
- AI Work Ledger pour tracer requete, resultat, fichiers, tests et review.
- Review Queue commune pour code IA, PR, decisions, memoire, builds et conflits.

## Memoire et connaissance
- Memoire privee locale, memoire projet partagee, memoire studio partagee.
- Recherche dans Obsidian depuis les agents autorises.
- Propositions de memoire avec approbation humaine.
- Memoire partagee en lecture seule par defaut pour les agents ; ecriture sur autorisation.
- Decision Log avec identifiants DEC-XXXX.

## Graphify et contexte
- Graphify reste local.
- Requete de dependances, symboles et fichiers pertinents.
- Generation de Context Packages par tache.
- Regroupement de la tache, decisions, commits, graphe, memoire, dependances et etat du projet.

## Git, GitHub et builds
- Detection locale de branche, commit, statut et fichiers modifies.
- Association tache <-> branche <-> commit <-> PR <-> build.
- Integration GitHub pour PR, issues, commits et Actions.
- Statut de builds visible dans le dashboard.

## Godot et enregistrements
- Detection du lancement/arret de Godot.
- Association automatique d'une session a un projet.
- Integration au systeme de capture existant.
- Marqueurs video manuels: `studio mark "..."`.
- Generation de candidats marketing a partir de moments interessants.

## Studio Transfer / Storage
- Transfert de fichiers entre les deux developpeurs.
- Upload et download resumables pour fichiers volumineux.
- Hash SHA-256 pour integrite.
- Historique, expiration et suppression.
- Association d'un transfert a un projet ou une tache.
- Categories: transfer, build, asset, recording, export, archive, other.
- Stockage via MinIO/S3 sur le VPS.
- URLs pre-signees temporaires.
- Drag & drop dans le dashboard et commandes CLI.
- Quotas et politique de retention.
- Les captures brutes restent locales par defaut.

## Fonctionnement hors ligne
- SQLite local pour les evenements en attente.
- Retry avec backoff exponentiel.
- UUID et idempotency keys.
- Deduplication serveur.
- Resynchronisation automatique au retour de la connexion.

## Notifications
Notifications uniquement pour les evenements qui demandent une action: conflit, build casse, review IA, PR prete, tache bloquee, decision/memoire a approuver, nouveau transfert.
