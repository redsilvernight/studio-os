# Modele de donnees v1

## Entites principales
Studio, User, Machine, Agent, Project, MachineProjectConfig, Task, WorkSession, ResourceClaim, Decision, AIWorkLog, Event, Transfer, TransferPart(optional), Notification, Build, Recording, RecordingMarker, MarketingCandidate.

## Relations clefs
- Project 1-N Task.
- Task 1-N WorkSession / Decision / AIWorkLog / Transfer / Event.
- Machine 1-N Heartbeats / sessions / agents.
- Transfer relie sender, recipient, project/task optionnels et object_key MinIO.

## Transfer
Champs minimum: id, transfer_code, sender_user_id, recipient_user_id, project_id, task_id, category, filename, object_key, content_type, size_bytes, sha256, status, expires_at, created_at, uploaded_at, downloaded_at, deleted_at.

## ResourceClaim
TTL obligatoire. Un claim expire n'est plus considere actif. Un claim de dossier entre en conflit avec un claim de fichier descendant.
