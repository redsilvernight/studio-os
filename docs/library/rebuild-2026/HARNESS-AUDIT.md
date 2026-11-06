# Audit des harnais — 5 novembre 2026

## Résumé

Les trois harnais consomment un protocole partagé, mais les preuves disponibles ne permettent pas de les déclarer équivalents ni tous prêts. Les projections sont vérifiées; le chargement et le comportement natifs restent partiellement non vérifiés.

| Harnais | Sources / configuration | Rules, skills, agents, hooks | MCP et délégation | Verdict et limites |
|---|---|---|---|---|
| Claude Code | Sources canoniques `.agents/`; projection `.claude/`; `CLAUDE.md`; fichiers globaux et projet selon l’audit Claude First. | Le synchroniseur génère rules/skills/agents. Hooks Claude Code existent dans le projet. Le catalogue contient des hooks versionnés avec consentement par machine. | Audit Round 2: MCP Studi’OS connecté dans Claude Code, lectures réussies. `postgres-test` en erreur `CONNECTION_CLOSED`. Délégation via agents et OpenCode Dispatch selon la demande. | `CLAUDE_NOT_READY`: fenêtre Claude Desktop présente, mais sa capture d’état a expiré avant lecture des Connectors; le scénario de cycle complet n’a pas été lancé sur serveur isolé. Certaines instructions réellement chargées ne sont pas prouvées. Aucun fichier personnel n’a été modifié durant cette session. |
| Codex | `AGENTS.md` et `.codex/`; source canonique sous `.agents/`. L’application Codex est aussi apparue dans l’inventaire local; les projections sont déjà modifiées dans le worktree. | La dernière génération connue a produit des projections cohérentes. Une règle récente réduit `AGENTS.md` et référence les rules ciblées; le check local actuel ne mesure que la cohérence des adaptateurs (35/0). | Dans cette session, MCP Studio OS et Local AI Hub répondent effectivement. Le dispatch d’équipe est disponible comme outil séparé. | Connectivité vérifiée pour cette session. Pas de test de chaque CLI/config personnelle, de sandbox effective dans un nouveau worktree ni de chargement effectif de chaque règle/skill. |
| OpenCode | `.opencode/`, `opencode.json`; sources `.agents/`. Projections préexistantes dans le worktree. Aucun processus/fenêtre OpenCode native n’a été retourné par l’inventaire d’applications de cette session. | Les skills et agents sont générés; les hooks ne sont pas uniformes avec Claude. Hook versionné non représentable par le harnais doit être ignoré et signalé, jamais approximé (DEC-0194). | Dispatch OpenCode via MCP, workers dans des worktrees. L’utilisateur demande le mode équipe uniquement. | P1.6 `NOT_READY`: deux de trois runs readonly ont encore appelé `start_work`; exécution réelle des profils/modèles et visualiseur Team non vérifiés dans ce passage. Aucune nouvelle délégation lancée. |

## Modèle de configuration et propriété

- `.agents/` est la source projet canonique; le client Studio OS possède les projections gérées.
- `.claude/`, `.codex/`, `.opencode/`, `AGENTS.md`, `CLAUDE.md` et `opencode.json` sont des sorties ou configurations propres aux runtimes; ne pas les éditer à la main lorsqu’elles sont générées.
- Hooks personnalisés conservés localement et ceux de la Library doivent être fusionnés sans écraser les hooks non gérés. Les événements non pris en charge doivent produire un avertissement explicite.
- La Library contient des définitions personnelles pour les rules, skills, agents, profils modèle et hooks; les sélecteurs personnels restent distincts du Core partagé.

## Doublons et contradictions identifiés

| Constat | Preuve | Traitement |
|---|---|---|
| Même protocole exprimé dans plusieurs fichiers projet et projections | `.agents/rules/studio-protocol.md`, skills `studio-task`/`studio-context`/`studio-handoff`, projections et audits | Le protocole de novembre réduit les règles permanentes et délègue le cycle au skill canonique. Ne pas créer un second texte Core concurrent. |
| Risque de rules dupliquées ou chargées globalement dans `AGENTS.md` | Tâche active `[Adapters] AGENTS.md généré…`; règle `paths:` perdue si rule est inline | Continuer l’ajustement générateur déjà suivi séparément; ne pas incorporer cette tâche au Core sans résolution validée. |
| Readonly instruit mais pas toujours respecté par OpenCode | Rapport P1.6: appels `start_work` observés dans 2/3 runs | Bloquant pour un verdict OpenCode; la projection correcte n’est pas une preuve suffisante. |
| Connectivité Desktop supposée depuis Claude Code | Claude First Round 2 sépare clairement les deux surfaces | Garder Desktop non certifié jusqu’à preuve dans Settings → Connectors et appel natif. |
| Hooks différents selon runtime | DEC-0194 et architecture `AGENT-WORKFLOW.md` | Conserver les adaptateurs spécifiques; aucun objectif d’uniformité artificielle. |

## Scénarios natifs encore à obtenir

1. Codex CLI et Desktop: démarrage readonly sur dépôt suivi et non suivi; prouver l’absence de session/claim/sync/handoff.
2. OpenCode CLI: readonly; confirmer aucun `start_work`, avec journal réel du job et état Studio OS inchangé.
3. Tous les harnais: cycle tracked en base isolée — start, sync/déduplication, traitement durable, ack, handoff et récupération stateless.
4. Vérifier les fichiers et versions réellement chargés par chaque runtime, permissions et sandbox; comparer les modèles annoncés au modèle effectif sans exposer les credentials.
5. Hook: vérifier consentement par empreinte, désactivation et absence d’écrasement des hooks non gérés.

## Décision

Un Core commun peut fournir rules, skills et définitions neutres, mais l’installation doit rester portée par des adaptateurs par runtime. Les capacités personnelles doivent être séparées par scope et activation explicite. Aucun hook ni profil modèle ne doit être supposé portable par simple projection.

