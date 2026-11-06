# Claude First — baseline

Date d'observation : 2026-11-05 (Europe/Paris). Dépôt : `Studi'os`.

## Git et protection des changements

- Branche `dev`, HEAD `d5912008bf8847835d454d3af5083a779909754c`, en retard de 9 commits sur `origin/dev`.
- Le worktree était déjà fortement modifié avant cette mission : sources canoniques `.agents/`, projections Claude/Codex/OpenCode, contrats et services MCP/API, tests, docs et `library/`. Ces changements n'ont pas été réécrits ni nettoyés. Les seuls nouveaux fichiers de cette mission sont les sept rapports de `claude-first/`.
- Worktrees présents : dépôt courant, un worktree temporaire Claude détaché et `codex/bina-monitor-caddy`. Aucun commit, push, merge ou déploiement effectué.
- La tâche Studio OS « Claude First — audit E2E de Claude Desktop et Claude Code » a été créée et démarrée pour suivre la mission. Aucun claim de ressource n'a été créé.

## Outils locaux observés

| Élément | Observation |
|---|---|
| Claude Code CLI | `2.1.316`, `C:\Users\redsi\.local\bin\claude.exe` |
| Auth Claude Code | `claude auth status --json` indique `loggedIn=true`; aucune donnée de compte n'a été exposée |
| Claude Desktop | Une fenêtre Claude apparaît dans l'inventaire des applications; version exacte et état de connexion non établis |
| Configuration Desktop | `C:\Users\redsi\AppData\Roaming\Claude\claude_desktop_config.json`, 8 119 octets; clés racine `coworkUserFilesPath` et `preferences`, aucune clé `mcpServers` |
| Logs Desktop | `mcp.log` vide; `main.log` et `claude.ai-web.log` remontent au 21 août 2026, donc ne décrivent pas la session actuelle |
| Claude Code MCP global | `~/.claude.json` contient `studio-os` de type HTTP, ainsi que `obsidian-memory`, `opencode-dispatch` et `local-ai-hub` |
| Claude Code MCP projet | Deux clés de projet désignent le même chemin avec séparateurs différents. L'une déclare `opencode-dispatch`, `context7`, `postgres-test`; l'autre n'a pas de serveur projet. Aucune entrée projet `studio-os` |
| Connectivité CLI MCP | `claude mcp list` a signalé `Failed` pour les six noms distincts visibles dans les scopes global et projet |
| Configuration MCP de dépôt | Aucun `.mcp.json` à la racine |
| Dépendances de test | `STUDIO_TEST_DATABASE_URL` absent; le client Docker a reçu `permission denied` sur le moteur; l'accès au Service Control Manager a été refusé. Aucun test dépendant de PostgreSQL n'a été lancé |

La configuration personnelle n'a pas été modifiée. Les valeurs d'URL, d'en-têtes, de credentials et de compte sont volontairement omises.

## Essai CLI interrompu

Une requête naturelle de lecture seule a été lancée dans Claude Code avec `--permission-mode plan`. Après environ 150 secondes sans réponse de modèle, elle a été interrompue (code de sortie 1). Seuls deux avertissements concernant des règles de permission personnelles préexistantes ont été affichés. Cet essai ne prouve ni le chargement effectif des instructions, ni l'appel d'un outil MCP, ni un résultat métier.

## Sources et limites

- Les versions, configurations et statuts ci-dessus proviennent de commandes locales et de métadonnées, pas d'une supposition sur le compte Claude Desktop.
- Le contrôle d'interface a sélectionné une fenêtre annoncée comme Claude mais a rendu l'écran Codex. Aucun réglage Desktop n'a été lu ou modifié.
- PostgreSQL, Docker et MinIO n'ont pas été démarrés. Les essais antérieurs sur une base isolée sont cités dans les rapports P0/P1.6; ils ne valent pas une validation exécutée dans cette mission.
