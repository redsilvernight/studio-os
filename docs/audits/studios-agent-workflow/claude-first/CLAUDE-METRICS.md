# Claude First — mesures

## Taille des instructions et configurations locales

Mesures en caractères lues sur le poste le 2026-11-05. `~tokens` est une approximation `caractères / 4`, pas un comptage du tokenizer Claude.

| Fichier | Caractères | Chargement attendu |
|---|---:|---|
| `~/.claude/CLAUDE.md` | 828 | Instructions utilisateur |
| `~/.claude/rules/studio-protocol.md` | 1 553 | Règle globale, sans portée de chemin |
| `CLAUDE.md` du projet | 1 105 | Instructions projet; importe le protocole canonique |
| `.agents/rules/studio-protocol.md` importé | 1 248 | Règle projet |
| **Total statique permanent ci-dessus** | **4 734 (~1 184 tokens)** | Hors prompts système, messages, tool schemas et cache |
| `.claude/skills/studio-task/SKILL.md` | 6 138 | Sur invocation/pertinence, pas en permanence |
| `AGENTS.md` | 4 031 | Claude Code le traite comme source alternative; avec un `CLAUDE.md` présent, sa politique d'instructions par défaut ne le charge pas |
| `~/.claude/settings.json` | 13 047 | Configuration, permissions et hooks; ce n'est pas un bloc d'instructions |
| `.claude/settings.json` | 718 | Hooks projet `PreToolUse` / `PostToolUse` |
| `~/.claude.json` | 106 088 | État de compte/MCP/projets; ne pas compter comme prompt |
| `claude_desktop_config.json` | 8 119 | Préférences Desktop; ne pas compter comme prompt |

Les comportements exacts de chargement doivent encore être vérifiés par `/memory`, `/status` ou `InstructionsLoaded` dans une session native. La documentation Claude Code confirme que les instructions user/projet, imports `@`, règles et skills ont des chargements distincts ([mémoire Claude Code](https://code.claude.com/docs/en/memory)).

## Outils MCP, appels et latence

| Mesure | Résultat |
|---|---|
| Outils `session` déclarés dans le code actuel | 29 |
| Outils du transport stdio observés historiquement en P1.5 | 63 |
| Outils réellement listés par le Claude Code courant | Aucun; les six connexions configurées ont échoué |
| Outils réellement listés dans Claude Desktop | Non mesurés |
| Appels MCP de scénarios E2E Claude cette mission | 0 résultat exploitable |
| Latence de réponse du prompt CLI readonly | Sans réponse exploitable après ~150 s; interruption |
| Tokens entrée/sortie, cache ou coût par scénario | Non disponibles |

Aucun gain de tokens n'est revendiqué; aucune baseline comparable de requêtes modèles n'a été obtenue.
