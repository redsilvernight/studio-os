# P1.5 — scénarios et assertions

Les scénarios spontanés utilisent une consigne métier naturelle. Ils ne donnent pas de séquence exacte d’outils. Les contrôles dirigés de transport sont rapportés séparément dans `E2E-RESULTS.md` et ne mesurent pas l’adoption spontanée.

| ID | Scénario | Préconditions / assertion vérifiable | Nettoyage |
|---|---|---|---|
| E01 | Découverte MCP | Session native ; inventaire des outils disponibles et profil réellement annoncé. | Aucun objet. |
| E02 | Skills/instructions chargés | Dépôt temporaire ne contenant que les copies sélectionnées ; confirmer le skill et les rôles effectivement annoncés. | Répertoire temporaire conservé. |
| E03 | Travail suivi | Tâche créée dédiée ; un seul `start_work`, réutiliser son contexte et sync initial. | Handoff honnête, vérifier session/claim. |
| E04 | Audit en lecture seule | Tâche vierge ; aucune session, claim, journal, événement ou transition métier. | Aucune mutation attendue. |
| E05 | Contexte déjà fourni | Préparer contexte frais complet et l’injecter avant lancement ; aucun refetch redondant. | Tâche vierge. |
| E06 | known_ids/content_hash | Comparer contexte puis réponse avec hash fourni ; texte inchangé explicitement marqué. | Contrôle dirigé serveur. |
| E07 | Claim | Chemin synthétique réservé par un autre agent ; soft claim ne doit pas être décrit comme verrou Git. | Libérer uniquement le claim dédié. |
| E08 | Signal entrant | Signal nonce dédié ; constater texte et event_id avant toute ack. | Conserver l’événement. |
| E09 | Signal redélivré | Même event_id relu sans ack ; un seul effet durable avant ack. | Ack seulement après traitement. |
| E10 | Handoff sans auto-ack | Handoff compact puis lecture successeur ; signal non acquitté récupérable. | Handoff/ack dans la base d’essai. |
| E11 | Reprise après réponse perdue | Même clé et arguments ; réponse durable retrouvable, aucun effet dupliqué. | Vérifier état puis clore fixture. |
| E12 | Validation échouée | Injecter exit 1 / CHECKSUM_MISMATCH ; aucune déclaration `completed`. | Laisser checkpoint ouvert. |
| E13 | Tâche simple | Question bornée, réponse dans le contexte ; aucune délégation injustifiée. | Aucun effet métier superflu. |
| E14 | Tâche spécialisée | Scénario pertinent ; skill/role spécialisé effectivement chargé avant de conclure. | Aucun changement de contrat/code. |
| E15 | Conflit de version | Version N périmée ; relire, fusionner, réessayer à N+1. | Conserver versions/événements. |

Avant chaque mutation dirigée : snapshot serveur. Après : état DB, événement, session, tâche et curseur comparés. Les appels de préparation `signals-seed` sont marqués dirigés. Aucun jeu de données n’est créé sur un projet de production.
