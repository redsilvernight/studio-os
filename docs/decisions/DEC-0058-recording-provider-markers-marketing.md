---
id: DEC-0058
title: 'Etape 9.2 (Bloc B) : RecordingProvider, markers video et MarketingCandidate locaux'
status: active
date: '2026-09-15'
superseded_by: null
source: docs/DECISIONS.md
---

# DEC-0058 — Etape 9.2, Bloc B : RecordingProvider, markers et MarketingCandidate

Sous-etape 9.2 de `docs/ROADMAP_CORRECTIONS_AUDIT.md` (etape 9, « Producer,
media et hardening final »). Bloc B uniquement : aucun endpoint, service ou
modele de base de donnees n'est ajoute. Les `EventType`
`recording.started`, `recording.finished`, `recording.marker.created`,
`marketing.candidate.created` et `marketing.post.published` existent deja dans
`packages/studio-contracts/src/studio_contracts/events.py`
(`TECH/03_EVENT_CONTRACT.md`) ; cette decision fixe seulement comment le
client local les produit. `DEC-0024` (le client ne depend jamais de
`studio_api`) reste respecte : `packages/studio-client` n'importe rien du
serveur.

## Decision

1. **Un seul paquet local, `studio_client.recording`.** `RecordingProvider`
   orchestre, `Marker` et `MarketingCandidate` sont des dataclasses gelees,
   `RecordingError` porte un `reason` machine-lisible. Le paquet n'importe ni
   `httpx` ni `studio_api` : la seule ecriture passe par un protocole
   `EventSink` (`async post_event(event) -> object`), structurellement
   satisfait par la methode existante `StudioApiClient.post_event`
   (`packages/studio-client/src/studio_client/api_client.py`). Un faux sink
   remplace le client dans les tests sans reseau.

2. **Association session / tache / recording.** Un `Recording` porte
   `recording_id`, `project_id`, `started_at`, `task_id?`, `session_id?`,
   `finished_at?`. Le `RecordingProvider` lit/ecrit l'enregistrement actif via
   un protocole `ActiveRecordingStore` ; l'implementation
   `OutboxRecordingStore` la persiste dans `sync_state` du outbox SQLite local
   (cle `recording:active`), **jamais** cote serveur. C'est une donnee locale,
   pas la file offline. Le defaut `NullRecordingStore` signifie « aucun
   enregistrement actif ». Un `Marker` est attache : un argument explicite
   (`--project`/`--task`/`--session`) l'emporte toujours ; sinon
   l'enregistrement actif fournit projet/tache/session. Sans `--project` ni
   enregistrement actif, le marker est refuse (`no_active_recording`) plutot
   qu'invente.

3. **Format du marker.** `marker_id` (UUID client), `label` normalise
   (espaces reduits, 1 a 200 caracteres), `recorded_at` (UTC ISO-8601),
   `offset_seconds?` (position dans l'enregistrement, connu seulement si un
   enregistrement est actif), `task_id?`, `session_id?`, `recording_id?`.
   `project_id` et `task_id` voyagent dans l'enveloppe d'evenement ; le
   `payload` reste compact : `marker_id`, `label`, `recorded_at`, puis
   `offset_seconds`/`session_id`/`recording_id` seulement s'ils sont connus.
   Aucun dump du contexte d'enregistrement.

4. **Generation de MarketingCandidate.** `MarketingCandidate.from_marker`
   produit une plage pure `[marker - pre_roll, marker + post_roll]`
   (defaut 15 s / 15 s, ajustable), validee (`end > start`), jamais des octets
   video : le pipeline marketing lit le segment localement. L'evenement
   `marketing.candidate.created` porte `candidate_id`, `marker_id`, `label`,
   `start`, `end`, `duration_seconds`, plus `session_id`/`recording_id` si
   connus. Le worker MarketingCandidate de `HUMAN/03` correspond a
   `create_marketing_candidate(marker, ...)`.

5. **Emission.** Chaque action produit exactement un evenement via
   `EventSink` ; l'`event_id` est genere par le client et stable, ce qui est
   la cle de rejeu idempotente du serveur (`TECH/04`). `recording.started` et
   `recording.finished` sont **manuels** (le `RecordingProvider` ne detecte
   rien tout seul) : l'auto-demarrage a la Godot/capture de `HUMAN/02` reste
   une integration future, pas une affirmation de cette sous-etape.

6. **Hors-ligne.** Les ecritures du CLI interactif (`studio mark`) exigent la
   connectivite et remontent une erreur courte, comme les autres commandes
   d'ecriture du CLI (`tasks create`, `claims create`) ; elles ne sont pas
   mises en file. L'`event_id` stable permet a un futur `EventSink` adosse au
   outbox (`pending_events`) de rejouer sans doublon. La table
   `pending_markers` reste inutilisee : un marker est un evenement, il
   n'ajoute pas de cible serveur distincte (`outbox/replay.py`).

7. **CLI.** `studio mark "<label>" [--project UUID] [--task UUID]
   [--session UUID] [--at VALEUR] [--json]`. `--at` accepte un ISO-8601
   absolu ou un decalage signe (`+90`, `-45s`, `+2m`), mesure depuis le debut
   de l'enregistrement actif s'il existe, sinon depuis maintenant.

## Consequences

- Aucun contrat n'est modifie : types d'evenements pre-existants, seuls des
  membres de `payload` apparaissent (additif, tolerant). Pas de
  `contract-guardian` requis.
- Aucune nouvelle entite DB/serveur ; `docs/ROADMAP_CORRECTIONS_AUDIT.md` 9.2
  est satisfaite cote Bloc B.
- `studio_client/__init__.py` n'expose pas (encore) ces classes ; le paquet
  s'importe directement, comme `studio_client.knowledge`.
- Un enregistrement actif orphelin (crash avant `finish_recording`) reste
  lisible dans `sync_state` ; sa resolution revient a l'appelant, aucune
  expiration implicite n'est inventee.

## Preuves

- `tests/client/test_recording_provider.py` (18 tests) et
  `tests/client/test_recording_cli.py` (9 tests) verts, sans PostgreSQL ni
  MinIO : faux sink + `httpx.MockTransport`, etat SQLite sous `tmp_path`.
- `uv run ruff check` et `uv run ruff format --check` verts sur les racines
  touchees ; `uv run mypy --strict packages/studio-client/src
  packages/studio-contracts/src` vert.
- `uv run pytest tests/client/test_recording_provider.py
  tests/client/test_recording_cli.py -v` : 27 passed.

## Compatibilite

Bloc B local uniquement. Les `EventType` et l'enveloppe d'evenement de
`TECH/03_EVENT_CONTRACT.md` sont utilises tels quels ; seul `payload` grandit,
conformement a la regle de compatibilite des contrats.
