# P0 — résultat autonome

**P0 terminé et validé localement le 04/11/2026. Non commité, non intégré,
non déployé. Aucun changement de production.**

| Sous-phase | État | Preuve | Risque résiduel |
|---|---|---|---|
| P0.1 — Handoff | Corrigé et testé | Récupération du texte après réponse compacte/perdue, retry, succession, limites et interruptions; race multi-session reproduite puis corrigée | Déduplication des effets consommateur requise; curseurs historiques non rembobinés |
| P0.2 — Versions tâches | Course reproduite puis corrigée | Avant : 3 échecs, deux writes acceptés; après : 3 succès, un seul 200, autre409, versionN+1 et un événement | Le verrou sérialise les mises à jour de la même ligne; pas de benchmark de charge |
| P0.3 — Curseurs | Régression reproduite puis corrigée | Avant sync :2 échecs/4 succès, 20→10; après :15 tests sync/handoff réussis, deux ordres, NULL, rollback/retry | Un ack arbitraire peut toujours sauter du contenu; confiance dans l'ack client inchangée |

## Garanties prouvées

**183 tests ciblés réussis**, aucun ignoré ou en échec au run final PostgreSQL
isolé; Ruff réussi, mypy9 fichiers réussi. Les nouveaux tests démontrent la
livraison récupérable des signaux commités dans les scénarios P0, le maintien
des signaux réservés à une autre session, l'absence d'auto-ack au handoff, les
versions de tâche atomiques et les deux curseurs monotones. Ils vérifient le
contenu, pas uniquement les codes de réponse. La revue indépendante a trouvé
un défaut supplémentaire qui a été reproduit, corrigé et testé.

## Procédure de récupération

Le successeur démarre via start_work, puis sync sans ack s'il a perdu la réponse
initiale. Il déduplique les effets par event_id, traite durablement le contenu,
puis envoie le next_cursor retourné comme ack. Il continue tant que resync ou
overflow signalent des items à récupérer; un budget insuffisant peut être
augmenté. Un overflow de coordination réservé à une cible encore vivante attend
son acquittement ou sa clôture. Pour une tâche terminée, sync stateless avec
agent_id+task_id depuis le curseur acquitté permet de relire sans la rouvrir.

## Compatibilité et limites

Version API contractuelle **5**, transport `/api/v1`, Event1 inchangé.
Révision comportementale explicite : handoff.sync non acquitté, warnings
pending, recovery optionnel. Pas de changement de signature, champ requis,
autorisation, profil ou suppression d'outil. La politique API_BREAKING exige
la mise à jour de l'interprétation N-1; les requêtes anciennes restent acceptées.
Les réponses idempotentes historiques restent telles qu'enregistrées.

Pas d'exactly-once distribuée promise. L'ordre seq/commit du journal, les
transactions non encore visibles lors d'un scan, le lease/fencing idempotent
général et tous les interleavings possibles ne sont pas prouvés par P0. Les
composites gardent plusieurs commits : retry/réconciliation restent nécessaires.
La publication tardive d'un seq inférieur à un ack est une limite du journal
préexistante, distincte de la consommation invisible corrigée ici.
Pas de test réel de panne réseau, MinIO, CI ou déploiement. Les snapshots
dashboard ne diffèrent du runtime que sur deux descriptions, pas sur les formes;
leur génération a été différée conformément à la consigne.

## État Git et environnement

Branche `dev`, HEAD `d5912008bf8847835d454d3af5083a779909754c`, index vide.
Trois worktrees préexistants conservés, sans nouveau worktree Git nécessaire :
les sources P0 étaient propres. Les **61 fichiers préexistants inventoriés**
ont les mêmes SHA-256 après les changements (`P0-PRESERVATION.json`), dont les
12 fichiers déjà modifiés, les six dérives Codex, les audits et la bibliothèque
non suivis. Aucun reset, clean, restauration, régénération ou suppression.
Les 19 chemins de code/tests/contrats modifiés sont listés dans
`P0-IMPLEMENTATION.md`, avec les quatre rapports et traces ajoutés.

PostgreSQL de validation neuf : rôle p0_runner, base studio_p0_test,
127.0.0.1:55439, données dans .worktrees/p0-runtime-20261104. Aucune base
préexistante ni ressource MinIO touchée. Les données temporaires créées restent
identifiées pour reprise ; arrêt de l'instance consigné dans le journal dédié.

Auto-update Graphify exécuté une fois via scripts/graphify-studio.ps1 sur les
17 chemins Python P0 exacts (sources et tests), AST uniquement, **0 token LLM**.
Résultat : 19 999 nœuds, 58 163 arêtes, 863 communautés dans le graphe central.
Le journal signale trois métadonnées source_file manquantes hors périmètre P0
et des noms de communautés à rafraîchir; aucune inférence ni relabellisation
LLM lancée. Pas d'extraction sémantique des rapports Markdown. Instance
PostgreSQL temporaire arrêtée avec succès, données conservées.

## Suite autorisable et rapports

P1 non commencé. Avant intégration ultérieure : enregistrement de la Decision
canonique de livraison/compatibilité, génération documentaire des deux schémas
OpenAPI si autorisée, suite complète une seule fois puis CI selon le cycle du
dépôt. Aucun de ces effets distants n'est annoncé comme réalisé.

- `P0-DESIGN.md` : choix avant implémentation, invariants et ajustements démontrés.
- `P0-IMPLEMENTATION.md` : liste exhaustive des chemins, contrats et écarts.
- `P0-TEST-REPORT.md` : environnement, commandes, échecs avant/succès après,
  exigences et tests non exécutés.
- `P0-FINAL.md` : présente synthèse autonome.
