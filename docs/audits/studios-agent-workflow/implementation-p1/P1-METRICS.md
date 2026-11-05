# P1 — mesures avant/après

Mesures de fichiers, pas tokens ni latence. Caractères normalisés LF ; octets UTF-8 réels. Baseline : baseline.json, baseline-files pour les chemins sales, HEAD fixé pour les sources propres. Détails reproductibles : metrics.json.

| Périmètre | Octets avant → après | Caractères LF avant → après |
|---|---:|---:|
| `AGENTS.md` | 32605 → 3869 | 32383 → 3774 |
| `.agents/rules/studio-protocol.md` | 980 → 1037 | 978 → 1035 |
| `.agents/skills/studio-task/SKILL.md` | 3213 → 5420 | 3199 → 5418 |
| `.agents/skills/studio-context/SKILL.md` | 2225 → 1438 | 2203 → 1436 |
| `.agents/skills/studio-handoff/SKILL.md` | 3449 → 1243 | 3445 → 1241 |
| `.claude/agents` | 237485 → 243148 | 236870 → 238577 |
| `.opencode/agents` | 237310 → 242979 | 236695 → 238402 |
| `.codex/agents` | 237411 → 237411 | 236796 → 236796 |

AGENTS.md : deux blocs reconnus deviennent un. Les sept règles à portée, auparavant copiées deux fois (14 corps permanents), deviennent sept références de chemins ; aucun corps spécialisé permanent. Le protocole court est inliné une fois. Bootstrap Codex comparable : ancien AGENTS + protocole externe (33 585 octets), nouveau AGENTS incluant protocole (voir table) ; pas de double comptage du protocole actuel.

Les trois entrées SKILL passent de trois procédures recouvrantes à un cycle et deux alias compatibles. Les références completion.md/roles.md ajoutent 4 951 octets conditionnels : le corpus disponible grossit, il ne faut pas annoncer une baisse globale de tous les prompts. Les projections de rôles Claude/OpenCode grossissent aussi ; le rendu historique inline des spécialisations est conservé. Les six TOML protégés restent strictement identiques.

| Scénario | Prescription avant | Prescription après | Nature de la mesure |
|---|---|---|---|
| Travail suivi minimal, hors claims/sync utiles | start_work + log_ai_work + handoff : 3 | start_work + handoff : 2 | Structure des instructions, pas sessions observées |
| Contexte initial déjà disponible | prepare_context supplémentaire possible par consignes contradictoires | 0 appel supplémentaire imposé | Redondance évitée, fréquence non mesurée |
| Audit strict lecture seule | prepare_context concurrencé par consigne start_work | prepare_context : 1 ; 0 mutation | Prescription + oracle simulé |
| Successeur sans historique | prepare_context puis start possibles | 1 start pour nouvelle unité mutable ; contenu nécessaire rechargé | Prescription, pas benchmark |
| Refresh avec texte conservé | mécanisme serveur existant, non enseigné | 1 prepare_context avec known_ids/content_hash retenus | Même nombre d'appels ; volume économisé non mesuré |
| Découverte MCP | connexion actuelle : 63 noms | session local : 29 ; admin : 63 | Config non changée ; pas gain live annoncé |

Cohérence : 35 éléments contrôlés sur candidats isolés sans dérive ; racine : exactement six drifts Codex préexistants. Aucun token converti depuis des caractères, aucune promesse de gain de coût/latence. Essai Claude : zéro token car échec avant appel modèle (harness-trials.md).
