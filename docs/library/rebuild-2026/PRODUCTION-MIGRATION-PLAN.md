# Runbook de migration de production (à ne pas exécuter)

**Statut : plan seulement.** Aucun script de suppression. Toute étape marquée ⛔ exige une autorisation distincte dans le chat. Principe : publier de nouvelles versions et en activer ; **ne jamais supprimer** ressource ni version. Le rollback consiste à réactiver les versions précédentes, ou à restaurer le snapshot.

## P0 — Préconditions (aucune mutation)

1. PR #222 fusionnée dans `dev` (CI lue) ; packages Core/Project/Personal régénérés, hashes vérifiés (`library_import` en dry-run, 84 définitions).
2. ⛔ Autorisation de sauvegarde de production donnée ; `BACKUP-RESTORE-PLAN.md` exécuté jusqu'à restauration réussie ; durée connue.
3. ⛔ Répétition générale réussie (section ci-dessous).
4. Décisions durables enregistrées (`studio_add_decision`) : remplacement de `studio-protocol` v3, dépréciation des 6 copies `user`.
5. Fenêtre choisie, aucune session active sur le projet (`studio_get_sessions`).

## P1 — Inventaire complet (sur la copie restaurée)

Comptages SQL en lecture seule : versions par ressource, liens, locks par projet, `runtime_bindings`, comptes. Comparer les hashes de production aux manifestes ; les 60 `KEEP` avec écart passent en `REVIEW_REQUIRED` et bloquent la suite jusqu'à décision.

## P2 — Migration (⛔ production, après P0 et P1)

Ordre imposé par les dépendances, un lot à la fois, arrêt à la première divergence :

1. Créer les 7 nouvelles ressources : skills Core `studio-task`, `studio-context`, `studio-handoff`, `studio-decision` ; rule Project `testing` ; skill Project `graphify` ; skill Personal `delegate-local`. Vérifier présence, hash, scope, owner.
2. Publier (sans activer) les versions suivantes des 4 skills et 6 rules Project.
3. Publier les versions des 6 agents Project (dépendent de `graphify`, `testing`).
4. Publier `studio-protocol` v3 (Core), sans activer.
5. Contrôle intermédiaire : comptes = avant + 7 ressources + 17 versions ; aucun lien cassé ; permissions inchangées.
6. Activer par lots dans l'ordre 2 → 3, contrôler la résolution après chaque lot.
7. Activer `studio-protocol` v3 en dernier ; régénérer les projections locales (`rules sync`, `skills`, `adapters check`) sur les postes.
8. Déprécier les 6 copies `user` doublons seulement après vérification que la clé `studio` résout correctement.
9. Ne rien faire sur les 4 hooks `user` ; aucun hook Core activé sans consentement.

Conflits : une clé inattendue, un hash divergent, une 409 (`expected_version`) ou un lock pointant une version à remplacer = arrêt, relecture, décision.

## P3 — Vérification

- Comptages : 87 + 7 = 94 ressources, aucune supprimée ; 17 nouvelles versions actives ; 6 dépréciées.
- Hashes : chaque version active = hash du manifeste (CRLF normalisé LF).
- Versions : actives conformes à la table de `MIGRATION-MAP.md`.
- Permissions : compte non propriétaire ne voit pas les définitions `user`.
- Références : 45 dépendances résolues ; locks valides.
- Installations : projet jetable, install/désinstall/réinstall Core, Project, Personal ; 3 runtimes (`claude`, `codex`, `opencode`) via le test natif.
- Fonctionnel : `studio_start_work` sur un projet test charge la rule v3.

## P4 — Rollback

**Déclencheurs** : divergence de comptage ou de hash, lien ou lock cassé, échec de résolution, permission élargie, échec d'un runtime, ou demande humaine.

1. Stopper les publications.
2. Réactiver les versions précédentes (v2 pour `studio-protocol`, v1/v2 pour les autres) et réactiver les copies `user` dépréciées ; contrôler les résolutions.
3. Si l'état reste incohérent : ⛔ restaurer le snapshot validé (`restore.sh`, procédure du plan de sauvegarde), puis régénérer les projections depuis les manifestes sauvegardés.
4. Contrôles après restauration : comptes = sauvegarde, FK, permissions, hashes.

Le rollback par réactivation ne perd aucune donnée (rien n'est supprimé) ; la restauration complète perd les écritures postérieures au dump : d'où la fenêtre sans session active.

## Répétition générale (prérequis et contenu)

**Prérequis** : copie restaurée disponible et autorisée (dump de P0.2), stack isolée (ports et volumes dédiés), aucune URL ni credential de production, hors du PostgreSQL partagé.

**À jouer** : P1 puis P2 complet sur la copie en conservant les identifiants ; collisions (une clé déjà présente, un hash divergent, un lock sur v1) ; migration de versions ; installations existantes (projections d'un projet jetable pré-installé en v1) ; packages multifichiers (`graphify` 10 fichiers, `workstation-setup` 19) ; permissions inter-utilisateurs ; rollback par réactivation puis par restauration ; mesure des durées. Critère : P3 entièrement vert, rollback vérifié.

**Non lancée** : la copie représentative n'existe pas.
