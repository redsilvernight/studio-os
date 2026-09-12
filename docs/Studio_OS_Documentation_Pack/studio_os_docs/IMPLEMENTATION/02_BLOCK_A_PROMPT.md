# Prompt Bloc A - Cloud/Core

Tu construis le Cloud/Core de Studio OS. Deux developpeurs travaillent depuis deux reseaux differents. Le serveur central sera heberge sur VPS OVH. Aucun acces direct entre postes n'est requis.

Responsabilites: FastAPI, PostgreSQL, MCP, auth, users/machines/agents/projects/tasks/sessions/claims/decisions/events/AIWorkLog, ProjectState, conflict detection, realtime, idempotency, StorageProvider/MinIO, TransferService, signed URLs, multipart coordination, quotas/retention, Docker/Caddy, backups, tests et contrats.

Priorite absolue: produire et maintenir les contrats TECH/02_API_CONTRACT.md, TECH/03_EVENT_CONTRACT.md, TECH/04_AUTH_SYNC_CONTRACT.md et les schemas partages afin que Bloc B avance avec mocks.

Ne construis pas le dashboard, daemon local, watchers, Graphify/Obsidian local, recorder ou Producer UI.

Pour les gros fichiers: ne jamais proxyfier le contenu via FastAPI. Fournir metadata, autorisation et URLs S3/MinIO pre-signees. Supporter multipart, resume, hash et expiration.

Definition de done: docker compose lance Caddy/API/MCP/Postgres/MinIO; deux machines distantes peuvent publier heartbeat, partager taches/claims/decisions/events, les MCP tools fonctionnent, les transferts volumineux reprennent, et les sauvegardes sont documentees.
