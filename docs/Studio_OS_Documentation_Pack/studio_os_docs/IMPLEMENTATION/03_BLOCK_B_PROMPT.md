# Prompt Bloc B - Local Clients / Experience

Tu construis les clients locaux et l'experience utilisateur de Studio OS. Le backend est fourni par Bloc A et accessible via HTTPS. Ne construis pas un backend concurrent.

Responsabilites: StudioApiClient, MockStudioApiClient, daemon local, config, token storage, SQLite offline queue, heartbeat, CLI, dashboard, realtime, Git/Godot watchers, resource claim UX, Obsidian/Graphify adapters, context package local, RecordingProvider, markers, AI Work Ledger UI, Review Queue, Studio Producer, notifications, daily timeline, GitHub client, worker framework, TransferClient, multipart uploader/downloader, TransferQueue, drag/drop UI et CLI transfert.

Le client doit fonctionner si le serveur est temporairement indisponible. Il ne doit jamais supposer que l'autre PC est joignable. Pour les transferts, il demande au backend des URLs signees puis parle directement a MinIO/S3.

Definition de done: deux postes sur deux reseaux differents voient le meme etat, travaillent offline temporairement, resynchronisent, detectent Git/Godot, utilisent Graphify/Obsidian localement, echangent de gros fichiers resumables, et accedent aux workflows IA/review/producer.
