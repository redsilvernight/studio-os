# Claude First — causes et preuves

## F01 — Desktop n'est pas démontré comme client Studi'OS

**Cause établie : manque de preuve d'exécution.** Le fichier de configuration local Desktop ne contient pas `mcpServers`, mais les connecteurs distants vivent dans le compte Claude Desktop et leur statut se consulte dans l'interface. L'inspection UI a rendu une fenêtre Codex malgré une sélection de fenêtre Claude; les journaux Desktop MCP sont vides ou datés du 21 août. On ne peut donc pas conclure à l'absence de connecteur ni à sa présence.

## F02 — Le protocole personnel et le protocole projet se contredisent

**Cause confirmée dans les fichiers présents.** `~/.claude/rules/studio-protocol.md` ordonne de commencer systématiquement par `studio_start_work`. Le protocole projet `.agents/rules/studio-protocol.md` et `AGENTS.md` donnent la priorité au mode readonly et prescrivent `studio_prepare_context` sans session, claim, sync ou handoff. La version courante de Claude Code charge les règles `~/.claude/rules/` pour tous les projets sans portée; `CLAUDE.md` importe en plus la règle projet. La documentation Anthropic précise que les consignes contradictoires peuvent être suivies arbitrairement. Le test Claude Code n'a pas retourné de trace d'instructions pour départager leur comportement effectif.

Une correction de cette contradiction toucherait le fichier personnel `~/.claude/rules/studio-protocol.md`. La mission interdit d'appliquer une modification de configuration personnelle sans autorisation explicite; un patch est préparé dans `CLAUDE-IMPLEMENTATION.md`, non appliqué.

## F03 — Le catalogue MCP actuel n'est pas atteignable depuis le CLI

**Échec observé.** `claude mcp list` a signalé `Failed` pour les six serveurs distincts configurés dans les scopes utilisateur et projet. Le compte Claude Code est pourtant signalé connecté. La cause réseau ou d'authentification précise n'est pas établie, et les valeurs sensibles n'ont pas été affichées. Aucun résultat ne permet de déterminer le nombre d'outils réellement annoncé par cette connexion.

## F04 — Écart de catalogue historique, portée actuelle inconnue

**Fait historique.** P1.5 a observé 63 outils sur un serveur stdio contre 29 attendus pour le profil `session`. Le code courant définit 29 outils `session`, `session` par défaut et `admin` comme surface complète. Le test historique ne suffit pas à établir le profil réellement sélectionné par une connexion Desktop ou HTTP aujourd'hui.

## F05 — Ack après handoff rejeté dans P1.5; réparation native non certifiée

P1.5 a observé Claude Code tenter `studio_sync(session_id=...)` après `studio_handoff`; la session fermée renvoyait `session_not_found`. P1.6 a clarifié l'ordre attendu : traiter durablement et ack les signaux reçus avant handoff; après fermeture, récupérer stateless avec `agent_id + task_id`, dédupliquer par `event_id` et avancer les curseurs retournés sans prétendre à un ack de session. Le test d'intégration dédié a réussi sur `studio_p16_test`, mais aucun nouveau cycle Claude natif n'a démontré cette correction.

## F06 — Inaccessibilité des dépendances isolées sur ce poste

Docker répond `permission denied`, le contrôle des services Windows est refusé et `STUDIO_TEST_DATABASE_URL` est absent. Aucun service n'a été démarré et aucune base n'a été modifiée. Les tests d'intégration du cycle ne pouvaient donc pas être rejoués dans l'environnement requis.
