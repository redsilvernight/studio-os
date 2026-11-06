# P0 — conception avant implémentation

Référence : `dev`, `d5912008bf8847835d454d3af5083a779909754c` (04/11/2026).
Baseline exhaustive : `P0-BASELINE.json`. Les douze fichiers modifiés, les
rapports et la bibliothèque non suivis préexistants restent intacts. Aucun fichier
source P0 visé n'était modifié. Aucun commit, push ou accès mutable de production.

## Diagnostic et invariants

Le handoff appelle sync puis acquitte `next_cursor` avant de finir la session.
La réponse compacte retire les items, l'idempotence mémorise cette réponse et
le successeur hérite de ce curseur : le contenu peut disparaître du parcours
de récupération normal même si l'événement reste dans PostgreSQL.
Un signal ciblant une session est également filtré quand le successeur change
d'identité de session. Les événements métier sont des références récupérables
dans les ressources ; la coordination contient du texte et des références dans
le journal. `prepare_context` ne remplace pas leur livraison.

Invariants : livraison au moins une fois récupérable, ack explicite après
traitement, déduplication consommateur par `event_id`, aucune promesse exactly-once.
Le dernier événement disponible, présenté, traité et acquitté sont distincts.
Les budgets limitent la présentation, jamais le droit de récupérer les items.
Les curseurs persistants doivent être monotones et une version de tâche ne
doit permettre qu'une seule écriture concurrente acceptée.

## Choix comparés

1. Retirer l'auto-ack du handoff : utilise immédiatement la primitive existante
   `sync(ack=...)`, conserve signatures, compaction et réponse idempotente.
2. Ajouter des endpoints fetch/ack : distinction utile mais déjà présente dans
   sync ; API supplémentaire inutile pour P0.
3. Ajouter une boîte de reprise : duplication du journal PostgreSQL, migration
   et rétention supplémentaires sans nécessité démontrée.

Solution retenue : (1), avec récupération des signaux non acquittés adressés
aux sessions terminées de la même tâche, contrôlée par les autorisations du
sync existant. Le handoff propage seulement le curseur explicitement acquitté.
Le successeur appelle start_work puis sync sans ack ; après déduplication et
traitement durable, il acquitte le `next_cursor` effectivement reçu.
Pour une tâche terminée non réouvrable, le sync stateless agent_id+task_id et
ack explicite depuis le curseur connu permet la récupération.

## Concurrence et compatibilité

Reproduire les courses PostgreSQL avant de modifier tâches et curseurs.
Réutiliser le verrou de ligne déjà présent dans claim/release pour update_task
si la course est confirmée ; UPDATE/GREATEST pour les curseurs si confirmé.
Aucune nouvelle table ni migration présumée nécessaire. Les champs publics,
statuts HTTP, clés et profils restent identiques. Le sens du bloc final sync
est corrigé : livré potentiellement, jamais implicitement consommé. Les clients
peuvent recevoir des doublons, conformément à la sémantique au moins une fois.
Les nouvelles réponses compactes doivent signaler les items en attente.
Les réponses idempotentes anciennes restent rejouées telles qu'enregistrées ;
les curseurs déjà avancés avant déploiement ne peuvent pas être réparés sans
relecture explicite du journal (sync stateless depuis 0).

## Limites

La déduplication des effets consommateur reste sa responsabilité. Un ack
arbitraire envoyé par un client peut volontairement sauter du contenu ; P0 ne
crée pas de reçu signé. Les composites gardent plusieurs commits, et le
lease/fencing idempotent général appartient à P2. Une panne entre commits peut
produire des effets partiels à réconcilier, mais ne doit pas acquitter un signal
invisible. Un signal dépassant le budget nécessite un sync avec budget accru.
Les événements non encore commités malgré un seq inférieur à un watermark
restent une limite distincte du journal à documenter, sans garantie globale
de livraison sous réordonnancement des commits.

## Ajustements démontrés pendant la validation

Le scan tronqué pouvait rester bloqué sur une page d'événements non pertinents.
Il propose désormais leur dernier seq comme progression acquittable, sans
modifier les réponses hors scan tronqué. Reproduction : `resync-before.log`.
La revue a aussi démontré qu'une autre session vivante pouvait acquitter
au-delà d'un signal ciblé non reçu : un floor retient désormais le curseur
avant tout signal dirigé non acquitté d'une autre session de la tâche, avant
même le filtre d'exclusion du propre émetteur. Son texte reste caché tant que
la cible vit ; acquittement ou fin de cible débloque la progression.

La correction modifie un sens documenté : version contractuelle API **5**,
Event **1** inchangé. La matrice de compatibilité classe l'évolution
`API_BREAKING` et demande la mise à jour de l'interprétation N-1, sans ajouter
de champ obligatoire ni refuser les requêtes historiques. Les warnings MCP
documentés deviennent `*_pending`, avec un champ indicatif `recovery` optionnel.
La Decision serveur sera enregistrée lors d'une opération ultérieure autorisée;
la justification et les sources sont conservées ici entre-temps.
