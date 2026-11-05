# P1 — architecture retenue

`.agents/` reste la source des règles et missions projet. Le propriétaire logiciel est studio-client adapters ; adapters sync génère règles et trois entrées de cycle, adapters export projette les agents. rules sync reste un alias compatible du même code. Bootstrap et adapters check utilisent la même fonction pure de migration, sans moteur MCP parallèle.

## Migration contrôlée

merge_agents_rules accepte un bloc propre, ou les blocs hérités dont le contenu correspond exactement au rendu historique des règles canoniques. Il remplace tous les spans reconnus par un seul bloc, conserve les textes hors spans, accepte l'absence de bloc et migre une copie orpheline exacte. Marqueurs inconnus, imbriqués, déséquilibrés ou copie héritée modifiée : refus avant écriture. Le cas orphelin exact suivi d'un second titre ambigu est également refusé (finding indépendant corrigé). Les seuls sauts de ligne excédentaires supprimés sont en suffixe vide ; le texte utilisateur reste conservé. Sauvegardes locales avant remplacement.

Les règles à applies_to restent complètes dans .agents et dans les projections paths de Claude ; AGENTS ne contient que leur index et le protocole. Codex/OpenCode doivent lire la règle à la demande avant d'éditer un chemin correspondant : aucune activation paths universelle n'est promise. Deux phrases d'amorçage hors bloc AGENTS et une dans CLAUDE ont été corrigées explicitement pour référencer le mode du protocole, sans les faire passer pour une migration automatique de texte utilisateur.

Le synchroniseur personnel externe a été identifié, ainsi que sa copie inverse des agents/skills projet. personal-sync.patch introduit un garde pour les projets .agents, conserve la synchronisation globale personnelle. Il n'est pas appliqué. Tant qu'il reste actif, la réintroduction est possible. Six TOML Codex préexistants sont intacts ; candidats et hashes permettent une revue avant accord. Aucun contournement du check pour afficher du vert.

## Cycle unique et spécialisations

studio-task porte le cycle commun. studio-context et studio-handoff gardent noms/déclencheurs comme entrées compatibles, sans cycle dupliqué. Entrée mutable suivie : un démarrage lié à la tâche, contexte et sync initiaux réutilisés. Recherche préalable sans task_id autorisée sans prétendre qu'une session a été créée. Observation stricte : prepare_context et lectures, aucune mutation. Reprise et rafraîchissement distinguent rejeu idempotent et nouvel état ; known_ids seulement si le texte correspondant est conservé.

La synchronisation a lieu aux frontières. Les signaux sont dédupliqués par coordination.event_id, traités durablement, puis acquittés au curseur sûr. Les notifications compactes ordinaires ont seq, pas de event_id racine inventé. Le handoff P0 ne fait pas d'auto-ack ; overflow/resync nécessitent récupération ciblée. Un signal redélivré est attendu, aucune garantie exactly-once. Claims : avertissements/TTL, jamais verrou Git ; lots partiels à réconcilier.

roles.md spécialise orchestrateur, développeur, auditeur, hotfix, documentation et validation sans six nouveaux skills. Les six spécialistes existants restent edit_policy deny ; les procédures spécialisées ne leur confèrent pas de mutations. Contrats, migrations, OpenAPI, offline, décision et Graphify restent disponibles à la demande. Délégation seulement pour valeur indépendante identifiable ; intégration et validation globale restent au principal.

## Preuves et compatibilité

completion.md décrit le schéma réel CompletionEvidence/check_completion, la preuve par nature et les cas partiels. Toute tâche suivie déclarée terminée exige des preuves ; aucune obligation serveur nouvelle n'est ajoutée. Échecs obligatoires, révision non versionnée ou gate restant : checkpoint, pas completed. Findings d'audit distincts de la validation du livrable. Implémenté, testé, intégré et déployé restent séparés. Futur enforcement recommandé par capacité négociée, avertissement, période de migration et versionnement ; pas d'implémentation P2.

Les hooks et permissions Claude, les configs/bindings préexistants et credentials sont conservés. Profil session recommandé aux agents courants, admin pour un besoin précis ; ce n'est pas un contrôle d'autorisation. Les signatures locales sont confrontées aux métadonnées connectées ; verbose local n'est jamais présumé disponible à distance. Connexion actuelle à 63 noms et version distante non établie.
