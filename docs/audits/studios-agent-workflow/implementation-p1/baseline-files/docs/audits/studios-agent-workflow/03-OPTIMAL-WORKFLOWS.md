# Workflows optimaux proposés

Propositions uniquement, aucune appliquée. Elles réutilisent les composites, le batch de claims, les signaux, les previews et les contrats existants. Voir [02](02-CURRENT-WORKFLOWS.md) pour les preuves et [01](01-MCP-INVENTORY.md) pour les signatures exactes.

## Tronc commun

### Entrée et démarrage

| Situation | Séquence minimale | Information à conserver |
|---|---|---|
| Projet et identité connus, tâche attribuée | start_work une fois, avec objectif ciblé et chemins utiles | task/version, session/id, contexte, sync/next_cursor, omissions, clé de replay |
| Projet inconnu | get_projects puis branche appropriée | UUID projet ; ne pas redécouvrir ensuite |
| Identité technique absente | resolve_agent_identity selon identité stable du harnais, puis démarrage | agent_id et stable_key ; ne pas confondre resolve_agent |
| Travail à choisir, writer autorisé | start_work sans task_id, choisir un candidat puis start_work avec tâche | candidats déjà retournés ; aucun get_active_tasks systématique |
| Audit/diagnostic imposé en lecture seule | prepare_context sans claim/session ; lectures ciblées | sources et limites ; aucune clôture MCP mutante |
| Reprise après perte de contexte | start_work même tâche/couple si travail suivi ; prepare_context si observation | état serveur frais ; ancien résultat idempotent n'est pas un refresh |

Traiter le sync initial sans le réclamer une seconde fois par défaut. `max_chars` borne la réponse sérialisée pour start_work/sync MCP locaux ; prepare_context conserve un budget de texte sélectionné. Ce n’est pas un budget de tokens. Ne pas imposer 3 000 à tous les cas : si le contexte ou les items indispensables ont été retirés, une lecture ciblée supplémentaire est préférable à une supposition.

Sources : `services/api/src/studio_api/services/start_work.py:91-165`, `services/mcp/src/studio_mcp/tools/start_work.py:41-105`, `response_budget.py:51-63,141-157`.

### Exploration et plan

1. Lire les liens structurels et décisions acceptées pertinents ; considérer les correspondances lexicales comme des candidats.
2. Réutiliser les objets déjà reçus. Obtenir une définition par stable_key/version avec discover_definitions, ou résoudre le rôle par resolve_agent si nécessaire. Ne pas recharger le catalogue entier.

   Pour un refresh prepare_context, transmettre `known_ids={id: content_hash}` des éléments dont le contenu est encore disponible (maximum 100). Les références `unchanged=true` réutilisent ce cache ; un successeur sans historique omet ces hashes pour récupérer les textes. Ce mécanisme existe déjà, distinct de `sync(ack=...)` : aucun nouveau cache collectif ni nouvel outil nécessaire. Source : `services/mcp/src/studio_mcp/tools/context.py:33-66`, test `tests/mcp/test_prepare_context.py:464` non exécuté.
3. Hub pour localiser le symbole ; code_context pour la plage connue. Source/Git pour le comportement actuel. Graphify seulement pour une relation non résolue et avec vocabulaire attesté ; mémoire personnelle seulement pour un fait transversal utile.
4. Le plan reste dans les tâches/roadmap existantes. Créer une sous-tâche seulement si elle a un responsable, une sortie vérifiable et un besoin de suivi distinct.
5. Faire intervenir un spécialiste lorsque son verdict apporte une preuve indépendante ou tranche un risque réel. Transmettre un paquet borné, pas l'historique de l'orchestrateur.

### Exécution et synchronisation

Déclarer en un batch les chemins réellement partagés, avec TTL proportionné au travail. Lire les conflits puis convenir d'une répartition ; le soft lock n'interdit aucune écriture. Pour une zone isolée non partagée, ne pas revendiquer tout le dépôt « par sécurité ».

Synchroniser avant un changement partagé, après un signal pertinent ou à une frontière de travail. Conserver `next_cursor`, traiter les items, puis ack au prochain checkpoint. Ne jamais ack un item non traité. Éviter les ack parallèles sur une même session tant que la monotonie concurrente n'est pas prouvée.

Si la boucle dépasse le TTL, relire les claims actifs ; la signature centrale ne fournit pas un outil universel de heartbeat/renouvellement. Ne pas inventer `studio_renew_claim` : réutiliser la procédure existante de libération/réservation sous contrôle de concurrence, ou laisser l'orchestrateur réallouer. Une session active ne prouve pas qu'un claim reste valide.

`studio_coordinate` est conditionnel : heads_up si une autre tâche change de plan, question si une réponse est nécessaire, blocked_by avec références si dépendance réelle, handoff pour transfert. Un event_id stable appartient au signal ; il ne faut pas en modifier le contenu lors d'un retry. Le quota de 20 exclut le bavardage de progression.

### Validation et sortie

Conserver commande exacte, exit code, résultat, artefact/révision et limites. Distinguer implémenté, testé, intégré et déployé. Pour un travail suivi, passer `completion` même si le serveur l'autorise encore à être absent. Un échec de validation laisse la tâche ouverte ou bloquée, avec une prochaine action vérifiable.

Avant handoff, exécuter un dernier sync explicite et traiter ses items. Puis appeler handoff une fois avec clé stable, version courante, summary utile, fichiers, tests et preuves. Le défaut d'auto-ack du dernier sync serveur laisse une fenêtre résiduelle : en attente de correction, `verbose=true` peut être utilisé dès le premier handoff à risque **uniquement si la signature réellement connectée l'annonce**, sans modifier le payload au retry. La connexion de cet audit ne l'annonce pas, contrairement au checkout local : ne pas lui envoyer ce paramètre par supposition. Ce contournement ne garantit pas la livraison si la réponse se perd. Il ne doit pas devenir une inflation globale permanente.

En lecture seule, produire les artefacts et un checkpoint documentaire ; aucun handoff/session fictif pour satisfaire le protocole. C'est l'exception explicite demandée dans cet audit.

## Spécialisations par rôle

### 1. Orchestrateur

**Entrée :** objectif accepté, projet accessible, tâches/roadmap connues ou à inspecter. **Sortie :** critères globaux vérifiés, sorties intégrées selon les règles du dépôt, responsabilités résiduelles nommées.

1. Démarrer une seule unité suivie. Lire les candidats/roadmap déjà retournés.
2. Réutiliser les tâches existantes ; create_task uniquement pour une unité indépendante mesurable. Pour un lot issu d'une roadmap, préférer preview/apply d'hydratation plutôt qu'une série d'objets équivalents recréés à la main.
3. Définir propriétaire, critères, fichiers, commande et frontières d'intégration de chaque délégation. Lancer via les capacités du harnais ou le chemin de lancement produit adapté ; coordinate ne lance rien.
4. Attribuer des zones distinctes. Ne pas faire travailler plusieurs agents sur une même session ni attribuer artificiellement la même tâche réclamée à plusieurs couples.
5. Lire les résultats bornés et preuves. get_teammate_activity ou list_task_launches seulement si l'état d'exécution est nécessaire ; pas de polling global aveugle.
6. Répondre aux blocages, proposer les décisions durables, faire valider celles qui relèvent de l'admin.
7. Relire les changements intégrés et faire les validations globales requises une fois, puis handoff de l'unité.

**Nécessaires :** start_work, sync, handoff ; claims si zones partagées. **Conditionnels :** create/update_task, roadmap preview/apply, coordinate, resolve_agent, décisions, lancements. **À éviter :** six sous-agents par défaut, un nouveau document de plan doublant la roadmap, messages de progression par coordinate.

**Récupération :** enfant échoué → tâche de correction ciblée, pas clôture globale ; conflit de claim → séparation ou passation explicite ; décision en attente → état bloqué documenté, pas boucle d'attente permanente.

### 2. Agent développeur

**Entrée :** tâche bornée et critères. **Sortie :** changement minimal validé, versionné/intégré si requis, dossier de reprise exploitable.

1. Start_work avec tâche et objectif précis ; conserver version et sync.
2. Localiser cause et appelants ; lire tests et frontières touchées. Charger contract-change, migration ou offline-sync-testing seulement si déclencheur réel.
3. Claim batch des fichiers partagés, traiter les avertissements, implémenter la cause une fois dans le code commun.
4. Tests ciblés et vérifications de contrat appropriées ; suite complète seulement à la porte d'intégration du dépôt, sans répétition après chaque édition.
5. Décision durable si le choix contraint la suite ; jamais pour une note de travail temporaire.
6. Dernier sync traité, preuve code avec révision et checks, handoff.

**Nécessaires :** cycle commun. **Facultatifs :** definitions/resolve_agent, add_decision, coordination, outils locaux du Hub. **À éviter :** ancien claim_task/start_session, lecture complète de tous ADR, log_ai_work juste avant un handoff qui écrit le même journal.

**Erreurs :** test rouge → corriger ou checkpoint avec échec ; 409 → relire/fusionner, jamais écraser ; infra indisponible → nommer le contrôle manquant, pas déclarer la validation réussie.

### 3. Agent auditeur

**Entrée :** périmètre, livrables et règle d'écriture explicites. **Sortie :** rapports vérifiés, preuves sourcées, sévérité distincte du niveau de preuve, limites explicites.

1. Si lecture seule imposée, prepare_context puis lectures sans démarrage suivi. Si audit suivi expressément autorisé à écrire son état, cycle commun avec completion.kind=audit.
2. Construire inventaire par introspection/AST/comptages déterministes ; confronter documentation, code, exposition et tests.
3. Déléguer seulement des lectures indépendantes avec frontières précises. Ne pas demander des modifications automatiques pour « vérifier » une proposition.
4. Exécuter les validations pures après inspection de leurs fixtures/imports. Ne pas lancer xdist, migrations, services ou opérations réelles pour simuler une panne.
5. Rapporter les scénarios et les tests nécessaires en environnement isolé. Ne pas présenter une analyse de course comme un incident reproduit.
6. Vérifier existence des livrables, références, couverture de l'inventaire et Git avant restitution.

**Nécessaires :** prepare_context et lectures ciblées. **Facultatifs :** découverte des définitions, lecture vault projet/graphe local. **À éviter :** claim_resources, decisions, coordinate, sync avec session, handoff si l'autorisation ne couvre pas les mutations.

### 4. Agent correcteur / hotfix

**Entrée :** symptôme reproductible, périmètre et urgence. **Sortie :** cause corrigée et testée, risques résiduels nommés ; pas de déploiement implicite.

1. Start_work ciblé, lire incidents/claims déjà fournis et le seul handoff pertinent.
2. Reproduire ou isoler la cause ; Hub sur symbole/appelants, test de non-régression utile.
3. Claim des seuls fichiers nécessaires, correction partagée minimale, pas de refonte du workflow pendant le hotfix.
4. Tests du chemin fautif et voisins ; gardes de contrat/migration restent applicables malgré urgence.
5. Sync, preuve et handoff. Intégration/CI/déploiement suivent leurs autorisations réelles.

**Conditionnels :** coordinate pour prévenir les agents réellement impactés ; sync-debugger si replay/claims/transfert incertain. **À éviter :** catalogue complet, roadmap neuve, six rôles spécialisés sans risque identifié.

### 5. Agent documentation

**Entrée :** audience et source de vérité identifiées. **Sortie :** documentation cohérente, liens vérifiés, source canonique/projection distinguées.

1. Start_work si tâche suivie autorisée ; prepare_context si simple revue.
2. Lire le comportement exécutable, les décisions validées pertinentes et le routage documentaire.
3. Identifier propriétaire du contenu : .agents canonique, projections générées, export de décisions généré, bibliothèque versionnée. Ne pas éditer un dérivé pour corriger sa source.
4. Réserver les docs partagées si édition ; mettre à jour uniquement le périmètre demandé, régénérer par le mécanisme propriétaire si autorisé.
5. Vérifier liens, exemples de signatures et adapters check quand concerné. Relecture de contenu, pas tests DB par automatisme.
6. Handoff avec artefacts et checks d'audit/diagnostic si le changement consiste en revue, ou preuve de changement versionné selon les règles de la tâche. Ne pas inventer kind=documentation : l'enum actuel ne le contient pas.

**À éviter :** recopier le catalogue MCP dans chaque skill ; transcrire tout le vault dans le dépôt ; dupliquer les décisions exportées à la main.

### 6. Agent de validation

**Entrée :** changement, critères, diff/fichiers bornés, commande connue, environnement. **Sortie :** verdict indépendant étayé, échecs et limites ; pas une promotion automatique de statut.

1. Recevoir un paquet autonome ; prepare_context pour compléter les contraintes manquantes, pas l'historique du parent.
2. Vérifier les critères contre le diff et les frontières de confiance ; sélectionner tests au risque.
3. Exécuter les contrôles autorisés et consigner les exit codes ; distinguer test non exécuté et test passé.
4. Envoyer le verdict au responsable ; coordinate seulement si un changement de plan ou un blocage doit être persisté dans une session autorisée.
5. Le responsable intègre les preuves puis clôture. Le validateur ne ferme pas la session du développeur et ne transforme pas une auto-déclaration completion en approbation externe.

**Outils obligatoires :** lectures et commandes ciblées ; cycle suivi uniquement sur sa propre tâche si nécessaire. **Facultatifs :** rôles spécialisés contract-guardian, migration-reviewer, dashboard-a11y, studio-tester. **À éviter :** remonter tout contexte, réimplémenter les critères sous forme de tests miroir, marquer completed parce que l'outil l'accepte.

## Scénarios et chemins de récupération

| Scénario | Actuel et risque | Comportement recommandé | Outils / changement nécessaire |
|---|---|---|---|
| Agents indépendants | Claims de tâches sérialisés ; fichiers non isolés automatiquement | Tâches et sessions distinctes ; zones/worktrees si utiles | start_work, batch claims ; pas de refonte |
| Fichiers proches | Soft locks, recouvrement exact/dossier ; aucune interdiction Git | Déclarer un ancêtre commun si zone réellement partagée, négocier avant édition | claim_resources, sync, coordinate |
| Orchestrateur + développeurs | Signaux pull, pas attente/launch implicite | Suivi borné via harnais ou task launches réels, paquet de preuves | outils de lecture lancement/activité conditionnels |
| Attente décision | blocked_by ne suspend rien automatiquement | Nommer décideur, décision et prochain déclencheur ; reprendre après réponse réelle | add_decision, coordinate, sync aux frontières |
| Interruption | Commits partiels possibles | Conserver clé/payload ; relire l'état avant nouvelles écritures | start_work replay, get_task/claims |
| Reprise autre agent | Ancien claim peut refuser same-machine other-agent | Passation/libération explicite, nouvelle session et lecture NEXT | handoff puis start_work ; chemin privilégié de release à préserver |
| Modification concurrente | Sync filtre métier même machine ; risque CAS tâche | Git/source fraîche et signal local ; 409 relire/fusionner | sync/coordinate/get_task ; test CAS prioritaire |
| Validation échoue | Garde si completion fournie ; sinon clôture possible | Garder ouvert/bloqué, artefact échec distinct de validation du livrable | handoff sans completed ou update_task |
| Handoff incomplet | Replays partiellement convergents, dernier sync auto-ack | Réessayer même requête ; ne pas reconstruire anciennes primitives | handoff même clé ; correction livraison P0 |
| Session expirée | Présence dérivée, sync peut réactiver | Reprendre via start_work si travail durable ; ne pas traiter comme révocation | start_work ; préciser doc plutôt que casser API |
| MCP indisponible | Pas d'outbox général dans handlers | Travail local sûr/checkpoint ; retry borné et état vérifié au retour | service_unavailable vs panne transport ; pas faux succès |
| Réponse tronquée | Budget/overflow/resync, contexte parfois nul | Lecture ciblée ou budget ajusté ; ne pas ack contenu absent | prepare_context/sync, dedicated get_* |
| Timeout coordination | event_id replay retourne original | Même UUID et même signal ; si besoin différent, nouvel UUID | coordinate ; comparaison payload à décider |

Preuves : `services/api/src/studio_api/services/{tasks.py:215-225,claims.py:38-53,sync.py:233-304,sessions.py:305-340,coordination.py:82-97,idempotency.py:71-117,handoff.py:125-132}` ; tests présents listés dans 02 et FINAL-AUDIT. Aucun scénario réseau/multiagent réel n'a été exécuté pendant cet audit.
