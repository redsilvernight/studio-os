# Obsidian & Graphify Integration

## Memoire
Trois niveaux: private, project, studio. Private n'est jamais synchronise automatiquement. Project/Studio peuvent etre proposes puis approuves.

### MemoryProvider
search, read, propose, write_if_authorized, append_task_log, create_decision_note.

### Qwen
Lecture seule sur project/studio par defaut.

## Graphify
Graphify est local et n'a pas besoin d'etre copie sur le VPS.

### GraphProvider
refresh_graph, query, relevant_files, dependencies, related_symbols.

## Context Package
Le serveur compose contexte partage; le client complete avec Git, Graphify, fichiers et memoire locale. Manifest versionne et trace les sources.
