# Analyse d'impact

Graphe construit à partir des dépendances déclarées dans les 3 manifestes cibles (45 arêtes, toutes résolues contre cible ∪ production). Les liens réels de production (`library_resource_links`), locks et installations ne sont pas lisibles en lecture seule : les risques ci-dessous sont **déduits des manifestes**, pas mesurés. Rien n'est inventé ; ce qui n'est pas connu est marqué `INCONNU`.

## Références entrantes principales (manifestes)

| Cible | Référencée par |
|---|---|
| `agent_definition` `reader`, `worker`, `verifier` | 4 workflows Core chacun |
| skill `graphify` (nouveau) | 4 agents Project (`contract-guardian`, `studio-architect`, `studio-tester`, `sync-debugger`) |
| rule `python-conventions` | 4 agents Project |
| profil `single-agent` | 3 agents Core |
| rules `contracts`, `database` | 3 agents Project chacune |
| rule `testing` (nouvelle) | `dashboard-a11y`, `migration-reviewer` |

Dépendances non résolues : **aucune** (45/45 résolues).

## Matrice d'impact

| Source | Opération | Références affectées | Risque | Stratégie | Vérification |
|---|---|---|---|---|---|
| rule `studio-protocol` v2→v3 | REPLACE | projections `.claude/rules`, `.codex`, `.opencode`, `AGENTS.md` ; skills `studio-*` ; installations locales ; locks sur v2 (INCONNU) | élevé (rule chargée à chaque session) | publier v3, activer seulement après répétition ; garder v2 | `rules sync`, `adapters check`, hash v3, lecture par les 3 runtimes |
| 6 rules Project v1→v2 | REPLACE | 3 à 4 agents Project chacune ; locks de projet possibles | moyen | publier puis activer par lot ; si un lock pointe v1, il reste valide (advisory) | `dependency-updates` par version, résolution d'un agent |
| 5 agents Project v1→v2 + `studio-tester` v2→v3 | REPLACE | adapters des 3 runtimes ; dépendances vers `graphify`, `testing` (nouveaux) | moyen | créer d'abord `graphify` et `testing`, puis agents | `adapters check`, résolution `studio_resolve_agent` |
| 4 skills Project v1→v2 | REPLACE | projections skills (multifichiers possibles) | moyen | synchro après activation ; dérive des auxiliaires contrôlée | `skills` status, hashes de fichiers |
| 6 agents `user` en doublon | DEPRECATE | résolutions par clé `user` ; projections locales du propriétaire | moyen | dépréciation seule, après publication/vérification des Core ; réversible par activation | résolution de chaque clé → version Core ; aucune installation orpheline |
| 4 hooks `user` | KEEP | aucun (non republiés) | faible | ne rien publier | aucun hook activé par la migration |
| 3 hooks Core | publication (déjà présents) | consentement et empreinte | moyen | pas d'activation implicite | `requires_consent` respecté |
| 7 nouvelles ressources | création | agents Project qui en dépendent | faible | publier avant les ressources qui les référencent | présence, hash, scope, owner |
| 60 `KEEP` | aucune opération | aucune | faible | comparer hashes en répétition ; écart → `REVIEW_REQUIRED` | hash prod = hash manifeste |

## Utilisateurs / projets / installations

- Un seul propriétaire et un seul projet visibles en lecture : Studio OS (`2a836038…`). Autres comptes, installations locales, locks projet et `runtime_bindings` : `INCONNU` (voir inventaire).
- Postes concernés connus : le poste principal et FLO-LAPTOP (projections locales) ; à régénérer après activation.
- Versions verrouillées : un lock (`resource_id`, `locked_version`) reste valide quand une nouvelle version est publiée ; la suppression de version est exclue, donc aucun lock ne peut casser.

## Points de vigilance

1. Ne jamais publier un agent avant les ressources dont il dépend.
2. L'activation de v3 de `studio-protocol` change le comportement de toutes les sessions : dernière étape, rollback immédiat disponible (réactiver v2).
3. Déprécier les copies `user` seulement quand la clé `studio` correspondante est vérifiée.
