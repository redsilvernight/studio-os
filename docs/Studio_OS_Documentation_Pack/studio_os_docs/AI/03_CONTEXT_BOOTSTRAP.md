# Bootstrap compact pour une IA

Utiliser ce texte comme contexte initial minimal:

> Tu travailles dans Studio OS, plateforme centrale d'un studio de deux developpeurs a distance. Les deux PC sont sur des reseaux differents et ne se joignent jamais directement. Le VPS central expose API/MCP/Dashboard et un stockage objet MinIO/S3. Avant de modifier un projet, recupere la tache, l'etat projet, les claims, conflits et decisions. Utilise Graphify pour cibler les fichiers. Respecte la memoire et les decisions existantes. Qwen est read-only sur la memoire partagee par defaut. Les soft locks avertissent mais ne bloquent pas Git. Journalise tout travail IA substantiel. Les gros fichiers transitent directement vers MinIO via URLs pre-signees et multipart, jamais via FastAPI. Les clients doivent supporter l'offline et la resynchronisation idempotente. Les contrats API/EVENT/AUTH/SYNC sont versionnes et ne doivent pas etre modifies unilateralement.

## Verification avant action
- Ai-je une Task ID ?
- Ai-je le ProjectState actuel ?
- Ai-je verifie les ResourceClaims ?
- Existe-t-il une Decision pertinente ?
- Ai-je cible les fichiers via Graphify/Git ?
- Mon action necessite-t-elle une review humaine ?
- Dois-je creer un AIWorkLog ou un Event ?
